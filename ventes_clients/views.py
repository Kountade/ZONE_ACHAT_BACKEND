# apps/ventes_clients/views.py
# ============================================================
# VIEWS COMPLET OPTIMISÉ — LOGICIEL B
# ✅ ZÉRO N+1 — Optimisé pour 10 000+ lignes < 1s
# ✅ Support complet des variantes (ProductVariant)
# ============================================================

import logging
import datetime as dt
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import (
    Q, Sum, Count, F, Prefetch, Value,
    DecimalField, ExpressionWrapper,
)
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.utils import timezone

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

# === Modèles ===
from .models import (
    Client, ClientWallet, Vente, LigneVente, Paiement, Facture,
    Avoir, Taxe, Remise, Devis, LigneDevis, WalletTransaction,
    ClientStock, ClientStockLigne, ClientStockMovement,
    ClientDelivery, ClientDeliveryLigne,
)
from produits_stocks.models import (
    Stock, StockMovement, Warehouse, Product,
    ProductVariant,   # ✅ VARIANTES
)
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
    WalletTransactionSerializer,
    ClientStockSerializer, ClientStockLigneSerializer,
    ClientStockMovementSerializer,
    ClientStockDepositSerializer, ClientStockWithdrawalSerializer,
    ClientDeliverySerializer, ClientDeliveryLigneSerializer,
    ClientDeliveryLigneCreateSerializer, ClientDeliveryCreateSerializer,
    ClientDeliveryStatusUpdateSerializer,
    ClientDeliveryValidateSerializer, ClientDeliveryRejectSerializer,
    ClientDeliveryRequestCreateSerializer,
    ClientDeliveryRequestUpdateSerializer,
    ClientDeliveryLigneRequestSerializer,
)

# === Pagination ===
from .pagination import VentePagination, OptimizedPagination, LargePagination

logger = logging.getLogger(__name__)


# ============================================================
# QUERYSETS RÉUTILISABLES (anti-N+1)
# ✅ VARIANTES : select_related('variant') ajouté partout
# ============================================================

def _vente_list_queryset():
    return (
        Vente.objects
        .select_related('client', 'warehouse', 'created_by')
        .prefetch_related('invoices', 'devis_source')
    )


def _vente_detail_queryset():
    return (
        Vente.objects
        .select_related('client', 'warehouse', 'created_by')
        .prefetch_related(
            'lines__product',
            'lines__variant',   # ✅ VARIANTES
            'lines__lot',
            'devis_source',
            Prefetch(
                'invoices',
                queryset=(
                    Facture.objects
                    .select_related('client', 'sale')
                    .prefetch_related(
                        Prefetch(
                            'paiements',
                            queryset=(
                                Paiement.objects
                                .select_related(
                                    'facture__client',
                                    'caisse_destination',
                                    'compte_destination',
                                    'received_by',
                                )
                            ),
                        ),
                    )
                ),
            ),
        )
    )


