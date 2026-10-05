# apps/ventes_clients/views.py
# ============================================================
# IMPORTATIONS AVEC ALIAS
# ============================================================

from django.db.models import Sum, Q
from decimal import Decimal
import logging
from io import BytesIO
import json
from datetime import date, timedelta
import datetime as dt

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.http import HttpResponse
from django.db import transaction
from django.core.exceptions import ValidationError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from PIL import Image as PILImage

# === Modèles ===
from .models import (
    Client, ClientWallet, Vente, LigneVente, Paiement, Facture,
    Avoir, Taxe, Remise, Devis, LigneDevis
)
from produits_stocks.models import Stock, StockMovement, Warehouse
from users.permissions import IsAdmin, IsGestionnaire, IsCaissier

# === Serializers ===
from .serializers import (
    ClientSerializer, ClientListSerializer, ClientWalletSerializer,
    VenteListSerializer, VenteDetailSerializer,
    VenteCreateSerializer, VenteUpdateSerializer,
    VenteStatusUpdateSerializer,
    LigneVenteSerializer, LigneVenteCreateSerializer,
    PaiementSerializer, PaiementCreateSerializer,
    FactureSerializer, FactureCreateSerializer,
    AvoirSerializer, AvoirCreateSerializer,
    TaxeSerializer, RemiseSerializer,
    DevisListSerializer, DevisDetailSerializer,
    DevisCreateSerializer, DevisUpdateSerializer,
    DevisStatusUpdateSerializer,
    LigneDevisSerializer, LigneDevisCreateSerializer,
    WalletDepositSerializer, ClientWalletCreateSerializer,
    WalletTransactionSerializer
)

# === Trésorerie ===
from tresorerie.models import MouvementTresorerie, Caisse

logger = logging.getLogger(__name__)