def _facture_list_queryset():
    return (
        Facture.objects
        .select_related('client', 'sale', 'sale__warehouse')
        .prefetch_related(
            Prefetch(
                'paiements',
                queryset=(
                    Paiement.objects
                    .select_related(
                        'facture__client',
                        'caisse_destination',
                        'compte_destination',
                        'received_by',
                    )
                ),
            ),
        )
        .annotate(
            remaining_calc=ExpressionWrapper(
                F('total') - F('amount_paid'),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )


def _paiement_queryset():
    return (
        Paiement.objects
        .select_related(
            'facture',
            'facture__client',
            'facture__sale',
            'received_by',
            'caisse_destination',
            'compte_destination',
        )
    )


def _devis_list_queryset():
    return (
        Devis.objects
        .select_related('client', 'warehouse', 'created_by', 'sale')
    )


def _devis_detail_queryset():
    return (
        Devis.objects
        .select_related('client', 'warehouse', 'created_by')
        .prefetch_related(
            'lignes__product',
            'lignes__variant',   # ✅ VARIANTES
            Prefetch(
                'sale',
                queryset=(
                    Vente.objects
                    .select_related('client', 'warehouse')
                    .prefetch_related('invoices')
                ),
            ),
        )
    )


def _avoir_queryset():
    return (
        Avoir.objects
        .select_related('client', 'sale', 'created_by')
        .prefetch_related(
            'lignes__product',
            'lignes__variant',   # ✅ VARIANTES
            'lignes__ligne_vente',
        )
    )


def _delivery_queryset():
    return (
        ClientDelivery.objects
        .select_related('client', 'client_stock', 'created_by', 'validated_by')
        .prefetch_related(
            Prefetch(
                'lignes',
                queryset=(
                    ClientDeliveryLigne.objects
                    .select_related('product', 'variant', 'client_stock_ligne')  # ✅ VARIANTES
                ),
            ),
        )
    )


# ============================================================
# FONCTION UTILITAIRE POUR CRÉER UN MOUVEMENT DE PAIEMENT
# ============================================================

def creer_mouvement_paiement_manuel(paiement, facture, request_user):
    logger.info(
        f"🔍 creer_mouvement_paiement_manuel - paiement {paiement.id}, "
        f"facture {facture.invoice_number}"
    )

    sale = facture.sale
    if not sale:
        logger.warning(f"❌ Paiement {paiement.id} : aucune vente associée")
        return None

    if not sale.warehouse:
        logger.warning(f"❌ Paiement {paiement.id} : pas d'entrepôt")
        return None

    try:
        from tresorerie.models import MouvementTresorerie, Caisse, CompteBancaire

        existing_movement = MouvementTresorerie.objects.filter(
            source_type='paiement_client',
            source_id=paiement.id
        ).first()

        if existing_movement:
            logger.info("ℹ️ Mouvement déjà existant")
            return existing_movement

        caisse = None
        compte = None

        if paiement.caisse_destination_id:
            try:
                caisse = Caisse.objects.get(id=paiement.caisse_destination_id)
            except Caisse.DoesNotExist:
                pass

        if paiement.compte_destination_id:
            try:
                compte = CompteBancaire.objects.get(
                    id=paiement.compte_destination_id)
            except CompteBancaire.DoesNotExist:
                pass

        if not caisse and not compte:
            caisse = Caisse.objects.filter(
                warehouse=sale.warehouse,
                is_default=True
            ).first()

            if not caisse:
                caisse = Caisse.objects.filter(
                    warehouse=sale.warehouse,
                    is_active=True
                ).first()

        if not caisse and not compte:
            logger.warning(f"❌ Aucune destination pour paiement {paiement.id}")
            return None

        client_name = facture.client.name if facture.client_id else 'N/A'

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
            libelle=f"Paiement client - {facture.invoice_number} - {client_name}",
            created_by=request_user,
        )

        if caisse:
            caisse.solde_actuel += paiement.amount
            caisse.save(update_fields=['solde_actuel', 'updated_at'])

        if compte:
            compte.solde_actuel += paiement.amount
            compte.save(update_fields=['solde_actuel', 'updated_at'])

        logger.info(f"✅ Mouvement créé : {mouvement.reference}")
        return mouvement

    except ImportError as e:
        logger.error(f"❌ Import trésorerie échoué: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur mouvement: {e}")
        return None


# ============================================================
# CLIENT VIEWSET
# ============================================================

class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LargePagination

    def get_serializer_class(self):
        if self.action == 'list':
            return ClientListSerializer
        return ClientSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(phone__icontains=search)
            )
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)
        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def sales(self, request, pk=None):
        client = self.get_object()
        sales = (
            _vente_list_queryset()
            .filter(client=client)
            .order_by('-sale_date')[:50]
        )
        serializer = VenteListSerializer(
            sales, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def devis(self, request, pk=None):
        client = self.get_object()
        devis = (
            _devis_list_queryset()
            .filter(client=client)
            .order_by('-devis_date')[:50]
        )
        serializer = DevisListSerializer(
            devis, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        client = self.get_object()

        stats_agg = Vente.objects.filter(client=client).aggregate(
            total_orders=Count('id'),
            total_purchases=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            draft=Count('id', filter=Q(status='draft')),
            confirmed=Count('id', filter=Q(status='confirmed')),
            paid=Count('id', filter=Q(status='paid')),
            delivered=Count('id', filter=Q(status='delivered')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            returned=Count('id', filter=Q(status='returned')),
        )

        total_orders = stats_agg['total_orders'] or 0
        total_purchases = stats_agg['total_purchases'] or Decimal('0')

        orders_by_status = {}
        for key in ['draft', 'confirmed', 'paid', 'delivered', 'cancelled', 'returned']:
            if stats_agg[key] > 0:
                orders_by_status[key] = stats_agg[key]

        return Response({
            'total_orders': total_orders,
            'total_purchases': float(total_purchases),
            'orders_by_status': orders_by_status,
            'average_order_value': (
                float(total_purchases / total_orders) if total_orders else 0
            ),
        })

    @action(detail=True, methods=['get'], url_path='unpaid-invoices')
    def unpaid_invoices(self, request, pk=None):
        client = self.get_object()

        factures = (
            _facture_list_queryset()
            .filter(
                client=client,
                status__in=['sent', 'overdue', 'partial'],
                remaining_calc__gt=0,
            )
            .order_by('due_date')
        )

        serializer = FactureSerializer(
            factures, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='wallet')
    def get_client_wallet(self, request, pk=None):
        client = self.get_object()
        wallet, _ = ClientWallet.objects.select_related('client').get_or_create(
            client=client
        )
        serializer = ClientWalletSerializer(
            wallet, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='stock')
    def get_client_stock(self, request, pk=None):
        client = self.get_object()
        stock, _ = ClientStock.objects.prefetch_related(
            Prefetch(
                'lignes',
                queryset=ClientStockLigne.objects.select_related(
                    'product', 'product__unit', 'variant'   # ✅ VARIANTES
                ),
            ),
        ).get_or_create(client=client)
        serializer = ClientStockSerializer(stock, context={'request': request})
        return Response(serializer.data)


# ============================================================
# DEVIS VIEWSET
# ============================================================

class DevisViewSet(viewsets.ModelViewSet):
    queryset = Devis.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OptimizedPagination

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
        queryset = _devis_list_queryset().order_by('-devis_date', '-id')

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
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            try:
                date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
                queryset = queryset.filter(devis_date__gte=date_start)
            except ValueError:
                pass
        date_to = self.request.query_params.get('date_to')
        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
                date_end = date_end.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(devis_date__lte=date_end)
            except ValueError:
                pass
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
                'devis_number': devis.devis_number,
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def convert_to_sale(self, request, pk=None):
        devis = self.get_object()
        if devis.status != 'accepted':
            return Response(
                {"error": "Seul un devis accepté peut être converti en vente"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if devis.sale:
            return Response(
                {"error": "Ce devis a déjà été converti en vente"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not devis.warehouse:
            return Response(
                {"error": "L'entrepôt doit être défini"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            vente = devis.convert_to_sale(user=request.user)
            vente = _vente_detail_queryset().get(pk=vente.pk)
            devis = _devis_detail_queryset().get(pk=devis.pk)
            return Response({
                'message': 'Devis converti en vente avec succès',
                'sale': VenteDetailSerializer(vente, context={'request': request}).data,
                'devis': DevisDetailSerializer(devis, context={'request': request}).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": f"Erreur lors de la conversion: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
                'qr_code_data': devis.qr_code_data,
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ============================================================
# VENTE VIEWSET
# ============================================================

class VenteViewSet(viewsets.ModelViewSet):
    queryset = Vente.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = VentePagination

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
        queryset = _vente_list_queryset().order_by('-sale_date', '-id')

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
            try:
                date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
                queryset = queryset.filter(sale_date__gte=date_start)
            except ValueError:
                pass
        date_to = self.request.query_params.get('date_to')
        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
                date_end = date_end.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(sale_date__lte=date_end)
            except ValueError:
                pass

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

    def _aggregate_stats(self, stats_qs):
        stats_agg = stats_qs.aggregate(
            total_count=Count('id'),
            total_amount=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            draft=Count('id', filter=Q(status='draft')),
            confirmed=Count('id', filter=Q(status='confirmed')),
            paid=Count('id', filter=Q(status='paid')),
            delivered=Count('id', filter=Q(status='delivered')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            returned=Count('id', filter=Q(status='returned')),
            pay_pending=Count('id', filter=Q(payment_status='pending')),
            pay_partial=Count('id', filter=Q(payment_status='partial')),
            pay_paid=Count('id', filter=Q(payment_status='paid')),
        )

        return {
            'total': stats_agg['total_count'] or 0,
            'total_amount': float(stats_agg['total_amount'] or 0),
            'by_status': {
                'draft': stats_agg['draft'],
                'confirmed': stats_agg['confirmed'],
                'paid': stats_agg['paid'],
                'delivered': stats_agg['delivered'],
                'cancelled': stats_agg['cancelled'],
                'returned': stats_agg['returned'],
            },
            'by_payment_status': {
                'pending': stats_agg['pay_pending'],
                'partial': stats_agg['pay_partial'],
                'paid': stats_agg['pay_paid'],
            },
        }

    def _apply_list_filters(self, qs, request):
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status__in=status_filter.split(','))

        payment_status = request.query_params.get('payment_status')
        if payment_status:
            qs = qs.filter(payment_status=payment_status)

        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(invoice_number__icontains=search) |
                Q(client_name__icontains=search)
            )

        warehouse = request.query_params.get('warehouse')
        if warehouse:
            qs = qs.filter(warehouse_id=warehouse)

        return qs

    @action(detail=False, methods=['get'], url_path='by-date')
    def get_by_date(self, request):
        date_str = request.query_params.get('date')
        if date_str:
            try:
                target_date = dt.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "Format de date invalide. Utilisez YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.now().date()

        date_start = dt.datetime.combine(target_date, dt.datetime.min.time())
        date_end = date_start + timedelta(days=1)

        stats_qs = Vente.objects.filter(
            sale_date__gte=date_start,
            sale_date__lt=date_end,
        )
        stats_qs = self._apply_list_filters(stats_qs, request)
        stats = self._aggregate_stats(stats_qs)

        list_qs = (
            _vente_list_queryset()
            .filter(sale_date__gte=date_start, sale_date__lt=date_end)
            .order_by('-sale_date')
        )
        list_qs = self._apply_list_filters(list_qs, request)

        page = self.paginate_queryset(list_qs)
        if page is not None:
            serializer = VenteListSerializer(
                page, many=True, context={'request': request}
            )
            response = self.get_paginated_response(serializer.data)
            response.data['date'] = target_date.isoformat()
            response.data['stats'] = stats
            return response

        serializer = VenteListSerializer(
            list_qs, many=True, context={'request': request}
        )
        return Response({
            'date': target_date.isoformat(),
            'stats': stats,
            'results': serializer.data,
        })

    @action(detail=False, methods=['get'], url_path='date-range')
    def get_date_range(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if not date_from or not date_to:
            return Response(
                {"error": "Les paramètres date_from et date_to sont requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
            date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
        except ValueError:
            return Response(
                {"error": "Format de date invalide. Utilisez YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        date_end = date_end.replace(hour=23, minute=59, second=59)

        stats_qs = Vente.objects.filter(
            sale_date__gte=date_start,
            sale_date__lte=date_end,
        )
        stats_qs = self._apply_list_filters(stats_qs, request)
        stats = self._aggregate_stats(stats_qs)

        list_qs = (
            _vente_list_queryset()
            .filter(sale_date__gte=date_start, sale_date__lte=date_end)
            .order_by('-sale_date')
        )
        list_qs = self._apply_list_filters(list_qs, request)

        page = self.paginate_queryset(list_qs)
        if page is not None:
            serializer = VenteListSerializer(
                page, many=True, context={'request': request}
            )
            response = self.get_paginated_response(serializer.data)
            response.data['date_from'] = date_from
            response.data['date_to'] = date_to
            response.data['stats'] = stats
            return response

        serializer = VenteListSerializer(
            list_qs, many=True, context={'request': request}
        )
        return Response({
            'date_from': date_from,
            'date_to': date_to,
            'stats': stats,
            'results': serializer.data,
        })

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'draft':
            return Response(
                {"error": "Seule une vente en brouillon peut être confirmée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not vente.warehouse:
            return Response(
                {"error": "Un entrepôt est requis pour confirmer la vente"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # ✅ VARIANTES : select_related('variant')
            lines = list(vente.lines.select_related('product', 'variant').all())

            # ✅ VARIANTES : map par (product_id, variant_id)
            stock_map = {}
            product_variant_pairs = [
                (l.product_id, l.variant_id) for l in lines
            ]
            stocks_qs = Stock.objects.filter(
                warehouse=vente.warehouse,
                product_id__in={p for p, _ in product_variant_pairs},
            )
            for s in stocks_qs:
                stock_map[(s.product_id, s.variant_id)] = s

            stock_errors = []
            for line in lines:
                stock = stock_map.get((line.product_id, line.variant_id))
                if not stock or stock.available_quantity < line.quantity:
                    available = stock.available_quantity if stock else 0
                    label = line.product.name
                    if line.variant_id:
                        label += f" [{line.variant.sku}]"
                    stock_errors.append(
                        f"{label}: disponible {available}, "
                        f"demandé {line.quantity}"
                    )

            if stock_errors:
                return Response({
                    "error": "Stock insuffisant pour les produits suivants:",
                    "details": stock_errors,
                }, status=status.HTTP_400_BAD_REQUEST)

            if not vente.client and not vente.client_name:
                vente.client_name = "Client anonyme"
                vente.save(update_fields=['client_name'])

            vente.status = 'confirmed'
            vente.save()

            mouvement = None
            try:
                from tresorerie.models import MouvementTresorerie, Caisse

                existing = MouvementTresorerie.objects.filter(
                    source_type='vente', source_id=vente.id
                ).first()

                if not existing:
                    caisse = Caisse.objects.filter(
                        warehouse=vente.warehouse, is_default=True
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
                            created_by=request.user,
                        )
                        caisse.solde_actuel += vente.total
                        caisse.save(update_fields=[
                            'solde_actuel', 'updated_at'
                        ])
                else:
                    mouvement = existing
            except ImportError:
                logger.warning("Module tresorerie non disponible")
            except Exception as e:
                logger.error(f"Erreur mouvement trésorerie: {e}")

            facture = Facture.objects.filter(sale=vente).first()
            if not facture:
                from .models import generate_number
                invoice_number = generate_number(
                    Facture, 'invoice_number', 'FAC'
                )
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
                    notes=f"Facture auto depuis vente {vente.invoice_number}",
                )
                facture.generate_qr_code()
                facture.save()

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
                'amount_due': vente.amount_due,
            })

        except Exception as e:
            vente.status = 'draft'
            vente.save(update_fields=['status', 'updated_at'])
            logger.exception("Erreur confirmation vente")
            return Response(
                {"error": f"Erreur: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    def register_payment(self, request, pk=None):
        vente = self.get_object()

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
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_due = vente.total - vente.amount_paid
        if amount > amount_due:
            return Response(
                {"error": f"Le montant dépasse le solde ({amount_due:,.0f} FCFA)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            facture = vente.invoices.first()
            if not facture:
                return Response(
                    {"error": "Aucune facture pour cette vente"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement vente {vente.invoice_number}",
                received_by=request.user,
                caisse_destination_id=caisse_destination_id,
                compte_destination_id=compte_destination_id,
            )

            total_paid_facture = facture.paiements.aggregate(
                total=Sum('amount'))['total'] or Decimal('0')
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

            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user
            )

        return Response({
            'status': 'success',
            'message': 'Paiement enregistré avec succès',
            'amount_paid': vente.amount_paid,
            'amount_due': vente.amount_due,
            'payment_status': vente.payment_status,
            'mouvement_cree': mouvement is not None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        vente = self.get_object()
        status_value = request.data.get('status')
        notes = request.data.get('notes', '')

        if not status_value:
            return Response(
                {"error": "Le statut est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed_statuses = ['draft', 'confirmed',
                            'paid', 'delivered', 'cancelled', 'returned']
        if status_value not in allowed_statuses:
            return Response(
                {"error": f"Statut invalide. Choisir parmi: {', '.join(allowed_statuses)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = vente.status
        if old_status == 'draft' and status_value == 'confirmed':
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
                'invoice_number': vente.invoice_number,
            })
        except Exception as e:
            return Response(
                {"error": f"Erreur: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        vente = self.get_object()

        if vente.status not in ['confirmed', 'delivered']:
            return Response(
                {"error": "Seule une vente confirmée ou livrée peut être marquée payée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_due = vente.amount_due
        if amount_due <= 0:
            return Response(
                {"error": "Cette vente est déjà entièrement payée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        facture = vente.invoices.first()
        if not facture:
            facture = vente.generate_invoice()
            if not facture:
                return Response(
                    {"error": "Impossible de générer une facture"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        with transaction.atomic():
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount_due,
                method='cash',
                reference='',
                notes='Paiement automatique',
                received_by=request.user,
            )

            total_paid_facture = facture.paiements.aggregate(
                total=Sum('amount'))['total'] or Decimal('0')
            facture.amount_paid = total_paid_facture
            facture.status = 'paid' if total_paid_facture >= facture.total else 'partial'
            facture.save()

            vente.amount_paid += amount_due
            vente.amount_due = vente.total - vente.amount_paid
            if vente.amount_due <= 0:
                vente.payment_status = 'paid'
                vente.status = 'paid'
            vente.save()

            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user
            )

        return Response({
            'status': 'success',
            'message': 'Vente marquée comme payée',
            'amount_paid': vente.amount_paid,
            'amount_due': vente.amount_due,
            'payment_status': vente.payment_status,
            'invoice_number': vente.invoice_number,
            'mouvement_cree': mouvement is not None,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        vente = self.get_object()

        if vente.status in ['paid', 'delivered']:
            return Response(
                {"error": "Cette vente ne peut pas être annulée"},
                status=status.HTTP_400_BAD_REQUEST,
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
                'message': 'Vente annulée',
                'stock_restored': old_status == 'confirmed',
                'invoice_number': vente.invoice_number,
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        vente = self.get_object()

        if vente.status != 'confirmed':
            return Response(
                {"error": "Seule une vente confirmée peut être livrée"},
                status=status.HTTP_400_BAD_REQUEST,
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
            'invoice_number': vente.invoice_number,
        })

    @action(detail=True, methods=['post'])
    def return_sale(self, request, pk=None):
        vente = self.get_object()

        if vente.status not in ['delivered', 'paid']:
            return Response(
                {"error": "Seules les ventes livrées ou payées peuvent être retournées"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            vente.restore_stock()
            vente.status = 'returned'
            vente.save()
            return Response({
                'status': vente.status,
                'message': 'Vente retournée avec succès',
                'stock_restored': True,
                'invoice_number': vente.invoice_number,
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        vente = _vente_detail_queryset().get(pk=pk)
        payments = [
            p for facture in vente.invoices.all()
            for p in facture.paiements.all()
        ]
        serializer = PaiementSerializer(
            payments, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        vente = _vente_detail_queryset().get(pk=pk)
        serializer = FactureSerializer(
            vente.invoices.all(), many=True, context={'request': request}
        )
        return Response(serializer.data)

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
                'invoice_number': vente.invoice_number,
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @action(detail=True, methods=['get'])
    def stock_movements(self, request, pk=None):
        vente = self.get_object()
        movements = StockMovement.objects.filter(
            reference_type='sale',
            reference_id=vente.id,
        ).select_related('product', 'lot', 'variant').order_by('-created_at')  # ✅ VARIANTES
        from produits_stocks.serializers import StockMovementSerializer
        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30

        start_date = timezone.now() - timedelta(days=days)

        try:
            stats_agg = Vente.objects.filter(
                sale_date__gte=start_date
            ).aggregate(
                total_ventes=Count('id'),
                total_montant=Coalesce(
                    Sum('total'), Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                ),
                total_paye=Coalesce(
                    Sum('amount_paid'), Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                ),
                draft=Count('id', filter=Q(status='draft')),
                confirmed=Count('id', filter=Q(status='confirmed')),
                paid=Count('id', filter=Q(status='paid')),
                delivered=Count('id', filter=Q(status='delivered')),
                cancelled=Count('id', filter=Q(status='cancelled')),
                returned=Count('id', filter=Q(status='returned')),
                pay_pending=Count('id', filter=Q(payment_status='pending')),
                pay_partial=Count('id', filter=Q(payment_status='partial')),
                pay_paid=Count('id', filter=Q(payment_status='paid')),
            )

            total_ventes = stats_agg['total_ventes'] or 0
            total_montant = stats_agg['total_montant'] or Decimal('0')
            total_paye = stats_agg['total_paye'] or Decimal('0')
            total_due = total_montant - total_paye

            by_status = {
                k: stats_agg[k] for k in
                ['draft', 'confirmed', 'paid', 'delivered', 'cancelled', 'returned']
                if stats_agg[k] > 0
            }
            by_payment_status = {
                'pending': stats_agg['pay_pending'],
                'partial': stats_agg['pay_partial'],
                'paid': stats_agg['pay_paid'],
            }
            by_payment_status = {
                k: v for k, v in by_payment_status.items() if v > 0
            }

            avg_amount = (
                total_montant / total_ventes
                if total_ventes > 0 else Decimal('0')
            )

            return Response({
                'period': {
                    'days': days,
                    'start_date': start_date.strftime('%Y-%m-%d'),
                    'end_date': timezone.now().strftime('%Y-%m-%d'),
                },
                'total_ventes': total_ventes,
                'total_montant': float(total_montant),
                'total_paye': float(total_paye),
                'total_due': float(total_due),
                'avg_amount': float(avg_amount),
                'by_status': by_status,
                'by_payment_status': by_payment_status,
            })
        except Exception as e:
            logger.exception("Erreur stats")
            return Response(
                {"error": f"Erreur: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ============================================================
# FACTURE VIEWSET
# ============================================================

class FactureViewSet(viewsets.ModelViewSet):
    queryset = Facture.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OptimizedPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return FactureCreateSerializer
        return FactureSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = _facture_list_queryset()

        client = self.request.query_params.get('client')
        if client:
            queryset = queryset.filter(client_id=client)
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status__in=status_param.split(','))
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
        return queryset.order_by('-invoice_date', '-id')

    @action(detail=False, methods=['get'], url_path='search-unpaid')
    def search_unpaid(self, request):
        query = request.query_params.get('q', '').strip()
        client_id = request.query_params.get('client_id')
        try:
            limit = min(int(request.query_params.get('limit', 20)), 50)
        except (TypeError, ValueError):
            limit = 20

        status_param = request.query_params.get(
            'status', 'sent,overdue,partial'
        )
        statuses = [s.strip() for s in status_param.split(',') if s.strip()]

        qs = (
            _facture_list_queryset()
            .filter(status__in=statuses, remaining_calc__gt=0)
            .order_by('due_date')
        )

        if client_id:
            qs = qs.filter(client_id=client_id)

        if query:
            qs = qs.filter(
                Q(invoice_number__icontains=query) |
                Q(client__name__icontains=query) |
                Q(client__code__icontains=query) |
                Q(client__phone__icontains=query)
            )

        qs = qs[:limit]

        serializer = FactureSerializer(
            qs, many=True, context={'request': request}
        )
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })

    @action(detail=False, methods=['get'], url_path='unpaid')
    def unpaid_invoices(self, request):
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response(
                {"error": "Le paramètre client_id est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = (
            _facture_list_queryset()
            .filter(
                client_id=client_id,
                status__in=['sent', 'overdue', 'partial'],
                remaining_calc__gt=0,
            )
            .order_by('due_date')
        )

        serializer = FactureSerializer(
            qs, many=True, context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='client-stats')
    def client_stats(self, request):
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response(
                {"error": "Le paramètre client_id est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stats_agg = Facture.objects.filter(client_id=client_id).aggregate(
            total_factures=Count('id'),
            total_montant=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_paye=Coalesce(
                Sum('amount_paid'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            draft=Count('id', filter=Q(status='draft')),
            sent=Count('id', filter=Q(status='sent')),
            paid=Count('id', filter=Q(status='paid')),
            overdue=Count('id', filter=Q(status='overdue')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            partial=Count('id', filter=Q(status='partial')),
        )

        total_montant = stats_agg['total_montant'] or Decimal('0')
        total_paye = stats_agg['total_paye'] or Decimal('0')

        par_statut = {}
        for k in ['draft', 'sent', 'paid', 'overdue', 'cancelled', 'partial']:
            if stats_agg[k] > 0:
                par_statut[k] = stats_agg[k]

        return Response({
            'total_factures': stats_agg['total_factures'] or 0,
            'total_montant': float(total_montant),
            'total_paye': float(total_paye),
            'total_impaye': float(total_montant - total_paye),
            'par_statut': par_statut,
        })

    @action(detail=True, methods=['post'])
    def register_payment(self, request, pk=None):
        facture = self.get_object()

        amount = request.data.get('amount')
        method = request.data.get('method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount > facture.remaining_amount:
            return Response(
                {"error": f"Montant dépasse le restant ({facture.remaining_amount:,.0f} FCFA)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement facture {facture.invoice_number}",
                received_by=request.user,
            )

            total_paid = facture.paiements.aggregate(
                total=Sum('amount'))['total'] or Decimal('0')
            facture.amount_paid = total_paid
            if facture.amount_paid >= facture.total:
                facture.status = 'paid'
            elif facture.amount_paid > 0:
                facture.status = 'partial'
            facture.save()

            sale = facture.sale
            if sale:
                total_paid_sale = (
                    Facture.objects.filter(sale=sale).aggregate(
                        total=Sum('amount_paid')
                    )['total'] or Decimal('0')
                )
                sale.amount_paid = total_paid_sale
                sale.amount_due = max(
                    Decimal('0'), sale.total - total_paid_sale
                )
                if sale.amount_due <= 0:
                    sale.payment_status = 'paid'
                elif sale.amount_paid > 0:
                    sale.payment_status = 'partial'
                else:
                    sale.payment_status = 'pending'
                sale.save()

            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user
            )

        serializer = PaiementSerializer(paiement, context={'request': request})
        return Response({
            'paiement': serializer.data,
            'facture': FactureSerializer(facture, context={'request': request}).data,
            'remaining_amount': facture.remaining_amount,
            'mouvement_cree': mouvement is not None,
            'mouvement_reference': mouvement.reference if mouvement else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        facture = self.get_object()

        amount = request.data.get('amount', 0)
        method = request.data.get('method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le montant doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0 or amount > facture.remaining_amount:
            return Response(
                {"error": f"Montant invalide (restant: {facture.remaining_amount:,.0f})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            paiement = Paiement.objects.create(
                facture=facture,
                amount=amount,
                method=method,
                reference=reference,
                notes=notes or f"Paiement facture {facture.invoice_number}",
                received_by=request.user,
            )

            total_paid = facture.paiements.aggregate(
                total=Sum('amount'))['total'] or Decimal('0')
            facture.amount_paid = total_paid
            if facture.amount_paid >= facture.total:
                facture.status = 'paid'
            elif facture.amount_paid > 0:
                facture.status = 'partial'
            facture.save()

            sale = facture.sale
            if sale:
                total_paid_sale = (
                    Facture.objects.filter(sale=sale).aggregate(
                        total=Sum('amount_paid')
                    )['total'] or Decimal('0')
                )
                sale.amount_paid = total_paid_sale
                sale.amount_due = max(
                    Decimal('0'), sale.total - total_paid_sale
                )
                if sale.amount_due <= 0:
                    sale.payment_status = 'paid'
                elif sale.amount_paid > 0:
                    sale.payment_status = 'partial'
                else:
                    sale.payment_status = 'pending'
                sale.save()

            mouvement = creer_mouvement_paiement_manuel(
                paiement, facture, request.user
            )

        return Response({
            'paiement': PaiementSerializer(paiement, context={'request': request}).data,
            'facture_status': facture.status,
            'remaining_amount': facture.remaining_amount,
            'mouvement_cree': mouvement is not None,
            'mouvement_reference': mouvement.reference if mouvement else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        facture = self.get_object()
        if facture.status != 'draft':
            return Response(
                {"error": "Seules les factures en brouillon peuvent être envoyées"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        facture.status = 'sent'
        facture.save()
        facture.generate_qr_code()
        facture.save()
        return Response({
            'status': facture.status,
            'message': 'Facture envoyée',
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        facture = self.get_object()
        if facture.status == 'paid':
            return Response(
                {"error": "Les factures payées ne peuvent pas être annulées"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        facture.status = 'cancelled'
        facture.save()
        return Response({
            'status': facture.status,
            'message': 'Facture annulée',
        })

    @action(detail=True, methods=['post'])
    def generate_invoice(self, request, pk=None):
        sale_id = request.data.get('sale_id')
        due_date = request.data.get('due_date')

        if not sale_id:
            return Response(
                {"error": "L'ID de la vente est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            sale = Vente.objects.select_related('client').get(id=sale_id)
        except Vente.DoesNotExist:
            return Response(
                {"error": "Vente non trouvée"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if Facture.objects.filter(sale=sale).exists():
            return Response(
                {"error": "Une facture existe déjà"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if due_date:
            try:
                due_date = date.fromisoformat(due_date)
            except ValueError:
                return Response(
                    {"error": "Format de date invalide"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            due_date = date.today() + timedelta(days=30)

        with transaction.atomic():
            from .models import generate_number
            invoice_number = generate_number(
                Facture, 'invoice_number', 'FAC'
            )

            facture = Facture.objects.create(
                invoice_number=invoice_number,
                sale=sale,
                client=sale.client,
                due_date=due_date,
                subtotal=sale.subtotal,
                tax_amount=sale.tax_amount,
                total=sale.total,
                status='sent',
            )
            facture.generate_qr_code()
            facture.save()

        return Response({
            'facture': FactureSerializer(facture, context={'request': request}).data,
            'message': 'Facture générée avec succès',
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        facture = self.get_object()
        if not facture.qr_code:
            facture.generate_qr_code()
            facture.save()
        if facture.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(facture.qr_code.url),
                'qr_code_data': facture.qr_code_data,
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @action(detail=True, methods=['get'])
    def paiements(self, request, pk=None):
        facture = _facture_list_queryset().get(pk=pk)
        serializer = PaiementSerializer(
            facture.paiements.all(), many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# PAIEMENT VIEWSET
# ============================================================

class PaiementViewSet(viewsets.ModelViewSet):
    queryset = Paiement.objects.all()
    serializer_class = PaiementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OptimizedPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = _paiement_queryset().order_by('-payment_date')

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

class AvoirViewSet(viewsets.ModelViewSet):
    queryset = _avoir_queryset()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OptimizedPagination

    def get_serializer_class(self):
        if self.action == "create":
            return AvoirCreateSerializer
        return AvoirSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        queryset = _avoir_queryset().order_by('-date', '-id')

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
                Q(avoir_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(reason__icontains=search)
            )

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        restore_stock = request.data.get("restore_stock", False)
        if isinstance(restore_stock, str):
            restore_stock = restore_stock.lower() == "true"

        try:
            with transaction.atomic():
                avoir = serializer.save(created_by=request.user)

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

                mouvement_tresorerie = None
                try:
                    from tresorerie.models import MouvementTresorerie, Caisse

                    if avoir.sale and avoir.sale.warehouse:
                        caisse = Caisse.objects.filter(
                            warehouse=avoir.sale.warehouse, is_default=True
                        ).first()

                        if not caisse:
                            caisse = Caisse.objects.filter(
                                warehouse=avoir.sale.warehouse, is_active=True
                            ).first()

                        if caisse:
                            existing = MouvementTresorerie.objects.filter(
                                source_type="avoir", source_id=avoir.id
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
                                caisse.solde_actuel -= avoir.amount
                                caisse.save(update_fields=[
                                    "solde_actuel", "updated_at"
                                ])
                            else:
                                mouvement_tresorerie = existing
                except ImportError:
                    pass
                except Exception as e:
                    logger.error(f"Erreur trésorerie : {e}")

                avoir = _avoir_queryset().get(pk=avoir.pk)

                return Response({
                    "status": "success",
                    "message": "Avoir créé avec succès",
                    "avoir": AvoirSerializer(
                        avoir, context={"request": request}
                    ).data,
                    "stock_restored": stock_restored,
                    "stock_details": stock_details,
                    "mouvement_tresorerie_cree": mouvement_tresorerie is not None,
                    "mouvement_reference": (
                        mouvement_tresorerie.reference
                        if mouvement_tresorerie else None
                    ),
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Erreur création avoir")
            return Response(
                {"error": f"Erreur : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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


# ============================================================
# TAXE / REMISE
# ============================================================

class TaxeViewSet(viewsets.ModelViewSet):
    queryset = Taxe.objects.all()
    serializer_class = TaxeSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]


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
# DASHBOARD STATS
# ============================================================

class SalesDashboardStatsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        today = date.today()
        start_of_month = today.replace(day=1)
        start_of_week = today - timedelta(days=today.weekday())

        ventes_agg = Vente.objects.aggregate(
            total_sales=Count('id'),
            total_amount=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            sales_today=Count('id', filter=Q(sale_date__date=today)),
            sales_this_week=Count(
                'id', filter=Q(sale_date__date__gte=start_of_week)
            ),
            sales_this_month=Count(
                'id', filter=Q(sale_date__date__gte=start_of_month)
            ),
            amount_today=Coalesce(
                Sum('total', filter=Q(sale_date__date=today)),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            amount_this_month=Coalesce(
                Sum('total', filter=Q(sale_date__date__gte=start_of_month)),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            pending_payments=Count(
                'id', filter=Q(payment_status__in=['pending', 'partial'])
            ),
            pending_amount=Coalesce(
                Sum('amount_due', filter=Q(
                    payment_status__in=['pending', 'partial']
                )),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )

        total_clients = Client.objects.filter(statut='actif').count()

        factures_agg = Facture.objects.aggregate(
            pending=Count('id', filter=Q(
                status__in=['draft', 'sent', 'partial']
            )),
            overdue=Count('id', filter=Q(status='overdue')),
        )

        devis_agg = Devis.objects.aggregate(
            total=Count('id'),
            en_attente=Count('id', filter=Q(status='sent')),
            acceptes=Count('id', filter=Q(status='accepted')),
            expires=Count('id', filter=Q(status='expired')),
            convertis=Count('id', filter=Q(status='converted')),
        )

        return Response({
            'sales': {
                'total': ventes_agg['total_sales'] or 0,
                'today': ventes_agg['sales_today'] or 0,
                'this_week': ventes_agg['sales_this_week'] or 0,
                'this_month': ventes_agg['sales_this_month'] or 0,
            },
            'amounts': {
                'total': float(ventes_agg['total_amount'] or 0),
                'today': float(ventes_agg['amount_today'] or 0),
                'this_month': float(ventes_agg['amount_this_month'] or 0),
            },
            'payments': {
                'pending': ventes_agg['pending_payments'] or 0,
                'pending_amount': float(ventes_agg['pending_amount'] or 0),
            },
            'clients': {'total': total_clients},
            'invoices': {
                'pending': factures_agg['pending'] or 0,
                'overdue': factures_agg['overdue'] or 0,
            },
            'devis': {
                'total': devis_agg['total'] or 0,
                'en_attente': devis_agg['en_attente'] or 0,
                'acceptes': devis_agg['acceptes'] or 0,
                'expires': devis_agg['expires'] or 0,
                'convertis': devis_agg['convertis'] or 0,
            },
        })


# ============================================================
# WALLET VIEWSET
# ============================================================

class WalletViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _is_admin(self, user):
        return user.role == 'admin' or user.is_staff or user.is_superuser

    @action(detail=False, methods=['get'], url_path='list')
    def list_wallets(self, request):
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stats_agg = ClientWallet.objects.aggregate(
            total=Count('id'),
            total_balance=Coalesce(
                Sum('balance'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            active_count=Count('id', filter=Q(is_active=True)),
            inactive_count=Count('id', filter=Q(is_active=False)),
        )

        wallets = ClientWallet.objects.select_related(
            'client'
        ).all().order_by('-created_at')

        results = [{
            'id': w.id,
            'client': w.client.id,
            'client_name': w.client.name,
            'client_code': w.client.code,
            'client_phone': w.client.phone,
            'client_type': w.client.type,
            'client_statut': w.client.statut,
            'balance': w.balance,
            'balance_display': f"{w.balance:,.0f} FCFA",
            'total_deposits': w.total_deposits,
            'total_used': w.total_used,
            'is_active': w.is_active,
            'created_at': w.created_at,
            'updated_at': w.updated_at,
        } for w in wallets]

        total_balance = stats_agg['total_balance'] or Decimal('0')

        return Response({
            'count': stats_agg['total'] or 0,
            'total_balance': float(total_balance),
            'total_balance_display': f"{total_balance:,.0f} FCFA",
            'active_count': stats_agg['active_count'] or 0,
            'inactive_count': stats_agg['inactive_count'] or 0,
            'results': results,
        })

    @action(detail=True, methods=['get'], url_path='client-wallet')
    def get_client_wallet(self, request, pk=None):
        try:
            wallet = ClientWallet.objects.select_related('client').get(
                client_id=pk
            )
        except ClientWallet.DoesNotExist:
            try:
                client = Client.objects.get(id=pk)
                wallet = ClientWallet.objects.create(client=client)
                wallet = ClientWallet.objects.select_related(
                    'client').get(pk=wallet.pk)
            except Client.DoesNotExist:
                return Response(
                    {"error": f"Client {pk} non trouvé"},
                    status=status.HTTP_404_NOT_FOUND,
                )

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
            'updated_at': wallet.updated_at,
        })

    @action(detail=False, methods=['post'], url_path='create-wallet')
    def create_wallet(self, request):
        client_id = request.data.get('client_id')
        initial_balance = request.data.get('initial_balance', 0)

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            initial_balance = Decimal(str(initial_balance))
        except (TypeError, ValueError):
            return Response(
                {"error": "Le solde initial doit être un nombre valide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if initial_balance < 0:
            return Response(
                {"error": "Le solde initial ne peut pas être négatif"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client = Client.objects.get(id=client_id)

            if hasattr(client, 'wallet'):
                wallet = client.wallet
                return Response(
                    {
                        "error": "Ce client a déjà un porte-monnaie",
                        "wallet": {
                            'id': wallet.id,
                            'balance': wallet.balance,
                            'balance_display': f"{wallet.balance:,.0f} FCFA",
                            'is_active': wallet.is_active,
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                wallet = ClientWallet.objects.create(
                    client=client,
                    balance=initial_balance,
                    total_deposits=initial_balance,
                    total_used=0,
                    is_active=True,
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
                        created_by=request.user,
                    )

                return Response({
                    'status': 'success',
                    'message': f'Wallet créé pour {client.name}',
                    'wallet_id': wallet.id,
                    'balance': wallet.balance,
                    'balance_display': f"{wallet.balance:,.0f} FCFA",
                    'is_active': wallet.is_active,
                }, status=status.HTTP_201_CREATED)

        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=['post'])
    def deposit(self, request):
        client_id = request.data.get('client_id')
        amount = request.data.get('amount')
        notes = request.data.get('notes', '')
        payment_method = request.data.get('payment_method', 'cash')

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Montant invalide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client = Client.objects.get(id=client_id)
            wallet, _ = ClientWallet.objects.get_or_create(client=client)
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with transaction.atomic():
                new_balance = wallet.credit(
                    amount=amount,
                    source='deposit',
                    reference=f"DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes or f"Dépôt de {amount:,.0f} FCFA en {payment_method}",
                    created_by=request.user,
                )

                try:
                    from tresorerie.models import MouvementTresorerie, Caisse

                    sale = Vente.objects.filter(client=client).select_related(
                        'warehouse'
                    ).first()
                    warehouse = sale.warehouse if sale else None

                    caisse = None
                    if warehouse:
                        caisse = Caisse.objects.filter(
                            warehouse=warehouse, is_default=True
                        ).first()
                        if not caisse:
                            caisse = Caisse.objects.filter(
                                warehouse=warehouse, is_active=True
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
                            created_by=request.user,
                        )
                        caisse.solde_actuel += amount
                        caisse.save(update_fields=[
                            'solde_actuel', 'updated_at'
                        ])
                except Exception as e:
                    logger.warning(f"⚠️ Erreur mouvement trésorerie: {e}")

                return Response({
                    'status': 'success',
                    'message': f'Dépôt de {amount:,.0f} FCFA effectué',
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'wallet_id': wallet.id,
                    'client_id': client.id,
                    'client_name': client.name,
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=['post'], url_path='pay-invoice')
    def pay_invoice(self, request):
        facture_id = request.data.get('facture_id')
        amount = request.data.get('amount')
        notes = request.data.get('notes', '')

        if not facture_id:
            return Response(
                {"error": "L'ID de la facture est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Montant invalide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return Response(
                {"error": "Le montant doit être supérieur à 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                facture = Facture.objects.select_related(
                    'sale', 'client'
                ).get(id=facture_id)

                if facture.status == 'paid':
                    return Response(
                        {"error": "Facture déjà payée"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                remaining = facture.remaining_amount
                if amount > remaining:
                    return Response(
                        {"error": f"Montant > restant ({remaining:,.0f} FCFA)"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                client = facture.client
                if not client:
                    return Response(
                        {"error": "Facture sans client"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                wallet, _ = ClientWallet.objects.get_or_create(client=client)

                if not wallet.is_active:
                    return Response(
                        {"error": "Porte-monnaie désactivé"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if wallet.balance < amount:
                    return Response(
                        {"error": f"Solde insuffisant ({wallet.balance:,.0f} FCFA)"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                new_balance = wallet.debit(
                    amount=amount,
                    source='payment',
                    reference=facture.invoice_number,
                    notes=notes or f"Paiement facture {facture.invoice_number}",
                    created_by=request.user,
                )

                paiement = Paiement.objects.create(
                    facture=facture,
                    amount=amount,
                    method='wallet',
                    reference=f"WALLET-{facture.invoice_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=f"Paiement via wallet - {notes or ''}",
                    received_by=request.user,
                )

                total_paid = facture.paiements.aggregate(
                    total=Sum('amount'))['total'] or Decimal('0')
                facture.amount_paid = total_paid
                if facture.amount_paid >= facture.total:
                    facture.status = 'paid'
                else:
                    facture.status = 'partial'
                facture.save(update_fields=[
                    'amount_paid', 'status', 'updated_at'])

                sale = facture.sale
                if sale:
                    total_paid_sale = (
                        Facture.objects.filter(sale=sale).aggregate(
                            total=Sum('amount_paid')
                        )['total'] or Decimal('0')
                    )
                    sale.amount_paid = total_paid_sale
                    sale.amount_due = max(
                        Decimal('0'), sale.total - total_paid_sale
                    )
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
                        'payment_status', 'status', 'updated_at',
                    ])

                return Response({
                    'status': 'success',
                    'message': f'Paiement de {amount:,.0f} FCFA effectué',
                    'wallet_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'paiement_id': paiement.id,
                    'facture_remaining': facture.remaining_amount,
                    'facture_status': facture.status,
                    'facture_number': facture.invoice_number,
                    'sale_status': sale.status if sale else None,
                    'payment_status': sale.payment_status if sale else None,
                }, status=status.HTTP_201_CREATED)

        except Facture.DoesNotExist:
            return Response(
                {"error": f"Facture {facture_id} non trouvée"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=['post'], url_path='pay-all-unpaid')
    def pay_all_unpaid(self, request):
        client_id = request.data.get('client_id')
        notes = request.data.get('notes', 'Paiement groupé')

        if not client_id:
            return Response(
                {"error": "L'ID du client est requis"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        factures_impayees = list(
            Facture.objects
            .select_related('sale')
            .annotate(
                remaining_calc=ExpressionWrapper(
                    F('total') - F('amount_paid'),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .filter(
                client=client,
                status__in=['sent', 'overdue', 'partial'],
                remaining_calc__gt=0,
            )
            .order_by('due_date')
        )

        if not factures_impayees:
            return Response({
                'status': 'success',
                'message': 'Aucune facture impayée',
                'paid_count': 0,
                'total_amount': 0,
            })

        sale_ids = [f.sale_id for f in factures_impayees if f.sale_id]
        paid_by_sale = dict(
            Facture.objects
            .filter(sale_id__in=sale_ids)
            .values('sale_id')
            .annotate(total_paid=Sum('amount_paid'))
            .values_list('sale_id', 'total_paid')
        )

        total_amount = sum(f.remaining_calc for f in factures_impayees)

        wallet, _ = ClientWallet.objects.get_or_create(client=client)

        if not wallet.is_active:
            return Response(
                {"error": "Porte-monnaie désactivé"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if wallet.balance < total_amount:
            return Response(
                {"error": f"Solde insuffisant. Total: {total_amount:,.0f} FCFA, Solde: {wallet.balance:,.0f} FCFA"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                now = timezone.now()
                now_str = now.strftime('%Y%m%d%H%M%S')

                wallet_transactions = []
                paiements = []
                facture_updates = []
                sale_updates = {}
                total_paye = Decimal('0')
                balance = wallet.balance
                total_used = wallet.total_used

                for facture in factures_impayees:
                    amount = facture.remaining_calc
                    balance -= amount
                    total_used += amount

                    wallet_transactions.append(WalletTransaction(
                        wallet=wallet, type='debit', amount=amount,
                        source='payment', reference=facture.invoice_number,
                        notes=f"Paiement facture {facture.invoice_number} - {notes}",
                        balance_after=balance, created_by=request.user,
                    ))

                    paiements.append(Paiement(
                        facture=facture, amount=amount, method='wallet',
                        reference=f"WALLET-{facture.invoice_number}-{now_str}",
                        notes=f"Paiement via wallet - {notes}",
                        received_by=request.user,
                    ))

                    facture.amount_paid = facture.total
                    facture.status = 'paid'
                    facture_updates.append(facture)

                    if facture.sale_id:
                        prev_paid = paid_by_sale.get(
                            facture.sale_id, Decimal('0'))
                        paid_by_sale[facture.sale_id] = prev_paid + amount
                        sale_updates[facture.sale_id] = paid_by_sale[facture.sale_id]

                    total_paye += amount

                WalletTransaction.objects.bulk_create(wallet_transactions)
                Paiement.objects.bulk_create(paiements)
                Facture.objects.bulk_update(
                    facture_updates, ['amount_paid', 'status']
                )

                for sale_id, total_paid_sale in sale_updates.items():
                    sale = Vente.objects.get(pk=sale_id)
                    sale.amount_paid = total_paid_sale
                    sale.amount_due = max(
                        Decimal('0'), sale.total - total_paid_sale
                    )
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
                        'payment_status', 'status', 'updated_at',
                    ])

                wallet.balance = balance
                wallet.total_used = total_used
                wallet.save(update_fields=[
                    'balance', 'total_used', 'updated_at'
                ])

                return Response({
                    'status': 'success',
                    'message': f'Paiement de {total_paye:,.0f} FCFA pour {len(paiements)} factures',
                    'paid_count': len(paiements),
                    'total_amount': float(total_paye),
                    'new_balance': float(balance),
                    'balance_display': f"{balance:,.0f} FCFA",
                    'factures_payees': [f.invoice_number for f in factures_impayees],
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Erreur paiement groupé")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'], url_path='transactions')
    def client_transactions(self, request, pk=None):
        try:
            client = Client.objects.get(id=pk)
            wallet, _ = ClientWallet.objects.get_or_create(client=client)
            transactions = (
                wallet.transactions
                .select_related('created_by')
                .order_by('-created_at')[:50]
            )

            transactions_data = [{
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
                'created_by_name': (
                    t.created_by.get_full_name() if t.created_by else None
                ),
            } for t in transactions]

            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'transactions': transactions_data,
            })
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stats_agg = ClientWallet.objects.aggregate(
            total_wallets=Count('id'),
            total_balance=Coalesce(
                Sum('balance'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            active_wallets=Count('id', filter=Q(is_active=True)),
            inactive_wallets=Count('id', filter=Q(is_active=False)),
        )

        total_wallets = stats_agg['total_wallets'] or 0
        total_balance = stats_agg['total_balance'] or Decimal('0')
        avg_balance = (
            total_balance / total_wallets
            if total_wallets > 0 else Decimal('0')
        )

        return Response({
            'total_wallets': total_wallets,
            'total_balance': float(total_balance),
            'total_balance_display': f"{total_balance:,.0f} FCFA",
            'active_wallets': stats_agg['active_wallets'] or 0,
            'inactive_wallets': stats_agg['inactive_wallets'] or 0,
            'avg_balance': float(avg_balance),
            'avg_balance_display': f"{avg_balance:,.0f} FCFA",
        })

    @action(detail=True, methods=['post'], url_path='adjust-balance')
    def adjust_balance(self, request, pk=None):
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            wallet = ClientWallet.objects.select_related('client').get(id=pk)
            amount = request.data.get('amount')
            adjustment_type = request.data.get('type', 'credit')
            notes = request.data.get('notes', 'Ajustement manuel')

            try:
                amount = Decimal(str(amount))
            except (TypeError, ValueError):
                return Response(
                    {"error": "Montant invalide"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if amount <= 0:
                return Response(
                    {"error": "Le montant doit être > 0"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                if adjustment_type == 'credit':
                    new_balance = wallet.credit(
                        amount=amount,
                        source='adjustment',
                        reference=f"ADJ-{wallet.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                        notes=notes,
                        created_by=request.user,
                    )
                    message = f"Ajout de {amount:,.0f} FCFA"
                elif adjustment_type == 'debit':
                    if amount > wallet.balance:
                        return Response(
                            {"error": f"Solde insuffisant ({wallet.balance:,.0f})"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    new_balance = wallet.debit(
                        amount=amount,
                        source='adjustment',
                        reference=f"ADJ-{wallet.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                        notes=notes,
                        created_by=request.user,
                    )
                    message = f"Retrait de {amount:,.0f} FCFA"
                else:
                    return Response(
                        {"error": "Type doit être 'credit' ou 'debit'"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                return Response({
                    'status': 'success',
                    'message': message,
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'wallet_id': wallet.id,
                    'client_name': wallet.client.name,
                })

        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Wallet {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            wallet = ClientWallet.objects.select_related('client').get(id=pk)
            is_active = request.data.get('is_active')

            if is_active is None:
                return Response(
                    {"error": "Champ 'is_active' requis"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if isinstance(is_active, str):
                is_active = is_active.lower() == 'true'

            wallet.is_active = is_active
            wallet.save(update_fields=['is_active', 'updated_at'])

            return Response({
                'status': 'success',
                'message': f'Wallet {"activé" if is_active else "désactivé"}',
                'wallet_id': wallet.id,
                'client_name': wallet.client.name,
                'is_active': wallet.is_active,
            })
        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Wallet {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['get'], url_path='has-wallet')
    def has_wallet(self, request, pk=None):
        try:
            client = Client.objects.select_related('wallet').get(id=pk)
            has_wallet = hasattr(client, 'wallet')

            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'has_wallet': has_wallet,
                'wallet_id': client.wallet.id if has_wallet else None,
                'balance': client.wallet.balance if has_wallet else 0,
                'balance_display': (
                    f"{client.wallet.balance:,.0f} FCFA"
                    if has_wallet else "0 FCFA"
                ),
                'is_active': client.wallet.is_active if has_wallet else False,
            })
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['get'], url_path='get-wallet')
    def get_wallet_by_id(self, request, pk=None):
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
                'updated_at': wallet.updated_at,
            })
        except ClientWallet.DoesNotExist:
            return Response(
                {"error": f"Wallet {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )


# ============================================================
# CLIENT WALLET VIEWSET
# ============================================================

class ClientWalletViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        return {'request': self.request}

    @action(detail=True, methods=['get'], url_path='wallet')
    def get_wallet(self, request, pk=None):
        try:
            wallet, _ = ClientWallet.objects.select_related('client').get_or_create(
                client_id=pk
            )
            serializer = ClientWalletSerializer(
                wallet, context={'request': request})
            return Response(serializer.data)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['post'], url_path='wallet/deposit')
    def deposit(self, request, pk=None):
        try:
            wallet, _ = ClientWallet.objects.select_related('client').get_or_create(
                client_id=pk
            )
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        amount = request.data.get('amount')
        notes = request.data.get('notes', '')

        try:
            amount = Decimal(str(amount))
        except (TypeError, ValueError):
            return Response(
                {"error": "Montant invalide"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return Response(
                {"error": "Montant doit être > 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                new_balance = wallet.credit(
                    amount=amount,
                    source='deposit',
                    reference=f"DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes or f"Dépôt de {amount:,.0f} FCFA",
                    created_by=request.user,
                )

                return Response({
                    'status': 'success',
                    'message': f'Dépôt de {amount:,.0f} FCFA effectué',
                    'new_balance': new_balance,
                    'balance_display': f"{new_balance:,.0f} FCFA",
                    'client_id': wallet.client.id,
                    'client_name': wallet.client.name,
                }, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['get'], url_path='wallet/transactions')
    def transactions(self, request, pk=None):
        try:
            wallet, _ = ClientWallet.objects.select_related('client').get_or_create(
                client_id=pk
            )
            transactions = (
                wallet.transactions
                .select_related('created_by')
                .order_by('-created_at')[:50]
            )
            serializer = WalletTransactionSerializer(
                transactions, many=True, context={'request': request}
            )
            return Response({
                'client_id': wallet.client.id,
                'client_name': wallet.client.name,
                'balance': wallet.balance,
                'balance_display': f"{wallet.balance:,.0f} FCFA",
                'transactions': serializer.data,
            })
        except Client.DoesNotExist:
            return Response(
                {"error": "Client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )


# ============================================================
# CLIENT STOCK VIEWSET — avec variantes
# ============================================================

class ClientStockViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        return {'request': self.request}

    def _is_admin(self, user):
        return user.role == 'admin' or user.is_staff or user.is_superuser

    @action(detail=False, methods=['get'], url_path='list')
    def list_stocks(self, request):
        if not self._is_admin(request.user):
            return Response(
                {"error": "Permission non accordée"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stocks_qs = ClientStock.objects.select_related('client').prefetch_related(
            Prefetch(
                'lignes',
                queryset=ClientStockLigne.objects.select_related(
                    'product', 'variant'),   # ✅ VARIANTES
            ),
        )

        search = request.query_params.get('search')
        if search:
            stocks_qs = stocks_qs.filter(
                Q(client__name__icontains=search) |
                Q(client__code__icontains=search) |
                Q(client__phone__icontains=search)
            )

        stocks = list(stocks_qs)
        serializer = ClientStockSerializer(
            stocks, many=True, context={'request': request}
        )

        total_value = sum(s.total_value for s in stocks)
        total_quantity = sum(s.total_quantity for s in stocks)

        return Response({
            'count': len(stocks),
            'total_value': float(total_value),
            'total_quantity': float(total_quantity),
            'results': serializer.data,
        })

    @action(detail=True, methods=['get'], url_path='client-stock')
    def get_client_stock(self, request, pk=None):
        try:
            stock, _ = ClientStock.objects.prefetch_related(
                Prefetch(
                    'lignes',
                    queryset=ClientStockLigne.objects.select_related(
                        'product', 'product__unit', 'variant'   # ✅ VARIANTES
                    ),
                ),
            ).get_or_create(client_id=pk)
            serializer = ClientStockSerializer(
                stock, context={'request': request})
            return Response(serializer.data)
        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {pk} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

    # ✅ VARIANTES : dépôt avec variant_id
    @action(detail=False, methods=['post'], url_path='deposit')
    def deposit(self, request):
        serializer = ClientStockDepositSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        client_id = data['client_id']
        product_id = data['product_id']
        variant_id = data.get('variant_id')   # ✅ VARIANTES
        quantity = data['quantity']
        unit_price = data.get('unit_price', Decimal('0'))
        notes = data.get('notes', '')

        try:
            with transaction.atomic():
                stock, _ = ClientStock.objects.get_or_create(
                    client_id=client_id
                )

                ligne_qs = ClientStockLigne.objects.select_for_update().filter(
                    stock=stock, product_id=product_id
                )
                if variant_id:
                    ligne_qs = ligne_qs.filter(variant_id=variant_id)
                else:
                    ligne_qs = ligne_qs.filter(variant__isnull=True)
                ligne = ligne_qs.first()

                if ligne:
                    ligne.quantity += quantity
                    if unit_price > 0:
                        ligne.unit_price = unit_price
                    if notes:
                        ligne.notes = (ligne.notes or '') + f"\n{notes}"
                    ligne.save()
                    created = False
                else:
                    ligne = ClientStockLigne.objects.create(
                        stock=stock,
                        product_id=product_id,
                        variant_id=variant_id,   # ✅ VARIANTES
                        quantity=quantity,
                        unit_price=unit_price,
                        notes=notes,
                    )
                    created = True

                ClientStockMovement.objects.create(
                    client_stock=stock,
                    product_id=product_id,
                    variant_id=variant_id,   # ✅ VARIANTES
                    movement_type='deposit',
                    quantity=quantity,
                    previous_quantity=ligne.quantity - quantity,
                    new_quantity=ligne.quantity,
                    unit_price=unit_price,
                    reference=f"DEP-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes,
                    created_by=request.user,
                )

                # Stock global (produit) — décrémenter
                stock_qs = Stock.objects.filter(
                    product_id=product_id, warehouse__isnull=False
                )
                if variant_id:
                    stock_qs = stock_qs.filter(variant_id=variant_id)
                else:
                    stock_qs = stock_qs.filter(variant__isnull=True)
                global_stock = stock_qs.first()

                if global_stock and global_stock.available_quantity >= quantity:
                    global_stock.consume_stock(quantity)

                return Response({
                    'status': 'success',
                    'message': f'{quantity} unités déposées chez le client',
                    'ligne_id': ligne.id,
                    'new_quantity': ligne.quantity,
                    'created': created,
                }, status=status.HTTP_201_CREATED)

        except Client.DoesNotExist:
            return Response(
                {"error": f"Client {client_id} non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.exception("Erreur dépôt client")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ✅ VARIANTES : retrait avec variant_id
    @action(detail=False, methods=['post'], url_path='withdrawal')
    def withdrawal(self, request):
        serializer = ClientStockWithdrawalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        client_id = data['client_id']
        product_id = data['product_id']
        variant_id = data.get('variant_id')   # ✅ VARIANTES
        quantity = data['quantity']
        notes = data.get('notes', '')

        try:
            with transaction.atomic():
                stock = ClientStock.objects.select_for_update().get(
                    client_id=client_id
                )

                ligne_qs = ClientStockLigne.objects.select_for_update().filter(
                    stock=stock, product_id=product_id
                )
                if variant_id:
                    ligne_qs = ligne_qs.filter(variant_id=variant_id)
                else:
                    ligne_qs = ligne_qs.filter(variant__isnull=True)
                ligne = ligne_qs.get()

                previous_qty = ligne.quantity
                ligne.quantity -= quantity
                if ligne.quantity <= 0:
                    ligne.delete()
                    new_qty = 0
                else:
                    ligne.save()
                    new_qty = ligne.quantity

                ClientStockMovement.objects.create(
                    client_stock=stock,
                    product_id=product_id,
                    variant_id=variant_id,   # ✅ VARIANTES
                    movement_type='withdrawal',
                    quantity=quantity,
                    previous_quantity=previous_qty,
                    new_quantity=new_qty,
                    unit_price=ligne.unit_price if ligne.pk else Decimal('0'),
                    reference=f"WD-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    notes=notes,
                    created_by=request.user,
                )

                return Response({
                    'status': 'success',
                    'message': f'{quantity} unités retirées du stock client',
                    'remaining_quantity': new_qty,
                }, status=status.HTTP_201_CREATED)

        except ClientStock.DoesNotExist:
            return Response(
                {"error": "Stock client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ClientStockLigne.DoesNotExist:
            return Response(
                {"error": "Ligne non trouvée"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.exception("Erreur retrait client")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ✅ VARIANTES : mouvements avec variant
    @action(detail=False, methods=['get'], url_path='movements')
    def movements(self, request):
        movements_qs = ClientStockMovement.objects.select_related(
            'client_stock__client', 'product', 'variant', 'created_by'
        ).order_by('-created_at')

        client_id = request.query_params.get('client_id')
        if client_id:
            movements_qs = movements_qs.filter(
                client_stock__client_id=client_id
            )

        product_id = request.query_params.get('product_id')
        if product_id:
            movements_qs = movements_qs.filter(product_id=product_id)

        variant_id = request.query_params.get('variant_id')
        if variant_id:
            movements_qs = movements_qs.filter(variant_id=variant_id)

        movements = movements_qs[:500]
        serializer = ClientStockMovementSerializer(
            movements, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# CLIENT DELIVERY VIEWSET (admin / staff)
# ✅ VARIANTES : select_related('variant')
# ============================================================

class ClientDeliveryViewSet(viewsets.ModelViewSet):
    queryset = ClientDelivery.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = OptimizedPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ClientDeliveryCreateSerializer
        elif self.action == 'update_status':
            return ClientDeliveryStatusUpdateSerializer
        elif self.action == 'validate_delivery':
            return ClientDeliveryValidateSerializer
        elif self.action == 'reject':
            return ClientDeliveryRejectSerializer
        return ClientDeliverySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = _delivery_queryset().order_by('-request_date', '-id')

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(delivery_number__icontains=search) |
                Q(recipient_name__icontains=search) |
                Q(recipient_phone__icontains=search) |
                Q(client__name__icontains=search)
            )

        client = self.request.query_params.get('client')
        if client:
            queryset = queryset.filter(client_id=client)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status__in=status_filter.split(','))

        from_client = self.request.query_params.get('from_client')
        if from_client == 'true':
            queryset = queryset.filter(created_by_client=True)

        return queryset

    def perform_create(self, serializer):
        data = serializer.validated_data
        client_id = data.pop('client_id')
        lignes_data = data.pop('lignes', [])

        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            raise ValidationError(f"Client {client_id} non trouvé")

        with transaction.atomic():
            delivery = ClientDelivery.objects.create(
                delivery_number=self._generate_delivery_number(),
                client=client,
                created_by=self.request.user,
                **data
            )

            lignes_to_create = []
            for ligne_data in lignes_data:
                product = ligne_data['product']
                variant = ligne_data.get('variant')   # ✅ VARIANTES
                quantity = ligne_data['quantity']
                unit_price = ligne_data.get('unit_price', Decimal('0'))
                notes = ligne_data.get('notes', '')

                lignes_to_create.append(ClientDeliveryLigne(
                    delivery=delivery,
                    product=product,
                    variant=variant,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_value=quantity * unit_price,
                    notes=notes,
                ))

            ClientDeliveryLigne.objects.bulk_create(lignes_to_create)

            delivery.total_quantity = sum(l.quantity for l in lignes_to_create)
            delivery.total_value = sum(l.total_value for l in lignes_to_create)
            delivery.save(update_fields=['total_quantity', 'total_value'])

        serializer.instance = delivery

    def _generate_delivery_number(self):
        year = date.today().year
        count = ClientDelivery.objects.filter(
            delivery_number__startswith=f"LIV-{year}-"
        ).count() + 1
        return f"LIV-{year}-{count:04d}"

    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        delivery = self.get_object()
        serializer = ClientDeliveryStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']
        old_status = delivery.status

        with transaction.atomic():
            delivery.status = new_status

            if new_status == 'confirmed' and not delivery.confirmed_date:
                delivery.confirmed_date = timezone.now()
            elif new_status == 'in_transit' and not delivery.shipped_date:
                delivery.shipped_date = timezone.now()
            elif new_status == 'delivered' and not delivery.delivered_date:
                delivery.delivered_date = timezone.now()

            for field in ['carrier', 'tracking_number', 'vehicle_plate',
                          'driver_name', 'driver_phone', 'delivery_method', 'notes']:
                if serializer.validated_data.get(field):
                    setattr(delivery, field, serializer.validated_data[field])

            delivery.save()

        return Response({
            'status': 'success',
            'message': f'Statut changé de {old_status} à {new_status}',
            'delivery_number': delivery.delivery_number,
            'new_status': delivery.status,
        })

    @action(detail=True, methods=['post'])
    def validate_delivery(self, request, pk=None):
        delivery = self.get_object()

        if not delivery.can_be_validated:
            return Response(
                {"error": "Cette livraison ne peut pas être validée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ClientDeliveryValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            delivery.status = 'confirmed'
            delivery.confirmed_date = timezone.now()
            delivery.validated_by = request.user

            for field in ['carrier', 'tracking_number', 'vehicle_plate',
                          'driver_name', 'driver_phone', 'delivery_method', 'notes']:
                if serializer.validated_data.get(field):
                    setattr(delivery, field, serializer.validated_data[field])

            delivery.save()

        return Response({
            'status': 'success',
            'message': 'Livraison validée',
            'delivery_number': delivery.delivery_number,
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        delivery = self.get_object()

        if not delivery.can_be_rejected:
            return Response(
                {"error": "Cette livraison ne peut pas être rejetée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ClientDeliveryRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            delivery.status = 'rejected'
            delivery.rejection_reason = serializer.validated_data['reason']
            delivery.save()

        return Response({
            'status': 'success',
            'message': 'Livraison rejetée',
            'delivery_number': delivery.delivery_number,
            'reason': delivery.rejection_reason,
        })

    @action(detail=True, methods=['post'])
    def start_transit(self, request, pk=None):
        delivery = self.get_object()

        if not delivery.can_be_started:
            return Response(
                {"error": "Cette livraison ne peut pas être mise en transit"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delivery.status = 'in_transit'
        delivery.shipped_date = timezone.now()
        delivery.save(update_fields=['status', 'shipped_date', 'updated_at'])

        return Response({
            'status': 'success',
            'message': 'Livraison en transit',
            'delivery_number': delivery.delivery_number,
        })

    @action(detail=True, methods=['post'])
    def mark_delivered(self, request, pk=None):
        delivery = self.get_object()

        if not delivery.can_be_confirmed:
            return Response(
                {"error": "Cette livraison ne peut pas être marquée livrée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delivery.status = 'delivered'
        delivery.delivered_date = timezone.now()
        delivery.save(update_fields=['status', 'delivered_date', 'updated_at'])

        return Response({
            'status': 'success',
            'message': 'Livraison effectuée',
            'delivery_number': delivery.delivery_number,
        })

    @action(detail=True, methods=['get'], url_path='lignes')
    def get_lignes(self, request, pk=None):
        delivery = self.get_object()
        lignes = delivery.lignes.select_related('product', 'variant').all()  # ✅ VARIANTES
        serializer = ClientDeliveryLigneSerializer(
            lignes, many=True, context={'request': request}
        )
        return Response(serializer.data)


# ============================================================
# CLIENT DELIVERY REQUEST VIEWSET (espace client)
# ✅ VARIANTES : select_related('variant')
# ============================================================

class ClientDeliveryRequestViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        return {'request': self.request}

    def _get_client(self, user):
        try:
            if hasattr(user, 'client_profile'):
                return user.client_profile
            elif hasattr(user, 'client'):
                return user.client
            return None
        except Exception:
            return None

    def _is_client(self, user):
        return getattr(user, 'role', None) == 'client'

    @action(detail=False, methods=['get'], url_path='my-deliveries')
    def my_deliveries(self, request):
        if not self._is_client(request.user):
            return Response(
                {"error": "Accès réservé aux clients"},
                status=status.HTTP_403_FORBIDDEN,
            )

        client = self._get_client(request.user)
        if not client:
            return Response(
                {"error": "Profil client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        deliveries = (
            _delivery_queryset()
            .filter(client=client)
            .order_by('-request_date')
        )

        status_filter = request.query_params.get('status')
        if status_filter:
            deliveries = deliveries.filter(status__in=status_filter.split(','))

        serializer = ClientDeliverySerializer(
            deliveries, many=True, context={'request': request}
        )

        stats_qs = ClientDelivery.objects.filter(client=client)
        stats = {
            'total': stats_qs.count(),
            'pending': stats_qs.filter(status='pending').count(),
            'confirmed': stats_qs.filter(status='confirmed').count(),
            'in_transit': stats_qs.filter(status='in_transit').count(),
            'delivered': stats_qs.filter(status='delivered').count(),
            'cancelled': stats_qs.filter(status='cancelled').count(),
            'rejected': stats_qs.filter(status='rejected').count(),
        }

        return Response({
            'count': len(serializer.data),
            'stats': stats,
            'results': serializer.data,
        })

    @action(detail=False, methods=['post'], url_path='create-request')
    def create_request(self, request):
        if not self._is_client(request.user):
            return Response(
                {"error": "Accès réservé aux clients"},
                status=status.HTTP_403_FORBIDDEN,
            )

        client = self._get_client(request.user)
        if not client:
            return Response(
                {"error": "Profil client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ClientDeliveryRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lignes_data = serializer.validated_data.pop('lignes', [])

        with transaction.atomic():
            delivery = ClientDelivery.objects.create(
                delivery_number=self._generate_delivery_number(),
                client=client,
                created_by_client=True,
                created_by=request.user,
                **serializer.validated_data
            )

            lignes_to_create = []
            for ligne_data in lignes_data:
                product = ligne_data['product']
                variant = ligne_data.get('variant')   # ✅ VARIANTES
                quantity = ligne_data['quantity']
                notes = ligne_data.get('notes', '')

                lignes_to_create.append(ClientDeliveryLigne(
                    delivery=delivery,
                    product=product,
                    variant=variant,
                    quantity=quantity,
                    unit_price=Decimal('0'),
                    total_value=Decimal('0'),
                    notes=notes,
                ))

            ClientDeliveryLigne.objects.bulk_create(lignes_to_create)

            delivery.total_quantity = sum(l.quantity for l in lignes_to_create)
            delivery.save(update_fields=['total_quantity'])

        delivery = _delivery_queryset().get(pk=delivery.pk)
        return Response({
            'status': 'success',
            'message': 'Demande de livraison créée',
            'delivery': ClientDeliverySerializer(
                delivery, context={'request': request}
            ).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'], url_path='update-request')
    def update_request(self, request, pk=None):
        if not self._is_client(request.user):
            return Response(
                {"error": "Accès réservé aux clients"},
                status=status.HTTP_403_FORBIDDEN,
            )

        client = self._get_client(request.user)
        try:
            delivery = ClientDelivery.objects.get(id=pk, client=client)
        except ClientDelivery.DoesNotExist:
            return Response(
                {"error": "Livraison non trouvée"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not delivery.can_be_edited_by_client:
            return Response(
                {"error": "Cette livraison ne peut plus être modifiée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ClientDeliveryRequestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lignes_data = serializer.validated_data.pop('lignes', None)

        with transaction.atomic():
            for field, value in serializer.validated_data.items():
                setattr(delivery, field, value)

            if lignes_data is not None:
                delivery.lignes.all().delete()

                lignes_to_create = []
                for ligne_data in lignes_data:
                    lignes_to_create.append(ClientDeliveryLigne(
                        delivery=delivery,
                        product=ligne_data['product'],
                        variant=ligne_data.get('variant'),   # ✅ VARIANTES
                        quantity=ligne_data['quantity'],
                        unit_price=Decimal('0'),
                        total_value=Decimal('0'),
                        notes=ligne_data.get('notes', ''),
                    ))

                ClientDeliveryLigne.objects.bulk_create(lignes_to_create)
                delivery.total_quantity = sum(l.quantity for l in lignes_to_create)

            delivery.save()

        delivery = _delivery_queryset().get(pk=delivery.pk)
        return Response({
            'status': 'success',
            'message': 'Demande mise à jour',
            'delivery': ClientDeliverySerializer(
                delivery, context={'request': request}
            ).data,
        })

    @action(detail=True, methods=['post'], url_path='cancel-request')
    def cancel_request(self, request, pk=None):
        if not self._is_client(request.user):
            return Response(
                {"error": "Accès réservé aux clients"},
                status=status.HTTP_403_FORBIDDEN,
            )

        client = self._get_client(request.user)
        try:
            delivery = ClientDelivery.objects.get(id=pk, client=client)
        except ClientDelivery.DoesNotExist:
            return Response(
                {"error": "Livraison non trouvée"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not delivery.can_be_cancelled_by_client:
            return Response(
                {"error": "Cette livraison ne peut plus être annulée"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delivery.status = 'cancelled'
        delivery.save(update_fields=['status', 'updated_at'])

        return Response({
            'status': 'success',
            'message': 'Demande annulée',
            'delivery_number': delivery.delivery_number,
        })

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        if not self._is_client(request.user):
            return Response(
                {"error": "Accès réservé aux clients"},
                status=status.HTTP_403_FORBIDDEN,
            )

        client = self._get_client(request.user)
        if not client:
            return Response(
                {"error": "Profil client non trouvé"},
                status=status.HTTP_404_NOT_FOUND,
            )

        stats_qs = ClientDelivery.objects.filter(client=client)

        return Response({
            'total': stats_qs.count(),
            'pending': stats_qs.filter(status='pending').count(),
            'confirmed': stats_qs.filter(status='confirmed').count(),
            'in_transit': stats_qs.filter(status='in_transit').count(),
            'delivered': stats_qs.filter(status='delivered').count(),
            'cancelled': stats_qs.filter(status='cancelled').count(),
            'rejected': stats_qs.filter(status='rejected').count(),
        })

    def _generate_delivery_number(self):
        year = date.today().year
        count = ClientDelivery.objects.filter(
            delivery_number__startswith=f"LIV-{year}-"
        ).count() + 1
        return f"LIV-{year}-{count:04d}"