# ============================================================
# FONCTION UTILITAIRE POUR CRÉER UN MOUVEMENT DE PAIEMENT
# ============================================================
def creer_mouvement_paiement_manuel(paiement, facture, request_user):
    """
    Crée un mouvement de trésorerie pour un paiement.
    Retourne le mouvement créé ou None.
    """
    logger.info(
        f"🔍 creer_mouvement_paiement_manuel - paiement {paiement.id}, facture {facture.invoice_number}")

    sale = facture.sale
    if not sale:
        logger.warning(
            f"❌ Paiement {paiement.id} : aucune vente associée à la facture {facture.invoice_number}")
        return None

    logger.info(
        f"   Vente associée : {sale.invoice_number}, entrepôt={sale.warehouse}")

    if not sale.warehouse:
        logger.warning(
            f"❌ Paiement {paiement.id} : la vente {sale.invoice_number} n'a pas d'entrepôt")
        return None

    try:
        from tresorerie.models import MouvementTresorerie, Caisse, CompteBancaire

        # ✅ VÉRIFIER SI UN MOUVEMENT EXISTE DÉJÀ
        existing_movement = MouvementTresorerie.objects.filter(
            source_type='paiement_client',
            source_id=paiement.id
        ).first()

        if existing_movement:
            logger.info(
                f"ℹ️ Paiement {paiement.id} : mouvement déjà existant ({existing_movement.reference})")
            return existing_movement

        # Récupérer la caisse ou le compte de destination
        caisse = None
        compte = None

        if hasattr(paiement, 'caisse_destination_id') and paiement.caisse_destination_id:
            try:
                caisse = Caisse.objects.get(id=paiement.caisse_destination_id)
                logger.info(f"✅ Caisse trouvée : {caisse.nom}")
            except Caisse.DoesNotExist:
                logger.warning(
                    f"⚠️ Caisse ID {paiement.caisse_destination_id} non trouvée")

        if hasattr(paiement, 'compte_destination_id') and paiement.compte_destination_id:
            try:
                compte = CompteBancaire.objects.get(
                    id=paiement.compte_destination_id)
                logger.info(f"✅ Compte trouvé : {compte.nom}")
            except CompteBancaire.DoesNotExist:
                logger.warning(
                    f"⚠️ Compte ID {paiement.compte_destination_id} non trouvé")

        if not caisse and not compte:
            logger.info(
                "ℹ️ Aucune destination spécifiée, recherche de la caisse par défaut...")
            caisse = Caisse.objects.filter(
                warehouse=sale.warehouse,
                is_default=True
            ).first()

            if caisse:
                logger.info(f"✅ Caisse par défaut trouvée : {caisse.nom}")
            else:
                caisse = Caisse.objects.filter(
                    warehouse=sale.warehouse,
                    is_active=True
                ).first()
                if caisse:
                    logger.info(f"✅ Caisse active trouvée : {caisse.nom}")

        if not caisse and not compte:
            logger.warning(
                f"❌ Paiement {paiement.id} : aucune caisse ou compte disponible pour l'entrepôt {sale.warehouse}")
            return None

        logger.info(
            f"✅ Destination finale : {caisse.nom if caisse else compte.nom}")

        # Créer le mouvement d'encaissement
        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='encaissement',
            warehouse=sale.warehouse,
            source_type='paiement_client',
            source_id=paiement.id,
            source_reference=paiement.reference or f"PAY-{paiement.id}",
            montant=paiement.amount,
            mode_paiement=paiement.method,
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=paiement.payment_date,
            date_valeur=paiement.payment_date.date(),
            status='effectue',
            libelle=f"Paiement client - {facture.invoice_number} - {facture.client.name}",
            created_by=request_user
        )

        if caisse:
            caisse.solde_actuel += paiement.amount
            caisse.save(update_fields=['solde_actuel', 'updated_at'])
            logger.info(
                f"💰 Caisse {caisse.nom} augmentée de {paiement.amount:,.0f} FCFA")

        if compte:
            compte.solde_actuel += paiement.amount
            compte.save(update_fields=['solde_actuel', 'updated_at'])
            logger.info(
                f"💰 Compte {compte.nom} augmenté de {paiement.amount:,.0f} FCFA")

        logger.info(
            f"✅ Mouvement d'encaissement créé pour paiement {paiement.id} : {mouvement.reference}")
        return mouvement

    except ImportError as e:
        logger.error(f"❌ Erreur d'importation du module trésorerie: {e}")
        return None
    except Exception as e:
        logger.error(
            f"❌ Erreur lors de la création du mouvement pour paiement {paiement.id} : {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================
# CLIENT VIEWSET
# ============================================================
class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return ClientListSerializer
        return ClientSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search)
            )
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)
        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)
        is_favorite = self.request.query_params.get('is_favorite')
        if is_favorite == 'true':
            queryset = queryset.filter(is_favorite=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def sales(self, request, pk=None):
        client = self.get_object()
        sales = client.sales.all().order_by('-sale_date')
        serializer = VenteListSerializer(sales, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def devis(self, request, pk=None):
        client = self.get_object()
        devis = client.devis.all().order_by('-devis_date')
        serializer = DevisListSerializer(devis, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        client = self.get_object()
        sales = client.sales.all()
        stats = {
            'total_orders': sales.count(),
            'total_purchases': sales.aggregate(total=Sum('total'))['total'] or 0,
            'orders_by_status': {},
            'average_order_value': 0,
        }
        for status_choice in Vente.STATUS_CHOICES:
            status_code = status_choice[0]
            count = sales.filter(status=status_code).count()
            if count > 0:
                stats['orders_by_status'][status_code] = count
        if stats['total_orders'] > 0:
            stats['average_order_value'] = stats['total_purchases'] / \
                stats['total_orders']
        return Response(stats)

    # ============================================================
    # Récupérer les factures impayées d'un client
    # ============================================================
    @action(detail=True, methods=['get'], url_path='unpaid-invoices')
    def unpaid_invoices(self, request, pk=None):
        """
        Récupère les factures impayées d'un client
        GET /clients/{id}/unpaid-invoices/
        """
        client = self.get_object()
        unpaid_statuses = ['sent', 'overdue', 'partial']

        factures = Facture.objects.filter(
            client=client,
            status__in=unpaid_statuses
        ).order_by('due_date')

        # Filtrer celles qui ont un reste à payer
        factures_impayees = [
            f for f in factures if f.remaining_amount > 0
        ]

        serializer = FactureSerializer(
            factures_impayees,
            many=True,
            context={'request': request}
        )

        return Response(serializer.data)

    # ============================================================
    # ✅ NOUVEAU : Récupérer le wallet d'un client
    # ============================================================
    @action(detail=True, methods=['get'], url_path='wallet')
    def get_client_wallet(self, request, pk=None):
        """
        Récupère le wallet d'un client spécifique
        GET /clients/{id}/wallet/
        """
        client = self.get_object()
        wallet, created = ClientWallet.objects.get_or_create(client=client)
        serializer = ClientWalletSerializer(wallet)
        return Response(serializer.data)


# ============================================================
# DEVIS VIEWSET
# ============================================================
class DevisViewSet(viewsets.ModelViewSet):
    queryset = Devis.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return DevisListSerializer
        elif self.action == 'create':
            return DevisCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return DevisUpdateSerializer
        return DevisDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(devis_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(client_name__icontains=search)
            )
        client = self.request.query_params.get('client')
        if client:
            queryset = queryset.filter(client_id=client)
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(devis_date__date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(devis_date__date__lte=date_to)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        devis = self.get_object()
        serializer = DevisStatusUpdateSerializer(data=request.data)
        if serializer.is_valid():
            old_status = devis.status
            new_status = serializer.validated_data['status']
            notes = serializer.validated_data.get('notes', '')
            devis.status = new_status
            if notes:
                devis.notes = devis.notes + '\n' + notes if devis.notes else notes
            devis.save()
            return Response({
                'status': devis.status,
                'old_status': old_status,
                'message': f'Statut changé de {old_status} à {new_status}',
                'devis_number': devis.devis_number
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def convert_to_sale(self, request, pk=None):
        devis = self.get_object()
        if devis.status != 'accepted':
            return Response(
                {"error": "Seul un devis accepté peut être converti en vente"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if devis.sale:
            return Response(
                {"error": "Ce devis a déjà été converti en vente"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not devis.warehouse:
            return Response(
                {"error": "L'entrepôt doit être défini pour convertir le devis en vente"},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            vente = devis.convert_to_sale(user=request.user)
            return Response({
                'message': 'Devis converti en vente avec succès',
                'sale': VenteDetailSerializer(vente, context={'request': request}).data,
                'devis': DevisDetailSerializer(devis, context={'request': request}).data
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": f"Erreur lors de la conversion: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        devis = self.get_object()
        if not devis.qr_code:
            devis.generate_qr_code()
            devis.save()
        if devis.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(devis.qr_code.url),
                'qr_code_data': devis.qr_code_data
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================
# VENTE VIEWSET - COMPLET CORRIGÉ
# ============================================================
class VenteViewSet(viewsets.ModelViewSet):
    queryset = Vente.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return VenteListSerializer
        elif self.action == 'create':
            return VenteCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return VenteUpdateSerializer
        return VenteDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(client_name__icontains=search) |
                Q(order_number__icontains=search)
            )
        client = self.request.query_params.get('client')
        if client:
            queryset = queryset.filter(client_id=client)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            status_list = status_filter.split(',')
            queryset = queryset.filter(status__in=status_list)
        payment_status = self.request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(sale_date__date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(sale_date__date__lte=date_to)
        warehouse = self.request.query_params.get('warehouse')
        if warehouse:
            queryset = queryset.filter(warehouse_id=warehouse)
        min_total = self.request.query_params.get('min_total')
        if min_total:
            queryset = queryset.filter(total__gte=min_total)
        max_total = self.request.query_params.get('max_total')
        if max_total:
            queryset = queryset.filter(total__lte=max_total)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ================================================================
    # 1. RÉCUPÉRER LES VENTES PAR DATE
    # ================================================================
    @action(detail=False, methods=['get'], url_path='by-date')
    def get_by_date(self, request):
        """
        Récupère les ventes par date avec pagination et filtres
        """
        date_str = request.query_params.get('date')
        if date_str:
            try:
                target_date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "Format de date invalide. Utilisez YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            target_date = timezone.now().date()

        date_start = dt.datetime.combine(target_date, dt.datetime.min.time())
        date_end = dt.datetime.combine(target_date, dt.datetime.max.time())

        queryset = self.get_queryset().filter(
            sale_date__gte=date_start,
            sale_date__lte=date_end
        ).order_by('-sale_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            status_list = status_filter.split(',')
            queryset = queryset.filter(status__in=status_list)

        payment_status = request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(client_name__icontains=search)
            )

        stats = {
            'total': queryset.count(),
            'total_amount': queryset.aggregate(total=Sum('total'))['total'] or 0,
            'by_status': {
                'draft': queryset.filter(status='draft').count(),
                'confirmed': queryset.filter(status='confirmed').count(),
                'paid': queryset.filter(status='paid').count(),
                'delivered': queryset.filter(status='delivered').count(),
                'cancelled': queryset.filter(status='cancelled').count(),
                'returned': queryset.filter(status='returned').count(),
            },
            'by_payment_status': {
                'pending': queryset.filter(payment_status='pending').count(),
                'partial': queryset.filter(payment_status='partial').count(),
                'paid': queryset.filter(payment_status='paid').count(),
            }
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = VenteListSerializer(page, many=True)
            return self.get_paginated_response({
                'date': target_date.isoformat(),
                'stats': stats,
                'results': serializer.data
            })

        serializer = VenteListSerializer(queryset, many=True)
        return Response({
            'date': target_date.isoformat(),
            'stats': stats,
            'results': serializer.data
        })

    # ================================================================
    # 2. RÉCUPÉRER LES VENTES SUR UNE PLAGE DE DATES
    # ================================================================
    @action(detail=False, methods=['get'], url_path='date-range')
    def get_date_range(self, request):
        """
        Récupère les ventes sur une plage de dates
        """
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if not date_from or not date_to:
            return Response(
                {"error": "Les paramètres date_from et date_to sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
            date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            return Response(
                {"error": "Format de date invalide. Utilisez YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST
            )

        date_end = date_end.replace(hour=23, minute=59, second=59)

        queryset = self.get_queryset().filter(
            sale_date__gte=date_start,
            sale_date__lte=date_end
        ).order_by('-sale_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            status_list = status_filter.split(',')
            queryset = queryset.filter(status__in=status_list)

        payment_status = request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(client_name__icontains=search)
            )

        stats = {
            'total': queryset.count(),
            'total_amount': queryset.aggregate(total=Sum('total'))['total'] or 0,
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = VenteListSerializer(page, many=True)
            return self.get_paginated_response({
                'date_from': date_from,
                'date_to': date_to,
                'stats': stats,
                'results': serializer.data
            })

        serializer = VenteListSerializer(queryset, many=True)
        return Response({
            'date_from': date_from,
            'date_to': date_to,
            'stats': stats,
            'results': serializer.data
        })

    # ================================================================
    # 3. CONFIRMER UNE VENTE
    # ================================================================
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        Confirme une vente :
        1. Vérifie le stock
        2. Déduit le stock
        3. Crée un mouvement de trésorerie (encaissement)
        4. Génère la facture automatiquement
        """
        vente = self.get_object()

        if vente.status != 'draft':
            return Response(
                {"error": "Seule une vente en brouillon peut être confirmée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not vente.warehouse:
            return Response(
                {"error": "Un entrepôt est requis pour confirmer la vente"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 1. Vérification du stock
            stock_errors = []
            for line in vente.lines.all():
                stock = Stock.objects.filter(
                    product=line.product,
                    warehouse=vente.warehouse
                ).first()
                if not stock or stock.available_quantity < line.quantity:
                    stock_errors.append(
                        f"{line.product.name}: disponible {stock.available_quantity if stock else 0}, demandé {line.quantity}"
                    )
            if stock_errors:
                return Response({
                    "error": "Stock insuffisant pour les produits suivants:",
                    "details": stock_errors
                }, status=status.HTTP_400_BAD_REQUEST)

            # 2. Si pas de client, nom par défaut
            if not vente.client and not vente.client_name:
                vente.client_name = "Client anonyme"
                vente.save(update_fields=['client_name'])

            # 3. Passer la vente en 'confirmed'
            vente.status = 'confirmed'
            vente.save()

            # 4. CRÉATION DU MOUVEMENT DE TRÉSORERIE
            mouvement = None
            try:
                from tresorerie.models import MouvementTresorerie, Caisse

                existing_movement = MouvementTresorerie.objects.filter(
                    source_type='vente',
                    source_id=vente.id
                ).first()

                if not existing_movement:
                    caisse = Caisse.objects.filter(
                        warehouse=vente.warehouse,
                        is_default=True
                    ).first()

                    if caisse:
                        mouvement = MouvementTresorerie.objects.create(
                            type_mouvement='encaissement',
                            warehouse=vente.warehouse,
                            source_type='vente',
                            source_id=vente.id,
                            source_reference=vente.invoice_number,
                            montant=vente.total,
                            mode_paiement='especes',
                            caisse=caisse,
                            date_mouvement=vente.sale_date,
                            date_valeur=vente.sale_date.date(),
                            status='effectue',
                            libelle=f"Vente {vente.invoice_number} - {vente.client_name}",
                            created_by=request.user
                        )

                        caisse.solde_actuel += vente.total
                        caisse.save(update_fields=[
                                    'solde_actuel', 'updated_at'])

                        logger.info(
                            f"✅ Mouvement d'encaissement créé pour la vente {vente.invoice_number}")
                        logger.info(
                            f"💰 Caisse {caisse.nom} augmentée de {vente.total:,.0f} FCFA")
                    else:
                        logger.warning(
                            f"Aucune caisse par défaut pour l'entrepôt {vente.warehouse}")
                else:
                    logger.info(
                        f"Mouvement déjà existant pour la vente {vente.invoice_number}")
                    mouvement = existing_movement

            except ImportError:
                logger.warning("Module tresorerie non disponible")
            except Exception as e:
                logger.error(f"Erreur création mouvement trésorerie: {e}")

            # 5. Génération de la facture
            from .models import Facture

            facture = Facture.objects.filter(sale=vente).first()
            if not facture:
                last_facture = Facture.objects.order_by('-id').first()
                num = 1
                if last_facture and last_facture.invoice_number:
                    try:
                        num = int(
                            last_facture.invoice_number.split('-')[-1]) + 1
                    except (ValueError, IndexError):
                        num = 1
                invoice_number = f"FAC-{date.today().year}-{num:04d}"

                facture = Facture.objects.create(
                    invoice_number=invoice_number,
                    sale=vente,
                    client=vente.client,
                    invoice_date=date.today(),
                    due_date=date.today() + timedelta(days=30),
                    subtotal=vente.subtotal,
                    tax_amount=vente.tax_amount,
                    total=vente.total,
                    status='sent',
                    notes=f"Facture générée automatiquement depuis la vente {vente.invoice_number}"
                )
                facture.generate_qr_code()
                facture.save()

            # 6. Mise à jour du statut de paiement
            vente.amount_due = vente.total - vente.amount_paid
            if vente.amount_due <= 0:
                vente.payment_status = 'paid'
            elif vente.amount_paid > 0:
                vente.payment_status = 'partial'
            else:
                vente.payment_status = 'pending'
            vente.save(update_fields=['amount_due', 'payment_status'])

            return Response({
                'status': vente.status,
                'message': 'Vente confirmée avec succès',
                'invoice_number': vente.invoice_number,
                'facture_generée': facture is not None,
                'facture_number': facture.invoice_number if facture else None,
                'mouvement_cree': mouvement is not None,
                'payment_status': vente.payment_status,
                'amount_due': vente.amount_due
            })

        except Exception as e:
            vente.status = 'draft'
            vente.save(update_fields=['status', 'updated_at'])
            logger.exception("Erreur lors de la confirmation de la vente")
            return Response(
                {"error": f"Erreur lors de la confirmation: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ================================================================
    # 4. ENREGISTRER UN PAIEMENT SUR UNE VENTE
    # ================================================================
    @action(detail=True, methods=['post'])
    def register_payment(self, request, pk=None):
        """
        Enregistre un paiement sur une vente
        """
        from decimal import Decimal
        from django.db import transaction
        from django.db.models import Sum

        vente = self.get_object()
        logger.info(f"🔔 register_payment - vente {vente.invoice_number}")

        amount = request.data.get('amount')
        method = request.data.get('method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')
        caisse_destination_id = request.data.get('caisse_destination_id')
        compte_destination_id = request.data.get('compte_destination_id')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        amount_due = vente.total - vente.amount_paid
        if amount > amount_due:
            return Response(
                {"error": f"Le montant dépasse le solde restant ({amount_due:,.0f} FCFA)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            facture = vente.invoices.first()
            if not facture:
                return Response(
                    {"error": "Aucune facture trouvée pour cette vente"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement sur la vente {vente.invoice_number}",
                received_by=request.user,
                caisse_destination_id=caisse_destination_id,
                compte_destination_id=compte_destination_id
            )
            logger.info(f"✅ Paiement créé : ID {paiement.id}")

            total_paid_facture = facture.paiements.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            facture.amount_paid = total_paid_facture
            if facture.amount_paid >= facture.total:
                facture.status = 'paid'
            elif facture.amount_paid > 0:
                facture.status = 'partial'
            facture.save()

            vente.amount_paid += amount
            vente.amount_due = vente.total - vente.amount_paid
            if vente.amount_due <= 0:
                vente.payment_status = 'paid'
                vente.status = 'paid'
            elif vente.amount_paid > 0:
                vente.payment_status = 'partial'
            else:
                vente.payment_status = 'pending'
            vente.save()

            # CRÉER LE MOUVEMENT DE TRÉSORERIE
            try:
                from tresorerie.models import MouvementTresorerie, Caisse, CompteBancaire

                caisse = None
                compte = None

                if caisse_destination_id:
                    try:
                        caisse = Caisse.objects.get(id=caisse_destination_id)
                    except Caisse.DoesNotExist:
                        pass

                if compte_destination_id:
                    try:
                        compte = CompteBancaire.objects.get(
                            id=compte_destination_id)
                    except CompteBancaire.DoesNotExist:
                        pass

                if not caisse and not compte:
                    caisse = Caisse.objects.filter(
                        warehouse=vente.warehouse,
                        is_default=True
                    ).first()

                if caisse or compte:
                    existing_movement = MouvementTresorerie.objects.filter(
                        source_type='paiement_client',
                        source_id=paiement.id
                    ).first()

                    if not existing_movement:
                        mouvement = MouvementTresorerie.objects.create(
                            type_mouvement='encaissement',
                            warehouse=vente.warehouse,
                            source_type='paiement_client',
                            source_id=paiement.id,
                            source_reference=paiement.reference or f"PAY-{paiement.id}",
                            montant=paiement.amount,
                            mode_paiement=paiement.method,
                            caisse=caisse,
                            compte_bancaire=compte,
                            date_mouvement=paiement.payment_date,
                            date_valeur=paiement.payment_date.date(),
                            status='effectue',
                            libelle=f"Paiement vente {vente.invoice_number} - {vente.client_name}",
                            created_by=request.user
                        )

                        if caisse:
                            caisse.solde_actuel += paiement.amount
                            caisse.save(update_fields=[
                                        'solde_actuel', 'updated_at'])
                            logger.info(
                                f"💰 Caisse {caisse.nom} augmentée de {paiement.amount:,.0f} FCFA")

                        if compte:
                            compte.solde_actuel += paiement.amount
                            compte.save(update_fields=[
                                        'solde_actuel', 'updated_at'])
                            logger.info(
                                f"💰 Compte {compte.nom} augmenté de {paiement.amount:,.0f} FCFA")

                        logger.info(
                            f"✅ Mouvement d'encaissement créé pour le paiement {paiement.id}")
                    else:
                        logger.info(
                            f"Mouvement déjà existant pour le paiement {paiement.id}")
                else:
                    logger.warning(
                        f"Aucune destination pour le paiement {paiement.id}")

            except ImportError:
                logger.warning("Module tresorerie non disponible")
            except Exception as e:
                logger.error(f"Erreur création mouvement: {e}")

        return Response({
            'status': 'success',
            'message': 'Paiement enregistré avec succès',
            'amount_paid': vente.amount_paid,
            'amount_due': vente.amount_due,
            'payment_status': vente.payment_status
        }, status=status.HTTP_201_CREATED)

    # ================================================================
    # 5. MISE À JOUR DU STATUT
    # ================================================================
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        vente = self.get_object()
        status_value = request.data.get('status')
        notes = request.data.get('notes', '')

        if not status_value:
            return Response(
                {"error": "Le statut est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_statuses = ['draft', 'confirmed',
                            'paid', 'delivered', 'cancelled', 'returned']
        if status_value not in allowed_statuses:
            return Response(
                {"error": f"Statut invalide. Choisir parmi: {', '.join(allowed_statuses)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = vente.status
        is_confirming = old_status == 'draft' and status_value == 'confirmed'

        if is_confirming:
            return self.confirm(request, pk)

        try:
            vente.status = status_value
            if notes:
                vente.notes = vente.notes + '\n' + notes if vente.notes else notes
            vente.save()

            return Response({
                'status': vente.status,
                'old_status': old_status,
                'message': f'Statut changé de {old_status} à {status_value}',
                'invoice_number': vente.invoice_number
            })
        except Exception as e:
            return Response(
                {"error": f"Erreur lors du changement de statut: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ================================================================
    # 6. MARQUER COMME PAYÉ
    # ================================================================
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """
        Marque la vente comme payée en créant automatiquement un paiement
        pour le montant restant dû.
        """
        from decimal import Decimal
        from django.db import transaction
        from django.db.models import Sum

        vente = self.get_object()

        if vente.status not in ['confirmed', 'delivered']:
            return Response(
                {"error": "Seule une vente confirmée ou livrée peut être marquée comme payée."},
                status=status.HTTP_400_BAD_REQUEST
            )

        amount_due = vente.amount_due
        if amount_due <= 0:
            return Response(
                {"error": "Cette vente est déjà entièrement payée."},
                status=status.HTTP_400_BAD_REQUEST
            )

        facture = vente.invoices.first()
        if not facture:
            facture = vente.generate_invoice()
            if not facture:
                return Response(
                    {"error": "Impossible de générer une facture pour cette vente."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        with transaction.atomic():
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount_due,
                method='cash',
                reference='',
                notes='Paiement automatique (marquer comme payé)',
                received_by=request.user
            )
            logger.info(f"✅ Paiement automatique créé : ID {paiement.id}")

            total_paid_facture = facture.paiements.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            facture.amount_paid = total_paid_facture
            facture.status = 'paid' if total_paid_facture >= facture.total else 'partial'
            facture.save()

            vente.amount_paid += amount_due
            vente.amount_due = vente.total - vente.amount_paid
            if vente.amount_due <= 0:
                vente.payment_status = 'paid'
                vente.status = 'paid'
            elif vente.amount_paid > 0:
                vente.payment_status = 'partial'
            else:
                vente.payment_status = 'pending'
            vente.save()

            # Créer le mouvement de trésorerie
            try:
                from tresorerie.models import MouvementTresorerie, Caisse

                caisse = Caisse.objects.filter(
                    warehouse=vente.warehouse,
                    is_default=True
                ).first()

                if not caisse:
                    caisse = Caisse.objects.filter(
                        warehouse=vente.warehouse,
                        is_active=True
                    ).first()

                if caisse:
                    mouvement_existant = MouvementTresorerie.objects.filter(
                        source_type='paiement_client',
                        source_id=paiement.id
                    ).first()
                    if not mouvement_existant:
                        mouvement = MouvementTresorerie.objects.create(
                            type_mouvement='encaissement',
                            warehouse=vente.warehouse,
                            source_type='paiement_client',
                            source_id=paiement.id,
                            source_reference=paiement.reference or f"PAY-{paiement.id}",
                            montant=paiement.amount,
                            mode_paiement=paiement.method,
                            caisse=caisse,
                            compte_bancaire=None,
                            date_mouvement=paiement.payment_date,
                            date_valeur=paiement.payment_date.date(),
                            status='effectue',
                            libelle=f"Paiement vente {vente.invoice_number} - {vente.client_name}",
                            created_by=request.user
                        )
                        caisse.solde_actuel += paiement.amount
                        caisse.save(update_fields=[
                                    'solde_actuel', 'updated_at'])
                        logger.info(
                            f"💰 Caisse {caisse.nom} augmentée de {paiement.amount:,.0f} FCFA")
                    else:
                        logger.info(
                            f"Mouvement déjà existant pour le paiement {paiement.id}")
                else:
                    logger.warning("Aucune caisse trouvée pour l'entrepôt.")
            except ImportError:
                logger.warning("Module tresorerie non disponible")
            except Exception as e:
                logger.error(
                    f"Erreur lors de la création du mouvement trésorerie : {e}")

        return Response({
            'status': 'success',
            'message': 'La vente a été marquée comme payée.',
            'amount_paid': vente.amount_paid,
            'amount_due': vente.amount_due,
            'payment_status': vente.payment_status,
            'facture_status': facture.status,
            'invoice_number': vente.invoice_number
        }, status=status.HTTP_200_OK)

    # ================================================================
    # 7. ANNULER UNE VENTE
    # ================================================================
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        vente = self.get_object()

        if vente.status in ['paid', 'delivered']:
            return Response(
                {"error": "Cette vente ne peut pas être annulée car elle est déjà payée ou livrée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            old_status = vente.status
            if old_status == 'confirmed':
                vente.restore_stock()
            vente.status = 'cancelled'
            vente.save()
            vente.generate_qr_code()
            vente.save(update_fields=['qr_code', 'qr_code_data', 'updated_at'])

            return Response({
                'status': vente.status,
                'old_status': old_status,
                'message': 'Vente annulée avec succès',
                'stock_restored': old_status == 'confirmed',
                'invoice_number': vente.invoice_number
            })
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    # ================================================================
    # 8. MARQUER COMME LIVRÉ
    # ================================================================
    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'confirmed':
            return Response(
                {"error": "Seule une vente confirmée peut être marquée comme livrée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        vente.status = 'delivered'
        vente.delivery_date = timezone.now()
        vente.delivery_status = 'delivered'
        if request.data.get('tracking_number'):
            vente.tracking_number = request.data.get('tracking_number')
        vente.save()

        return Response({
            'status': vente.status,
            'delivery_status': vente.delivery_status,
            'delivery_date': vente.delivery_date,
            'message': 'Vente marquée comme livrée',
            'invoice_number': vente.invoice_number
        })

    # ================================================================
    # 9. RETOURNER UNE VENTE
    # ================================================================
    @action(detail=True, methods=['post'])
    def return_sale(self, request, pk=None):
        vente = self.get_object()

        if vente.status not in ['delivered', 'paid']:
            return Response(
                {"error": "Seules les ventes livrées ou payées peuvent être retournées"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            vente.restore_stock()
            vente.status = 'returned'
            vente.save()

            return Response({
                'status': vente.status,
                'message': 'Vente retournée avec succès',
                'stock_restored': True,
                'invoice_number': vente.invoice_number
            })
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    # ================================================================
    # 10. RÉCUPÉRER LES PAIEMENTS
    # ================================================================
    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        vente = self.get_object()
        payments = []
        for facture in vente.invoices.all():
            for paiement in facture.paiements.all():
                payments.append(paiement)
        serializer = PaiementSerializer(
            payments, many=True, context={'request': request}
        )
        return Response(serializer.data)

    # ================================================================
    # 11. RÉCUPÉRER LES FACTURES
    # ================================================================
    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        vente = self.get_object()
        factures = vente.invoices.all()
        serializer = FactureSerializer(
            factures, many=True, context={'request': request}
        )
        return Response(serializer.data)

    # ================================================================
    # 12. GÉNÉRER LE QR CODE
    # ================================================================
    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        vente = self.get_object()
        if not vente.qr_code:
            vente.generate_qr_code()
            vente.save()
        if vente.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(vente.qr_code.url),
                'qr_code_data': vente.qr_code_data,
                'invoice_number': vente.invoice_number
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # ================================================================
    # 13. RÉCUPÉRER LES MOUVEMENTS DE STOCK
    # ================================================================
    @action(detail=True, methods=['get'])
    def stock_movements(self, request, pk=None):
        vente = self.get_object()
        movements = StockMovement.objects.filter(
            reference_type='sale',
            reference_id=vente.id
        ).order_by('-created_at')
        from produits_stocks.serializers import StockMovementSerializer
        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)

    # ================================================================
    # 14. STATISTIQUES
    # ================================================================
    @action(detail=False, methods=['get'])
    def stats(self, request):
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        ventes = Vente.objects.filter(sale_date__gte=start_date)

        total_ventes = ventes.count()
        total_montant = ventes.aggregate(total=Sum('total'))['total'] or 0
        total_paye = ventes.aggregate(total=Sum('amount_paid'))['total'] or 0
        total_due = total_montant - total_paye

        by_status = {}
        for status_choice in Vente.STATUS_CHOICES:
            status_code = status_choice[0]
            count = ventes.filter(status=status_code).count()
            if count > 0:
                by_status[status_code] = count

        by_payment_status = {}
        for status_choice in Vente.PAYMENT_STATUS_CHOICES:
            status_code = status_choice[0]
            count = ventes.filter(payment_status=status_code).count()
            if count > 0:
                by_payment_status[status_code] = count

        avg_amount = total_montant / total_ventes if total_ventes > 0 else 0

        return Response({
            'period': {
                'days': days,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': timezone.now().strftime('%Y-%m-%d')
            },
            'total_ventes': total_ventes,
            'total_montant': total_montant,
            'total_paye': total_paye,
            'total_due': total_due,
            'avg_amount': avg_amount,
            'by_status': by_status,
            'by_payment_status': by_payment_status
        })


# ============================================================
# FACTURE VIEWSET
# ============================================================
# ============================================================
# FACTURE VIEWSET - COMPLET AVEC RECHERCHE OPTIMISÉE
# ============================================================
class FactureViewSet(viewsets.ModelViewSet):
    queryset = Facture.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return FactureCreateSerializer
        return FactureSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset().select_related('client', 'sale')
        client = self.request.query_params.get('client')
        if client:
            queryset = queryset.filter(client_id=client)
        status = self.request.query_params.get('status')
        if status:
            status_list = status.split(',')
            queryset = queryset.filter(status__in=status_list)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(invoice_date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(invoice_date__lte=date_to)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(client__code__icontains=search)
            )
        return queryset

    # ================================================================
    # ✅ RECHERCHE OPTIMISÉE POUR LE FORMULAIRE DE PAIEMENT
    # ================================================================
    @action(detail=False, methods=['get'], url_path='search-unpaid')
    def search_unpaid(self, request):
        """
        Recherche paginée de factures impayées pour le formulaire de paiement.

        GET /factures/search-unpaid/?q=client&client_id=1&limit=20

        Paramètres :
        - q          : recherche texte (n° facture, nom client, code client, téléphone)
        - client_id  : filtrer par client spécifique
        - limit      : nombre max de résultats (défaut 20, max 50)
        - status     : statuts à inclure (défaut: sent,overdue,partial)
        """
        query = request.query_params.get('q', '').strip()
        client_id = request.query_params.get('client_id')
        try:
            limit = min(int(request.query_params.get('limit', 20)), 50)
        except (TypeError, ValueError):
            limit = 20

        status_param = request.query_params.get(
            'status', 'sent,overdue,partial')
        statuses = [s.strip() for s in status_param.split(',') if s.strip()]

        # Base : factures non payées
        qs = Facture.objects.select_related('client', 'sale').filter(
            status__in=statuses
        ).exclude(status='paid').order_by('due_date')

        # Filtre par client spécifique
        if client_id:
            qs = qs.filter(client_id=client_id)

        # Recherche texte
        if query:
            qs = qs.filter(
                Q(invoice_number__icontains=query) |
                Q(client__name__icontains=query) |
                Q(client__code__icontains=query) |
                Q(client__phone__icontains=query)
            )

        # Filtrer uniquement celles avec un reste à payer > 0
        factures = [f for f in qs if f.remaining_amount > 0][:limit]

        serializer = FactureSerializer(
            factures, many=True, context={'request': request}
        )

        return Response({
            'count': len(factures),
            'results': serializer.data
        })

    # ================================================================
    # ✅ Récupérer les factures impayées d'un client (ancien endpoint)
    # ================================================================
    @action(detail=False, methods=['get'], url_path='unpaid')
    def unpaid_invoices(self, request):
        """
        Récupère les factures impayées d'un client
        GET /factures/unpaid/?client_id=1
        """
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response(
                {"error": "Le paramètre client_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        unpaid_statuses = ['sent', 'overdue', 'partial']

        factures = Facture.objects.filter(
            client_id=client_id,
            status__in=unpaid_statuses
        ).order_by('due_date')

        factures_impayees = [
            f for f in factures if f.remaining_amount > 0
        ]

        serializer = FactureSerializer(
            factures_impayees,
            many=True,
            context={'request': request}
        )

        return Response(serializer.data)

    # ================================================================
    # ✅ Récupérer les stats de factures d'un client (pour dashboard)
    # ================================================================
    @action(detail=False, methods=['get'], url_path='client-stats')
    def client_stats(self, request):
        """
        Statistiques de facturation pour un client.
        GET /factures/client-stats/?client_id=1
        """
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response(
                {"error": "Le paramètre client_id est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        factures = Facture.objects.filter(client_id=client_id)

        total_factures = factures.count()
        total_montant = factures.aggregate(
            total=Sum('total'))['total'] or Decimal('0')
        total_paye = factures.aggregate(
            total=Sum('amount_paid'))['total'] or Decimal('0')
        total_impaye = total_montant - total_paye

        par_statut = {}
        for status_choice in Facture.STATUS_CHOICES:
            status_code = status_choice[0]
            count = factures.filter(status=status_code).count()
            if count > 0:
                par_statut[status_code] = count

        return Response({
            'total_factures': total_factures,
            'total_montant': total_montant,
            'total_paye': total_paye,
            'total_impaye': total_impaye,
            'par_statut': par_statut,
        })

    # ================================================================
    # ENREGISTRER UN PAIEMENT SUR UNE FACTURE
    # ================================================================
    @action(detail=True, methods=['post'])
    def register_payment(self, request, pk=None):
        from decimal import Decimal
        from django.db import transaction
        from django.db.models import Sum

        facture = self.get_object()
        logger.info(f"🔔 register_payment - facture {facture.invoice_number}")

        amount = request.data.get('amount')
        method = request.data.get('method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount > facture.remaining_amount:
            return Response(
                {"error": f"Le montant dépasse le solde restant ({facture.remaining_amount:,.0f} FCFA)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # 1. Création du paiement
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement sur la facture {facture.invoice_number}",
                received_by=request.user
            )
            logger.info(f"✅ Paiement créé : ID {paiement.id}")

            # 2. Mise à jour de la facture
            total_paid = facture.paiements.aggregate(total=Sum('amount'))[
                'total'] or Decimal('0')
            facture.amount_paid = total_paid
            if facture.amount_paid >= facture.total:
                facture.status = 'paid'
            elif facture.amount_paid > 0:
                facture.status = 'partial'
            facture.save()

            # 3. Mise à jour de la vente associée
            sale = facture.sale
            if sale:
                total_paid_sale = Decimal('0')
                for inv in sale.invoices.all():
                    total_paid_sale += inv.amount_paid
                sale.amount_paid = total_paid_sale
                sale.amount_due = sale.total - sale.amount_paid
                if sale.amount_due <= 0:
                    sale.payment_status = 'paid'
                elif sale.amount_paid > 0:
                    sale.payment_status = 'partial'
                else:
                    sale.payment_status = 'pending'
                sale.save()
                logger.info(
                    f"   Vente associée : {sale.invoice_number}, warehouse={sale.warehouse}")

            # 4. ✨ CRÉATION MANUELLE DU MOUVEMENT DE TRÉSORERIE
            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user)

            if mouvement:
                logger.info(f"✅ Mouvement créé : {mouvement.reference}")
            else:
                logger.warning(
                    "⚠️ Aucun mouvement créé pour ce paiement (vérifiez les logs)")

        # 5. Réponse
        serializer = PaiementSerializer(paiement, context={'request': request})
        return Response({
            'paiement': serializer.data,
            'facture': FactureSerializer(facture, context={'request': request}).data,
            'remaining_amount': facture.remaining_amount,
            'mouvement_cree': mouvement is not None,
            'mouvement_reference': mouvement.reference if mouvement else None
        }, status=status.HTTP_201_CREATED)

    # ================================================================
    # MARQUER COMME PAYÉE (avec montant optionnel)
    # ================================================================
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        from decimal import Decimal
        from django.db import transaction
        from django.db.models import Sum

        facture = self.get_object()
        logger.info(f"🔔 mark_paid - facture {facture.invoice_number}")

        amount = request.data.get('amount', 0)
        method = request.data.get('method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount > facture.remaining_amount:
            return Response(
                {"error": f"Le montant dépasse le solde restant ({facture.remaining_amount:,.0f} FCFA)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement sur la facture {facture.invoice_number}",
                received_by=request.user
            )
            logger.info(f"✅ Paiement créé : ID {paiement.id}")

            total_paid = facture.paiements.aggregate(total=Sum('amount'))[
                'total'] or Decimal('0')
            facture.amount_paid = total_paid
            if facture.amount_paid >= facture.total:
                facture.status = 'paid'
            elif facture.amount_paid > 0:
                facture.status = 'partial'
            facture.save()

            sale = facture.sale
            if sale:
                total_paid_sale = Decimal('0')
                for inv in sale.invoices.all():
                    total_paid_sale += inv.amount_paid
                sale.amount_paid = total_paid_sale
                sale.amount_due = sale.total - sale.amount_paid
                if sale.amount_due <= 0:
                    sale.payment_status = 'paid'
                elif sale.amount_paid > 0:
                    sale.payment_status = 'partial'
                else:
                    sale.payment_status = 'pending'
                sale.save()

            # ✨ Création manuelle du mouvement
            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user)

        serializer = PaiementSerializer(paiement, context={'request': request})
        return Response({
            'paiement': serializer.data,
            'facture_status': facture.status,
            'remaining_amount': facture.remaining_amount,
            'mouvement_cree': mouvement is not None,
            'mouvement_reference': mouvement.reference if mouvement else None
        }, status=status.HTTP_201_CREATED)

    # ================================================================
    # ENVOYER UNE FACTURE
    # ================================================================
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        facture = self.get_object()
        if facture.status != 'draft':
            return Response(
                {"error": "Seules les factures en brouillon peuvent être envoyées"},
                status=status.HTTP_400_BAD_REQUEST
            )
        facture.status = 'sent'
        facture.save()
        facture.generate_qr_code()
        facture.save()
        return Response({
            'status': facture.status,
            'message': 'Facture envoyée avec succès'
        })

    # ================================================================
    # ANNULER UNE FACTURE
    # ================================================================
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        facture = self.get_object()
        if facture.status in ['paid']:
            return Response(
                {"error": "Les factures payées ne peuvent pas être annulées"},
                status=status.HTTP_400_BAD_REQUEST
            )
        facture.status = 'cancelled'
        facture.save()
        return Response({
            'status': facture.status,
            'message': 'Facture annulée avec succès'
        })

    # ================================================================
    # GÉNÉRER UNE FACTURE DEPUIS UNE VENTE
    # ================================================================
    @action(detail=True, methods=['post'])
    def generate_invoice(self, request, pk=None):
        from django.db import transaction
        sale_id = request.data.get('sale_id')
        due_date = request.data.get('due_date')

        if not sale_id:
            return Response(
                {"error": "L'ID de la vente est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            sale = Vente.objects.get(id=sale_id)
        except Vente.DoesNotExist:
            return Response(
                {"error": "Vente non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )

        if Facture.objects.filter(sale=sale).exists():
            return Response(
                {"error": "Une facture existe déjà pour cette vente"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if due_date:
            try:
                due_date = date.fromisoformat(due_date)
            except ValueError:
                return Response(
                    {"error": "Format de date invalide. Utilisez YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            due_date = date.today() + timedelta(days=30)

        with transaction.atomic():
            last_facture = Facture.objects.order_by('-id').first()
            if last_facture and last_facture.invoice_number:
                try:
                    num = int(last_facture.invoice_number.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            invoice_number = f"FAC-{date.today().year}-{num:04d}"

            facture = Facture.objects.create(
                invoice_number=invoice_number,
                sale=sale,
                client=sale.client,
                due_date=due_date,
                subtotal=sale.subtotal,
                tax_amount=sale.tax_amount,
                total=sale.total,
                status='sent'
            )

            facture.generate_qr_code()
            facture.save()

        return Response({
            'facture': FactureSerializer(facture, context={'request': request}).data,
            'message': 'Facture générée avec succès'
        }, status=status.HTTP_201_CREATED)

    # ================================================================
    # GÉNÉRER LE QR CODE
    # ================================================================
    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        facture = self.get_object()
        if not facture.qr_code:
            facture.generate_qr_code()
            facture.save()
        if facture.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(facture.qr_code.url),
                'qr_code_data': facture.qr_code_data
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # ================================================================
    # LISTER LES PAIEMENTS D'UNE FACTURE
    # ================================================================
    @action(detail=True, methods=['get'])
    def paiements(self, request, pk=None):
        facture = self.get_object()
        paiements = facture.paiements.all()
        serializer = PaiementSerializer(
            paiements, many=True, context={'request': request})
        return Response(serializer.data)

# ============================================================
# PAIEMENT VIEWSET
# ============================================================


class PaiementViewSet(viewsets.ModelViewSet):
    queryset = Paiement.objects.all()
    serializer_class = PaiementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = (
            Paiement.objects
            .select_related(
                'facture',
                'facture__client',
                'facture__sale',
                'received_by',
                'caisse_destination',
                'compte_destination',
            )
            .order_by('-payment_date')
        )
        facture_id = self.request.query_params.get('facture')
        if facture_id:
            queryset = queryset.filter(facture_id=facture_id)

        method = self.request.query_params.get('method')
        if method and method != 'all':
            queryset = queryset.filter(method=method)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(payment_date__date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(payment_date__date__lte=date_to)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(facture__invoice_number__icontains=search) |
                Q(facture__client__name__icontains=search) |
                Q(reference__icontains=search)
            )
        return queryset

# ============================================================
# AVOIR VIEWSET
# ============================================================


# ============================================================
# AVOIR VIEWSET - CORRIGÉ AVEC RESTAURATION DU STOCK
# ============================================================
# apps/ventes_clients/views.py (extrait — AvoirViewSet complet)

class AvoirViewSet(viewsets.ModelViewSet):
    queryset = Avoir.objects.prefetch_related(
        "lignes", "lignes__product", "client", "sale"
    ).all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return AvoirCreateSerializer
        return AvoirSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()

        client = self.request.query_params.get("client")
        if client:
            queryset = queryset.filter(client_id=client)

        sale = self.request.query_params.get("sale")
        if sale:
            queryset = queryset.filter(sale_id=sale)

        avoir_type = self.request.query_params.get("type")
        if avoir_type:
            queryset = queryset.filter(type=avoir_type)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(avoir_number__icontains=search)
                | Q(client__name__icontains=search)
                | Q(reason__icontains=search)
            )

        return queryset

    # ============================================================
    # CRÉATION AVEC RESTAURATION DU STOCK
    # ============================================================
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Lire restore_stock (bool ou string)
        restore_stock = request.data.get("restore_stock", False)
        if isinstance(restore_stock, str):
            restore_stock = restore_stock.lower() == "true"

        try:
            with transaction.atomic():
                # 1. CRÉER L'AVOIR + SES LIGNES
                avoir = serializer.save(created_by=request.user)

                logger.info(
                    f"✅ Avoir créé : {avoir.avoir_number} "
                    f"({avoir.type}) - {avoir.amount:,.0f} FCFA - "
                    f"{avoir.lignes.count()} ligne(s)"
                )

                # 2. RESTAURER LE STOCK (PRODUITS RETOURNÉS UNIQUEMENT)
                stock_restored = False
                stock_details = []

                should_restore = (
                    restore_stock
                    and avoir.sale is not None
                    and avoir.type in ["refund", "return"]
                    and avoir.lignes.exists()
                )

                if should_restore:
                    result = avoir.restore_partial_stock(user=request.user)
                    stock_restored = result["success"]
                    stock_details = result["details"]

                    if stock_restored:
                        logger.info(f"📦 {result['message']}")
                    else:
                        logger.warning(f"⚠️ {result['message']}")

                # 3. MOUVEMENT DE TRÉSORERIE (DÉCAISSEMENT)
                mouvement_tresorerie = None
                try:
                    from tresorerie.models import MouvementTresorerie, Caisse

                    if avoir.sale and avoir.sale.warehouse:
                        caisse = Caisse.objects.filter(
                            warehouse=avoir.sale.warehouse,
                            is_default=True,
                        ).first()

                        if not caisse:
                            caisse = Caisse.objects.filter(
                                warehouse=avoir.sale.warehouse,
                                is_active=True,
                            ).first()

                        if caisse:
                            existing = MouvementTresorerie.objects.filter(
                                source_type="avoir",
                                source_id=avoir.id,
                            ).first()

                            if not existing:
                                mouvement_tresorerie = MouvementTresorerie.objects.create(
                                    type_mouvement="decaissement",
                                    warehouse=avoir.sale.warehouse,
                                    source_type="avoir",
                                    source_id=avoir.id,
                                    source_reference=avoir.avoir_number,
                                    montant=avoir.amount,
                                    mode_paiement="especes",
                                    caisse=caisse,
                                    date_mouvement=timezone.now(),
                                    date_valeur=timezone.now().date(),
                                    status="effectue",
                                    libelle=f"Avoir {avoir.avoir_number} - {avoir.reason[:100]}",
                                    created_by=request.user,
                                )

                                # Diminuer la caisse
                                caisse.solde_actuel -= avoir.amount
                                caisse.save(update_fields=[
                                            "solde_actuel", "updated_at"])

                                logger.info(
                                    f"💰 Caisse {caisse.nom} : -{avoir.amount:,.0f} FCFA"
                                )
                            else:
                                mouvement_tresorerie = existing
                except ImportError:
                    logger.warning("Module tresorerie non disponible")
                except Exception as e:
                    logger.error(f"Erreur trésorerie : {e}")

                # 4. RÉPONSE
                return Response({
                    "status": "success",
                    "message": "Avoir créé avec succès",
                    "avoir": AvoirSerializer(avoir, context={"request": request}).data,
                    "stock_restored": stock_restored,
                    "stock_details": stock_details,
                    "mouvement_tresorerie_cree": mouvement_tresorerie is not None,
                    "mouvement_reference": (
                        mouvement_tresorerie.reference if mouvement_tresorerie else None
                    ),
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Erreur création avoir")
            return Response(
                {"error": f"Erreur : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ============================================================
    # ACTION : RESTAURER LE STOCK MANUELLEMENT
    # ============================================================
    @action(detail=True, methods=["post"], url_path="restore-stock")
    def restore_stock_action(self, request, pk=None):
        avoir = self.get_object()

        if avoir.restore_stock:
            return Response(
                {"error": "Stock déjà restauré"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not avoir.can_restore_stock:
            return Response(
                {"error": "Restauration impossible"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            result = avoir.restore_partial_stock(user=request.user)

        if not result["success"]:
            return Response(
                {"error": result["message"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "status": "success",
            "message": result["message"],
            "stock_details": result["details"],
        })


class TaxeViewSet(viewsets.ModelViewSet):
    queryset = Taxe.objects.all()
    serializer_class = TaxeSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]


# ============================================================
# REMISE VIEWSET
# ============================================================
class RemiseViewSet(viewsets.ModelViewSet):
    queryset = Remise.objects.all()
    serializer_class = RemiseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset


# ============================================================
# DASHBOARD STATS VIEWSET
# ============================================================
class SalesDashboardStatsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        today = date.today()
        start_of_month = today.replace(day=1)
        start_of_week = today - timedelta(days=today.weekday())

        total_sales = Vente.objects.count()
        sales_today = Vente.objects.filter(sale_date__date=today).count()
        sales_this_month = Vente.objects.filter(
            sale_date__date__gte=start_of_month).count()
        sales_this_week = Vente.objects.filter(
            sale_date__date__gte=start_of_week).count()

        total_amount = Vente.objects.aggregate(
            total=Sum('total'))['total'] or 0
        amount_today = Vente.objects.filter(sale_date__date=today).aggregate(
            total=Sum('total'))['total'] or 0
        amount_this_month = Vente.objects.filter(
            sale_date__date__gte=start_of_month).aggregate(total=Sum('total'))['total'] or 0

        pending_payments = Vente.objects.filter(
            payment_status__in=['pending', 'partial']).count()
        pending_amount = Vente.objects.filter(payment_status__in=[
                                              'pending', 'partial']).aggregate(total=Sum('amount_due'))['total'] or 0

        total_clients = Client.objects.filter(statut='actif').count()

        pending_invoices = Facture.objects.filter(
            status__in=['draft', 'sent', 'partial']).count()
        overdue_invoices = Facture.objects.filter(status='overdue').count()

        total_devis = Devis.objects.count()
        devis_en_attente = Devis.objects.filter(status='sent').count()
        devis_acceptes = Devis.objects.filter(status='accepted').count()
        devis_expires = Devis.objects.filter(status='expired').count()
        devis_convertis = Devis.objects.filter(status='converted').count()

        return Response({
            'sales': {
                'total': total_sales,
                'today': sales_today,
                'this_week': sales_this_week,
                'this_month': sales_this_month
            },
            'amounts': {
                'total': total_amount,
                'today': amount_today,
                'this_month': amount_this_month
            },
            'payments': {
                'pending': pending_payments,
                'pending_amount': pending_amount
            },
            'clients': {
                'total': total_clients
            },
            'invoices': {
                'pending': pending_invoices,
                'overdue': overdue_invoices
            },
            'devis': {
                'total': total_devis,
                'en_attente': devis_en_attente,
                'acceptes': devis_acceptes,
                'expires': devis_expires,
                'convertis': devis_convertis
            }
        })


# ============================================================
# WALLET VIEWSET - COMPLET AVEC NOUVEAUX ENDPOINTS
# ============================================================

# apps/ventes_clients/views.py - PARTIE WALLET CORRIGÉE

# ============================================================
# WALLET VIEWSET - COMPLET CORRIGÉ (SANS request.user.client)
# ============================================================
# apps/ventes_clients/views.py
# ============================================================
# WALLET VIEWSET - COMPLET CORRIGÉ
# ============================================================


logger = logging.getLogger(__name__)

# apps/ventes_clients/views.py
# ============================================================
# WALLET VIEWSET - COMPLET ET CORRIGÉ
# ============================================================


logger = logging.getLogger(__name__)

# apps/ventes_clients/views.py - WalletViewSet corrigé


class WalletViewSet(viewsets.ViewSet):
    """
    API pour gérer le porte-monnaie client
    Toutes les actions requièrent un client_id explicite
    """
    permission_classes = [permissions.IsAuthenticated]

    # ✅ Helper pour vérifier si l'utilisateur est admin
    def _is_admin(self, user):
        """Vérifie si l'utilisateur a le rôle admin"""
        return user.role == 'admin' or user.is_staff or user.is_superuser

    # ============================================================
    # 1. LISTE DES WALLETS (ADMIN)
    # ============================================================
    @action(detail=False, methods=['get'], url_path='list')
    def list_wallets(self, request):
        """
        Liste tous les wallets avec leurs clients (admin uniquement)
        GET /wallet/list/
        """
        # ✅ CORRECTION : Vérifier le rôle admin
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée. Accès réservé aux administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallets = ClientWallet.objects.select_related(
                'client'
            ).all().order_by('-created_at')

            total = wallets.count()
            total_balance = wallets.aggregate(
                total=Sum('balance')
            )['total'] or Decimal('0')
            active_count = wallets.filter(is_active=True).count()
            inactive_count = wallets.filter(is_active=False).count()

            # Sérialiser manuellement avec les infos client
            results = []
            for wallet in wallets:
                results.append({
                    'id': wallet.id,
                    'client': wallet.client.id,
                    'client_name': wallet.client.name,
                    'client_code': wallet.client.code,
                    'client_phone': wallet.client.phone,
                    'client_type': wallet.client.type,
                    'client_statut': wallet.client.statut,
                    'balance': wallet.balance,
                    'balance_display': f"{wallet.balance:,.0f} FCFA",
                    'total_deposits': wallet.total_deposits,
                    'total_used': wallet.total_used,
                    'is_active': wallet.is_active,
                    'created_at': wallet.created_at,
                    'updated_at': wallet.updated_at
                })

            return Response({
                'count': total,
                'total_balance': total_balance,
                'total_balance_display': f"{total_balance:,.0f} FCFA",
                'active_count': active_count,
                'inactive_count': inactive_count,
                'results': results
            })
        except Exception as e:
            logger.error(f"❌ Erreur chargement wallets: {e}")
            return Response(
                {"error": f"Erreur lors du chargement des wallets: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 2. RÉCUPÉRER LE WALLET D'UN CLIENT SPÉCIFIQUE
    # ============================================================
    @action(detail=True, methods=['get'], url_path='client-wallet')
    def get_client_wallet(self, request, pk=None):
        """
        Récupère le wallet d'un client spécifique par son ID
        GET /wallet/{client_id}/client-wallet/
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        try:
            client = Client.objects.get(id=pk)
            wallet, created = ClientWallet.objects.get_or_create(client=client)

            return Response({
                'id': wallet.id,
                'client': wallet.client.id,
                'client_name': wallet.client.name,
                'client_code': wallet.client.code,
                'client_phone': wallet.client.phone,
                'client_type': wallet.client.type,
                'client_statut': wallet.client.statut,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'total_deposits': wallet.total_deposits,
                'total_used': wallet.total_used,
                'is_active': wallet.is_active,
                'created_at': wallet.created_at,
                'updated_at': wallet.updated_at
            })
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur récupération wallet: {e}")
            return Response(
                {"error": f"Erreur lors de la récupération: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 3. CRÉATION DU WALLET POUR UN CLIENT
    # ============================================================
    @action(detail=False, methods=['post'], url_path='create-wallet')
    def create_wallet(self, request):
        """
        Crée un porte-monnaie pour un client spécifique
        URL: POST /wallet/create-wallet/
        Body: { "client_id": 1, "initial_balance": 0 }
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        client_id = request.data.get('client_id')
        initial_balance = request.data.get('initial_balance', 0)

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            initial_balance = Decimal(str(initial_balance))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le solde initial doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if initial_balance < 0:
            return Response(
                {"error": "Le solde initial ne peut pas être négatif"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client = Client.objects.get(id=client_id)

            # Vérifier si le client a déjà un wallet
            if hasattr(client, 'wallet'):
                wallet = client.wallet
                return Response(
                    {
                        "error": "Ce client a déjà un porte-monnaie",
                        "wallet": {
                            'id': wallet.id,
                            'balance': wallet.balance,
                            'balance_display': f"{wallet.balance:,.0f} FCFA",
                            'is_active': wallet.is_active
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                wallet = ClientWallet.objects.create(
                    client=client,
                    balance=initial_balance,
                    total_deposits=initial_balance,
                    total_used=0,
                    is_active=True
                )

                if initial_balance > 0:
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        type='credit',
                        amount=initial_balance,
                        source='adjustment',
                        reference=f"INITIAL-{wallet.id}",
                        notes=f"Solde initial de {initial_balance:,.0f} FCFA",
                        balance_after=initial_balance,
                        created_by=request.user
                    )

                return Response({
                    'status': 'success',
                    'message': f'Porte-monnaie créé avec succès pour {client.name}',
                    'wallet_id': wallet.id,
                    'balance': wallet.balance,
                    'balance_display': f"{wallet.balance:,.0f} FCFA",
                    'is_active': wallet.is_active
                }, status=status.HTTP_201_CREATED)

        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur création wallet: {e}")
            return Response(
                {"error": f"Erreur lors de la création du wallet: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 4. DÉPÔT DANS LE WALLET
    # ============================================================
    @action(detail=False, methods=['post'])
    def deposit(self, request):
        """
        Déposer de l'argent dans le wallet d'un client
        POST /wallet/deposit/
        Body: { "client_id": 1, "amount": 1000, "payment_method": "cash", "notes": "..." }
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        client_id = request.data.get('client_id')
        amount = request.data.get('amount')
        notes = request.data.get('notes', '')
        payment_method = request.data.get('payment_method', 'cash')

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client = Client.objects.get(id=client_id)
            wallet, created = ClientWallet.objects.get_or_create(client=client)
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            with transaction.atomic():
                new_balance = wallet.credit(
                    amount=amount,
                    source='deposit',
                    reference=f"DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes or f"Dépôt de {amount:,.0f} FCFA en {payment_method}",
                    created_by=request.user
                )

                # Créer un mouvement de trésorerie
                try:
                    from tresorerie.models import MouvementTresorerie, Caisse

                    warehouse = None
                    sale = client.sales.first()
                    if sale and sale.warehouse:
                        warehouse = sale.warehouse

                    caisse = None
                    if warehouse:
                        caisse = Caisse.objects.filter(
                            warehouse=warehouse,
                            is_default=True
                        ).first()
                        if not caisse:
                            caisse = Caisse.objects.filter(
                                warehouse=warehouse,
                                is_active=True
                            ).first()

                    if caisse:
                        MouvementTresorerie.objects.create(
                            type_mouvement='encaissement',
                            warehouse=caisse.warehouse,
                            source_type='wallet_deposit',
                            source_id=wallet.id,
                            source_reference=f"DEP-{wallet.id}",
                            montant=amount,
                            mode_paiement=payment_method,
                            caisse=caisse,
                            date_mouvement=timezone.now(),
                            date_valeur=timezone.now().date(),
                            status='effectue',
                            libelle=f"Dépôt wallet - {client.name}",
                            created_by=request.user
                        )

                        caisse.solde_actuel += amount
                        caisse.save(update_fields=[
                                    'solde_actuel', 'updated_at'])
                        logger.info(
                            f"💰 Caisse {caisse.nom} augmentée de {amount:,.0f} FCFA")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erreur création mouvement trésorerie: {e}")

                return Response({
                    'status': 'success',
                    'message': f'Dépôt de {amount:,.0f} FCFA effectué avec succès',
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'wallet_id': wallet.id,
                    'client_id': client.id,
                    'client_name': client.name
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Erreur lors du dépôt: {e}")
            return Response(
                {"error": f"Erreur lors du dépôt: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 5. PAYER UNE FACTURE SPÉCIFIQUE AVEC LE WALLET
    # ============================================================
    @action(detail=False, methods=['post'], url_path='pay-invoice')
    def pay_invoice(self, request):
        """
        Payer une facture spécifique avec le wallet
        POST /wallet/pay-invoice/
        Body: { "facture_id": 1, "amount": 1000, "notes": "..." }
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        facture_id = request.data.get('facture_id')
        amount = request.data.get('amount')
        notes = request.data.get('notes', '')

        if not facture_id:
            return Response(
                {"error": "L'ID de la facture est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                # 1. Récupérer la facture
                facture = Facture.objects.select_related(
                    'sale', 'client'
                ).get(id=facture_id)

                # 2. Vérifier que la facture n'est pas déjà payée
                if facture.status == 'paid':
                    return Response(
                        {"error": "Cette facture est déjà entièrement payée"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 3. Vérifier le montant restant
                remaining = facture.remaining_amount
                if amount > remaining:
                    return Response({
                        "error": f"Le montant dépasse le solde restant ({remaining:,.0f} FCFA)"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 4. Récupérer le client et son wallet
                client = facture.client
                if not client:
                    return Response(
                        {"error": "Cette facture n'a pas de client associé"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                wallet, created = ClientWallet.objects.get_or_create(
                    client=client)

                # 5. Vérifier si le wallet est actif
                if not wallet.is_active:
                    return Response(
                        {"error": "Le porte-monnaie est désactivé"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 6. Vérifier le solde du wallet
                if wallet.balance < amount:
                    return Response({
                        "error": f"Solde insuffisant. Disponible : {wallet.balance:,.0f} FCFA"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 7. DÉBITER LE WALLET
                new_balance = wallet.debit(
                    amount=amount,
                    source='payment',
                    reference=facture.invoice_number,
                    notes=notes or f"Paiement facture {facture.invoice_number}",
                    created_by=request.user
                )

                # 8. CRÉER LE PAIEMENT - ✅ AVEC MÉTHODE 'WALLET'
                paiement = Paiement.objects.create(
                    facture=facture,
                    amount=amount,
                    method='wallet',
                    reference=f"WALLET-{facture.invoice_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=f"Paiement via wallet - {notes or ''}",
                    received_by=request.user
                )

                logger.info(f"✅ Paiement wallet créé : ID {paiement.id}")

                # 9. METTRE À JOUR LA FACTURE
                total_paid = facture.paiements.aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0')
                facture.amount_paid = total_paid

                if facture.amount_paid >= facture.total:
                    facture.status = 'paid'
                else:
                    facture.status = 'partial'
                facture.save(update_fields=[
                             'amount_paid', 'status', 'updated_at'])

                # 10. METTRE À JOUR LA VENTE ASSOCIÉE
                sale = facture.sale
                if sale:
                    total_paid_sale = Decimal('0')
                    for inv in sale.invoices.all():
                        total_paid_sale += inv.amount_paid
                    sale.amount_paid = total_paid_sale
                    sale.amount_due = sale.total - sale.amount_paid

                    if sale.amount_due <= 0:
                        sale.payment_status = 'paid'
                        if sale.status != 'paid':
                            sale.status = 'paid'
                    elif sale.amount_paid > 0:
                        sale.payment_status = 'partial'
                    else:
                        sale.payment_status = 'pending'
                    sale.save(update_fields=[
                        'amount_paid', 'amount_due',
                        'payment_status', 'status', 'updated_at'
                    ])

                # 11. RÉPONSE
                return Response({
                    'status': 'success',
                    'message': f'Paiement de {amount:,.0f} FCFA effectué avec succès',
                    'wallet_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'paiement_id': paiement.id,
                    'facture_remaining': facture.remaining_amount,
                    'facture_status': facture.status,
                    'facture_number': facture.invoice_number,
                    'sale_status': sale.status if sale else None,
                    'payment_status': sale.payment_status if sale else None
                }, status=status.HTTP_201_CREATED)

        except Facture.DoesNotExist:
            return Response(
                {"error": f"Facture avec l'ID {facture_id} non trouvée"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Erreur lors du paiement de facture: {e}")
            import traceback
            traceback.print_exc()
            return Response(
                {"error": f"Erreur lors du paiement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 6. PAYER TOUTES LES FACTURES IMPAYÉES D'UN CLIENT
    # ============================================================
    @action(detail=False, methods=['post'], url_path='pay-all-unpaid')
    def pay_all_unpaid(self, request):
        """
        Payer toutes les factures impayées d'un client avec le wallet
        POST /wallet/pay-all-unpaid/
        Body: { "client_id": 1, "notes": "..." }
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        client_id = request.data.get('client_id')
        notes = request.data.get(
            'notes', 'Paiement de toutes les factures impayées')

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

        # 1. Récupérer toutes les factures impayées du client
        unpaid_statuses = ['sent', 'overdue', 'partial']
        factures = Facture.objects.filter(
            client=client,
            status__in=unpaid_statuses
        ).order_by('due_date')

        factures_impayees = [f for f in factures if f.remaining_amount > 0]

        if not factures_impayees:
            return Response({
                'status': 'success',
                'message': 'Aucune facture impayée à payer',
                'paid_count': 0,
                'total_amount': 0
            })

        total_amount = sum(f.remaining_amount for f in factures_impayees)

        wallet, created = ClientWallet.objects.get_or_create(client=client)

        if not wallet.is_active:
            return Response(
                {"error": "Le porte-monnaie est désactivé"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if wallet.balance < total_amount:
            return Response({
                "error": f"Solde insuffisant. Total des factures : {total_amount:,.0f} FCFA, Solde disponible : {wallet.balance:,.0f} FCFA"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                paiements_crees = []
                total_paye = Decimal('0')
                factures_payees = []

                for facture in factures_impayees:
                    amount = facture.remaining_amount

                    # Débiter le wallet
                    wallet.balance -= amount
                    wallet.total_used += amount

                    # Créer la transaction wallet
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        type='debit',
                        amount=amount,
                        source='payment',
                        reference=facture.invoice_number,
                        notes=f"Paiement facture {facture.invoice_number} - {notes}",
                        balance_after=wallet.balance,
                        created_by=request.user
                    )

                    # Créer le paiement - ✅ AVEC MÉTHODE 'WALLET'
                    paiement = Paiement.objects.create(
                        facture=facture,
                        amount=amount,
                        method='wallet',
                        reference=f"WALLET-{facture.invoice_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                        notes=f"Paiement via wallet - {notes}",
                        received_by=request.user
                    )
                    paiements_crees.append(paiement.id)

                    # Mettre à jour la facture
                    total_paid = facture.paiements.aggregate(
                        total=Sum('amount')
                    )['total'] or Decimal('0')
                    facture.amount_paid = total_paid
                    facture.status = 'paid' if total_paid >= facture.total else 'partial'
                    facture.save(update_fields=[
                                 'amount_paid', 'status', 'updated_at'])

                    # Mettre à jour la vente
                    sale = facture.sale
                    if sale:
                        total_paid_sale = Decimal('0')
                        for inv in sale.invoices.all():
                            total_paid_sale += inv.amount_paid
                        sale.amount_paid = total_paid_sale
                        sale.amount_due = sale.total - sale.amount_paid
                        if sale.amount_due <= 0:
                            sale.payment_status = 'paid'
                            if sale.status != 'paid':
                                sale.status = 'paid'
                        elif sale.amount_paid > 0:
                            sale.payment_status = 'partial'
                        else:
                            sale.payment_status = 'pending'
                        sale.save(update_fields=[
                            'amount_paid', 'amount_due',
                            'payment_status', 'status', 'updated_at'
                        ])

                    total_paye += amount
                    factures_payees.append(facture.invoice_number)

                # Sauvegarder le wallet
                wallet.save(update_fields=[
                            'balance', 'total_used', 'updated_at'])

                return Response({
                    'status': 'success',
                    'message': f'Paiement de {total_paye:,.0f} FCFA effectué pour {len(paiements_crees)} factures',
                    'paid_count': len(paiements_crees),
                    'total_amount': total_paye,
                    'new_balance': wallet.balance,
                    'balance_display': f"{wallet.balance:,.0f} FCFA",
                    'payment_ids': paiements_crees,
                    'factures_payees': factures_payees
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Erreur lors du paiement groupé: {e}")
            import traceback
            traceback.print_exc()
            return Response(
                {"error": f"Erreur lors du paiement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 7. HISTORIQUE DES TRANSACTIONS D'UN CLIENT
    # ============================================================
    @action(detail=True, methods=['get'], url_path='transactions')
    def client_transactions(self, request, pk=None):
        """
        Historique des transactions du wallet d'un client
        GET /wallet/{client_id}/transactions/
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        try:
            client = Client.objects.get(id=pk)
            wallet, created = ClientWallet.objects.get_or_create(client=client)
            transactions = wallet.transactions.all().order_by(
                '-created_at')[:50]

            # Sérialiser manuellement
            transactions_data = []
            for t in transactions:
                transactions_data.append({
                    'id': t.id,
                    'type': t.type,
                    'type_display': t.get_type_display(),
                    'amount': t.amount,
                    'amount_display': f"{t.amount:,.0f} FCFA",
                    'source': t.source,
                    'source_display': t.get_source_display(),
                    'reference': t.reference,
                    'notes': t.notes,
                    'balance_after': t.balance_after,
                    'created_at': t.created_at,
                    'created_by': t.created_by.id if t.created_by else None,
                    'created_by_name': t.created_by.get_full_name() if t.created_by else None
                })

            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'transactions': transactions_data
            })
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur récupération transactions: {e}")
            return Response(
                {"error": f"Erreur lors de la récupération: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 8. ADMIN : STATISTIQUES GLOBALES
    # ============================================================
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Admin : Statistiques globales des wallets
        GET /wallet/stats/
        """
        # ✅ CORRECTION : Vérifier le rôle admin
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            total_wallets = ClientWallet.objects.count()
            total_balance = ClientWallet.objects.aggregate(
                total=Sum('balance'))['total'] or Decimal('0')
            active_wallets = ClientWallet.objects.filter(
                is_active=True).count()
            inactive_wallets = ClientWallet.objects.filter(
                is_active=False).count()

            avg_balance = total_balance / \
                total_wallets if total_wallets > 0 else Decimal('0')

            return Response({
                'total_wallets': total_wallets,
                'total_balance': total_balance,
                'total_balance_display': f"{total_balance:,.0f} FCFA",
                'active_wallets': active_wallets,
                'inactive_wallets': inactive_wallets,
                'avg_balance': avg_balance,
                'avg_balance_display': f"{avg_balance:,.0f} FCFA"
            })
        except Exception as e:
            logger.error(f"❌ Erreur calcul statistiques: {e}")
            return Response(
                {"error": f"Erreur lors du calcul des statistiques: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 9. ADMIN : AJUSTER LE SOLDE D'UN WALLET
    # ============================================================
    @action(detail=True, methods=['post'], url_path='adjust-balance')
    def adjust_balance(self, request, pk=None):
        """
        Admin : Ajuster le solde d'un wallet (ajout ou retrait)
        POST /wallet/{wallet_id}/adjust-balance/
        Body: { "amount": 1000, "type": "credit"|"debit", "notes": "..." }
        """
        # ✅ CORRECTION : Vérifier le rôle admin
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée. Réservé aux administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallet = ClientWallet.objects.get(id=pk)

            amount = request.data.get('amount')
            adjustment_type = request.data.get('type', 'credit')
            notes = request.data.get('notes', 'Ajustement manuel')

            try:
                amount = Decimal(str(amount))
            except (TypeError, ValueError):
                return Response(
                    {"error": "Le montant doit être un nombre valide"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if amount <= 0:
                return Response(
                    {"error": "Le montant doit être supérieur à 0"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                if adjustment_type == 'credit':
                    new_balance = wallet.credit(
                        amount=amount,
                        source='adjustment',
                        reference=f"ADJ-{wallet.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                        notes=notes or f"Ajustement positif de {amount:,.0f} FCFA",
                        created_by=request.user
                    )
                    message = f"Ajout de {amount:,.0f} FCFA effectué"
                elif adjustment_type == 'debit':
                    if amount > wallet.balance:
                        return Response(
                            {"error": f"Solde insuffisant. Disponible : {wallet.balance:,.0f} FCFA"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    new_balance = wallet.debit(
                        amount=amount,
                        source='adjustment',
                        reference=f"ADJ-{wallet.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                        notes=notes or f"Ajustement négatif de {amount:,.0f} FCFA",
                        created_by=request.user
                    )
                    message = f"Retrait de {amount:,.0f} FCFA effectué"
                else:
                    return Response(
                        {"error": "Le type doit être 'credit' ou 'debit'"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                return Response({
                    'status': 'success',
                    'message': message,
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'wallet_id': wallet.id,
                    'client_name': wallet.client.name
                })

        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Porte-monnaie avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'ajustement: {e}")
            return Response(
                {"error": f"Erreur lors de l'ajustement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 10. ADMIN : ACTIVER/DÉSACTIVER UN WALLET
    # ============================================================
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """
        Admin : Activer/désactiver un wallet
        POST /wallet/{wallet_id}/toggle-status/
        Body: { "is_active": true/false }
        """
        # ✅ CORRECTION : Vérifier le rôle admin
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée. Réservé aux administrateurs."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallet = ClientWallet.objects.get(id=pk)
            is_active = request.data.get('is_active')

            if is_active is None:
                return Response(
                    {"error": "Le champ 'is_active' est requis (true ou false)"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Convertir en booléen si nécessaire
            if isinstance(is_active, str):
                is_active = is_active.lower() == 'true'

            wallet.is_active = is_active
            wallet.save(update_fields=['is_active', 'updated_at'])

            return Response({
                'status': 'success',
                'message': f'Wallet {"activé" if is_active else "désactivé"} avec succès',
                'wallet_id': wallet.id,
                'client_name': wallet.client.name,
                'is_active': wallet.is_active
            })
        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Porte-monnaie avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur changement statut: {e}")
            return Response(
                {"error": f"Erreur lors du changement de statut: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 11. VÉRIFIER SI UN CLIENT A UN WALLET
    # ============================================================
    @action(detail=True, methods=['get'], url_path='has-wallet')
    def has_wallet(self, request, pk=None):
        """
        Vérifie si un client a un wallet
        GET /wallet/{client_id}/has-wallet/
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        try:
            client = Client.objects.get(id=pk)
            has_wallet = hasattr(client, 'wallet')

            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'has_wallet': has_wallet,
                'wallet_id': client.wallet.id if has_wallet else None,
                'balance': client.wallet.balance if has_wallet else 0,
                'balance_display': f"{client.wallet.balance:,.0f} FCFA" if has_wallet else "0 FCFA",
                'is_active': client.wallet.is_active if has_wallet else False
            })
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur vérification wallet: {e}")
            return Response(
                {"error": f"Erreur lors de la vérification: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 12. RÉCUPÉRER UN WALLET PAR SON ID
    # ============================================================
    @action(detail=True, methods=['get'], url_path='get-wallet')
    def get_wallet_by_id(self, request, pk=None):
        """
        Récupère un wallet spécifique par son ID
        GET /wallet/{wallet_id}/get-wallet/
        """
        # ✅ Autoriser tous les utilisateurs authentifiés pour cette action
        try:
            wallet = ClientWallet.objects.select_related('client').get(id=pk)

            return Response({
                'id': wallet.id,
                'client': wallet.client.id,
                'client_name': wallet.client.name,
                'client_code': wallet.client.code,
                'client_phone': wallet.client.phone,
                'client_type': wallet.client.type,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'total_deposits': wallet.total_deposits,
                'total_used': wallet.total_used,
                'is_active': wallet.is_active,
                'created_at': wallet.created_at,
                'updated_at': wallet.updated_at
            })
        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Porte-monnaie avec l'ID {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Erreur récupération wallet: {e}")
            return Response(
                {"error": f"Erreur lors de la récupération: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# ============================================================
# ✅ NOUVEAU : Client Wallet ViewSet (pour gérer directement via le client)
# ============================================================


class ClientWalletViewSet(viewsets.ViewSet):
    """
    API pour gérer le porte-monnaie des clients via l'ID du client
    """
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['get'], url_path='wallet')
    def get_wallet(self, request, pk=None):
        """
        Récupère le wallet d'un client
        GET /clients/{id}/wallet/
        """
        try:
            client = Client.objects.get(id=pk)
            wallet, created = ClientWallet.objects.get_or_create(client=client)
            serializer = ClientWalletSerializer(wallet)
            return Response(serializer.data)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'], url_path='wallet/deposit')
    def deposit(self, request, pk=None):
        """
        Dépose de l'argent dans le wallet d'un client
        POST /clients/{id}/wallet/deposit/
        Body: { "amount": 1000, "notes": "..." }
        """
        from decimal import Decimal

        try:
            client = Client.objects.get(id=pk)
            wallet, created = ClientWallet.objects.get_or_create(client=client)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )

        amount = request.data.get('amount')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                new_balance = wallet.credit(
                    amount=amount,
                    source='deposit',
                    reference=f"DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes or f"Dépôt de {amount:,.0f} FCFA",
                    created_by=request.user
                )

                return Response({
                    'status': 'success',
                    'message': f'Dépôt de {amount:,.0f} FCFA effectué avec succès',
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'client_id': client.id,
                    'client_name': client.name
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"❌ Erreur lors du dépôt: {e}")
            return Response(
                {"error": f"Erreur lors du dépôt: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'], url_path='wallet/transactions')
    def transactions(self, request, pk=None):
        """
        Historique des transactions du wallet d'un client
        GET /clients/{id}/wallet/transactions/
        """
        try:
            client = Client.objects.get(id=pk)
            wallet, created = ClientWallet.objects.get_or_create(client=client)
            transactions = wallet.transactions.all().order_by(
                '-created_at')[:50]
            serializer = WalletTransactionSerializer(transactions, many=True)
            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'transactions': serializer.data
            })
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND
            )


# ============================================================
# EXPORTATIONS POUR LES URLS
# ============================================================

# On garde tous les ViewSets déjà exportés
# On ajoute ClientWalletViewSet
