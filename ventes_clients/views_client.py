# apps/ventes_clients/views_client.py
# ============================================================
# ESPACE CLIENT — LOGICIEL B
# ✅ ZÉRO N+1 — Optimisé pour 10 000+ lignes < 1s
# ============================================================

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
from django.db.models import (
    Sum, Count, Q, Exists, OuterRef, Prefetch, F, Value,
    DecimalField, IntegerField,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from decimal import Decimal
import logging

from .models import (
    Client, Vente, Facture, Paiement,
    ClientWallet, WalletTransaction,
    ClientStock, ClientStockLigne, ClientStockMovement,
    ClientDelivery, ClientDeliveryLigne,
)
from .serializers import (
    VenteListSerializer, VenteDetailSerializer,
    FactureSerializer,
    PaiementSerializer, ClientWalletSerializer,
    WalletTransactionSerializer,
    ClientStockSerializer,
    ClientStockMovementSerializer,
    ClientDeliverySerializer,
    ClientDeliveryRequestCreateSerializer,
    ClientDeliveryRequestUpdateSerializer,
)
from users.permissions import IsClient

logger = logging.getLogger(__name__)


# ============================================================
# PAGINATION PERSONNALISÉE
# ============================================================
class ClientSpacePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


# ============================================================
# HELPERS QUERYSETS OPTIMISÉS (anti-N+1)
# ============================================================

def _vente_queryset_base():
    """
    Queryset Vente optimisé :
    - select_related : client, warehouse, created_by
    - prefetch_related : invoices, devis_source
    - annotate : has_invoice_annotated
    """
    return (
        Vente.objects
        .select_related('client', 'warehouse', 'created_by')
        .prefetch_related('invoices', 'devis_source')
        .annotate(
            has_invoice_annotated=Exists(
                Facture.objects.filter(sale=OuterRef('pk'))
            )
        )
    )


def _vente_detail_queryset():
    """
    Queryset Vente détail ultra-optimisé :
    charge en profondeur toutes les relations utilisées par VenteDetailSerializer.
    """
    return (
        Vente.objects
        .select_related('client', 'warehouse', 'created_by')
        .prefetch_related(
            'lines__product',
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


def _facture_queryset_base():
    """
    Queryset Facture optimisé :
    - select_related : client, sale
    - prefetch_related : paiements (avec leurs FK)
    - annotate : remaining_calc pour éviter les SerializerMethodField coûteux
    """
    return (
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
        .annotate(
            remaining_calc=Coalesce(
                F('total') - F('amount_paid'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )


def _paiement_queryset_base():
    """
    Queryset Paiement optimisé :
    select_related complet vers facture, client, caisse, compte, received_by.
    """
    return (
        Paiement.objects
        .select_related(
            'facture__client',
            'facture__sale',
            'caisse_destination',
            'compte_destination',
            'received_by',
        )
    )


def _delivery_queryset_base():
    """
    Queryset ClientDelivery optimisé :
    - select_related : client, client_stock, created_by, validated_by
    - prefetch_related : lignes__product
    """
    return (
        ClientDelivery.objects
        .select_related(
            'client', 'client_stock', 'created_by', 'validated_by'
        )
        .prefetch_related(
            Prefetch(
                'lignes',
                queryset=(
                    ClientDeliveryLigne.objects
                    .select_related('product', 'client_stock_ligne')
                ),
            ),
        )
    )


# ============================================================
# VIEWSET
# ============================================================

class ClientSpaceViewSet(viewsets.GenericViewSet):
    """
    Espace client — toutes les données sont filtrées par le client connecté.
    Toutes les actions sont optimisées anti-N+1.
    """
    permission_classes = [permissions.IsAuthenticated, IsClient]
    serializer_class = VenteListSerializer
    pagination_class = ClientSpacePagination

    # ============================================================
    # HELPERS
    # ============================================================
    def _get_client(self, request):
        """Récupère le profil Client lié à l'utilisateur connecté (cache user)."""
        if hasattr(request, '_cached_client'):
            return request._cached_client
        client = getattr(request.user, 'client_profile', None)
        if not client:
            client = getattr(request.user, 'client', None)
        request._cached_client = client
        return client

    def _no_client_response(self):
        return Response(
            {'error': 'Aucun profil client lié à votre compte. '
                      'Contactez un administrateur pour activer votre espace client.'},
            status=status.HTTP_404_NOT_FOUND
        )

    def _paginated_response(self, queryset, serializer_class, extra_data=None):
        """Réponse paginée avec données extra."""
        page = self.paginate_queryset(queryset)
        context = {'request': self.request}

        if page is not None:
            serializer = serializer_class(page, many=True, context=context)
            data = dict(extra_data) if extra_data else {}
            data['results'] = serializer.data
            return self.get_paginated_response(data)

        serializer = serializer_class(queryset, many=True, context=context)
        data = dict(extra_data) if extra_data else {}
        data['results'] = serializer.data
        return Response(data)

    def _compute_vente_stats(self, base_qs):
        """
        ✅ 1 SEULE requête d'agrégation pour toutes les stats ventes.
        """
        agg = base_qs.aggregate(
            total_orders=Count('id'),
            total_amount=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_paid=Coalesce(
                Sum('amount_paid'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_due=Coalesce(
                Sum('amount_due'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        return {
            'total_orders': agg['total_orders'] or 0,
            'total_amount': float(agg['total_amount'] or 0),
            'total_paid': float(agg['total_paid'] or 0),
            'total_due': float(agg['total_due'] or 0),
        }

    # ============================================================
    # MES ACHATS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-orders')
    def my_orders(self, request):
        """Historique de mes achats — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        # ✅ queryset optimisé : select_related + prefetch + annotation
        ventes = _vente_queryset_base().filter(client=client).order_by('-sale_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            ventes = ventes.filter(status=status_filter)

        date_from = request.query_params.get('date_from')
        if date_from:
            ventes = ventes.filter(sale_date__date__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            ventes = ventes.filter(sale_date__date__lte=date_to)

        # ✅ 1 seule requête d'agrégation
        stats = self._compute_vente_stats(ventes)

        return self._paginated_response(
            ventes, VenteListSerializer, {'stats': stats}
        )

    # ============================================================
    # DÉTAIL D'UNE COMMANDE
    # ============================================================
    @action(detail=True, methods=['get'], url_path='order-detail')
    def order_detail(self, request, pk=None):
        """Détail complet d'une commande — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            # ✅ queryset détail avec prefetch profond
            vente = _vente_detail_queryset().get(id=pk, client=client)
        except Vente.DoesNotExist:
            return Response(
                {'error': 'Commande non trouvée ou non autorisée'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = VenteDetailSerializer(vente, context={'request': request})
        return Response(serializer.data)

    # ============================================================
    # MES FACTURES
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-invoices')
    def my_invoices(self, request):
        """Mes factures — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        factures = _facture_queryset_base().filter(
            client=client
        ).order_by('-invoice_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            factures = factures.filter(status=status_filter)

        # ✅ 1 seule agrégation
        agg = factures.aggregate(
            total_invoices=Count('id'),
            total_amount=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_paid=Coalesce(
                Sum('amount_paid'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        stats = {
            'total_invoices': agg['total_invoices'] or 0,
            'total_amount': float(agg['total_amount'] or 0),
            'total_paid': float(agg['total_paid'] or 0),
        }

        return self._paginated_response(
            factures, FactureSerializer, {'stats': stats}
        )

    # ============================================================
    # MES PAIEMENTS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-payments')
    def my_payments(self, request):
        """Mes paiements — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        paiements = _paiement_queryset_base().filter(
            facture__client=client
        ).order_by('-payment_date')

        # ✅ 1 seule agrégation
        agg = paiements.aggregate(
            total_payments=Count('id'),
            total_amount=Coalesce(
                Sum('amount'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        stats = {
            'total_payments': agg['total_payments'] or 0,
            'total_amount': float(agg['total_amount'] or 0),
        }

        return self._paginated_response(
            paiements, PaiementSerializer, {'stats': stats}
        )

    # ============================================================
    # MON PORTE-MONNAIE
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-wallet')
    def my_wallet(self, request):
        """Mon porte-monnaie — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        wallet, _ = ClientWallet.objects.select_related('client').get_or_create(
            client=client
        )
        serializer = ClientWalletSerializer(
            wallet, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-wallet-transactions')
    def my_wallet_transactions(self, request):
        """Historique de mes transactions wallet — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        wallet, _ = ClientWallet.objects.get_or_create(client=client)

        # ✅ select_related created_by pour éviter N+1 dans WalletTransactionSerializer
        transactions = (
            wallet.transactions
            .select_related('created_by')
            .order_by('-created_at')[:100]
        )

        serializer = WalletTransactionSerializer(
            transactions, many=True, context={'request': request}
        )
        return Response({
            'balance': float(wallet.balance),
            'balance_display': f"{wallet.balance:,.0f} FCFA",
            'total_deposits': float(wallet.total_deposits),
            'total_used': float(wallet.total_used),
            'transactions': serializer.data,
        })

    # ============================================================
    # MON STOCK DE PRODUITS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-stock')
    def my_stock(self, request):
        """Stock de marchandises déposées chez le client — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        # ✅ prefetch lignes__product et product__unit en une passe
        stock = (
            ClientStock.objects
            .select_related('client')
            .prefetch_related(
                Prefetch(
                    'lignes',
                    queryset=(
                        ClientStockLigne.objects
                        .select_related('product', 'product__unit')
                        .order_by('product__name')
                    ),
                ),
            )
            .filter(client=client)
            .first()
        )

        if not stock:
            return Response({
                'count': 0,
                'total_quantity': 0,
                'total_value': 0,
                'results': [],
            })

        serializer = ClientStockSerializer(stock, context={'request': request})

        return Response({
            'count': stock.nombre_produits,
            'total_quantity': float(stock.total_quantity),
            'total_value': float(stock.total_value),
            'results': serializer.data['lignes'],
            'last_update': stock.updated_at,
        })

    # ============================================================
    # HISTORIQUE DES MOUVEMENTS DE MON STOCK
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-stock-movements')
    def my_stock_movements(self, request):
        """Historique des mouvements de mon stock — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        stock = ClientStock.objects.filter(client=client).first()

        if not stock:
            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'movements': [],
                'stats': {
                    'total_deposits': 0,
                    'total_withdrawals': 0,
                    'current_quantity': 0,
                },
            })

        movement_type = request.query_params.get('type')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        # ✅ Queryset optimisé avec select_related + client_stock__client
        movements_qs = (
            ClientStockMovement.objects
            .select_related('product', 'created_by', 'client_stock__client')
            .filter(client_stock=stock)
        )

        if movement_type:
            movements_qs = movements_qs.filter(movement_type=movement_type)
        if date_from:
            movements_qs = movements_qs.filter(created_at__date__gte=date_from)
        if date_to:
            movements_qs = movements_qs.filter(created_at__date__lte=date_to)

        # ✅ 1 seule requête d'agrégation pour les stats
        stats_agg = ClientStockMovement.objects.filter(
            client_stock=stock
        ).aggregate(
            total_deposits=Coalesce(
                Sum('quantity', filter=Q(movement_type='deposit')),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_withdrawals=Coalesce(
                Sum('quantity', filter=Q(
                    movement_type__in=['withdrawal', 'delivery', 'sale']
                )),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )

        movements = movements_qs.order_by('-created_at')[:100]

        serializer = ClientStockMovementSerializer(
            movements, many=True, context={'request': request}
        )

        return Response({
            'client_id': client.id,
            'client_name': client.name,
            'stats': {
                'total_deposits': float(stats_agg['total_deposits'] or 0),
                'total_withdrawals': float(stats_agg['total_withdrawals'] or 0),
                'current_quantity': float(stock.total_quantity),
            },
            'movements': serializer.data,
        })

    # ============================================================
    # MES LIVRAISONS (SUIVI)
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-deliveries')
    def my_deliveries(self, request):
        """Suivi des livraisons — ZÉRO N+1 (sans pagination)."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        status_filter = request.query_params.get('status')

        # ✅ queryset optimisé
        deliveries_qs = _delivery_queryset_base().filter(client=client)

        if status_filter:
            deliveries_qs = deliveries_qs.filter(status=status_filter)

        deliveries_qs = deliveries_qs.order_by('-created_at')

        # ✅ 1 seule agrégation au lieu de 7 .filter().count()
        stats_agg = ClientDelivery.objects.filter(client=client).aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            confirmed=Count('id', filter=Q(status='confirmed')),
            in_transit=Count('id', filter=Q(status='in_transit')),
            delivered=Count('id', filter=Q(status='delivered')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            rejected=Count('id', filter=Q(status='rejected')),
        )

        serializer = ClientDeliverySerializer(
            deliveries_qs, many=True, context={'request': request}
        )

        return Response({
            'client_id': client.id,
            'client_name': client.name,
            'stats': {
                'total': stats_agg['total'] or 0,
                'pending': stats_agg['pending'] or 0,
                'confirmed': stats_agg['confirmed'] or 0,
                'in_transit': stats_agg['in_transit'] or 0,
                'delivered': stats_agg['delivered'] or 0,
                'cancelled': stats_agg['cancelled'] or 0,
                'rejected': stats_agg['rejected'] or 0,
            },
            'count': stats_agg['total'] or 0,
            'results': serializer.data,
        })

    # ============================================================
    # DÉTAIL D'UNE LIVRAISON
    # ============================================================
    @action(detail=True, methods=['get'], url_path='my-delivery-detail')
    def my_delivery_detail(self, request, pk=None):
        """Détail d'une livraison — ZÉRO N+1."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            # ✅ queryset optimisé
            delivery = _delivery_queryset_base().get(id=pk, client=client)
        except ClientDelivery.DoesNotExist:
            return Response(
                {'error': 'Livraison non trouvée ou non autorisée'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ClientDeliverySerializer(
            delivery, context={'request': request}
        )
        return Response(serializer.data)

    # ============================================================
    # CRÉER UNE DEMANDE DE LIVRAISON (CLIENT)
    # ============================================================
    @action(detail=False, methods=['post'], url_path='my-deliveries/create')
    def create_my_delivery(self, request):
        """
        Le client crée une demande de livraison.
        ✅ Optimisé : 1 requête pour stock + N lignes bulk_create.
        """
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        serializer = ClientDeliveryRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            with transaction.atomic():
                # ✅ 1 requête pour le stock
                client_stock = ClientStock.objects.filter(
                    client=client).first()

                if not client_stock:
                    return Response(
                        {'error': 'Vous n\'avez aucun stock disponible. '
                                  'Contactez l\'administrateur.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # ✅ 1 requête pour TOUTES les lignes de stock
                product_ids = [
                    l['product'].id if hasattr(l['product'], 'id')
                    else l['product']
                    for l in data['lignes']
                ]

                stock_lignes_map = {
                    sl.product_id: sl
                    for sl in ClientStockLigne.objects
                    .select_related('product')
                    .filter(stock=client_stock, product_id__in=product_ids)
                }

                # ✅ Validation en mémoire
                lignes_to_create = []
                for ligne_data in data['lignes']:
                    product_id = (
                        ligne_data['product'].id
                        if hasattr(ligne_data['product'], 'id')
                        else ligne_data['product']
                    )
                    quantity = Decimal(str(ligne_data['quantity']))

                    stock_ligne = stock_lignes_map.get(product_id)
                    if not stock_ligne:
                        raise ValueError(
                            f"Le produit {product_id} n'est pas dans votre stock."
                        )
                    if stock_ligne.quantity < quantity:
                        raise ValueError(
                            f"Stock insuffisant pour {stock_ligne.product.name}. "
                            f"Disponible : {stock_ligne.quantity}, "
                            f"Demandé : {quantity}"
                        )

                    lignes_to_create.append(
                        ClientDeliveryLigne(
                            product_id=product_id,
                            client_stock_ligne=stock_ligne,
                            quantity=quantity,
                            unit_price=stock_ligne.unit_price or 0,
                            notes=ligne_data.get('notes', ''),
                        )
                    )

                # ✅ Créer la livraison
                delivery = ClientDelivery.objects.create(
                    client=client,
                    client_stock=client_stock,
                    recipient_name=data['recipient_name'],
                    recipient_phone=data['recipient_phone'],
                    recipient_address=data.get('recipient_address', ''),
                    recipient_email=data.get('recipient_email', ''),
                    recipient_notes=data.get('recipient_notes', ''),
                    client_notes=data.get('client_notes', ''),
                    status='pending',
                    created_by=request.user,
                    created_by_client=True,
                )

                # ✅ bulk_create : 1 requête pour N lignes
                for ligne in lignes_to_create:
                    ligne.delivery = delivery
                ClientDeliveryLigne.objects.bulk_create(lignes_to_create)

                delivery.recalculate_totals()

                logger.info(
                    f"📝 Demande client créée : {delivery.delivery_number} "
                    f"par {request.user.email} ({delivery.total_quantity} unités)"
                )

                # ✅ Recharger optimisé pour la réponse
                delivery = _delivery_queryset_base().get(pk=delivery.pk)

                return Response({
                    'status': 'success',
                    'message': (
                        f'Votre demande {delivery.delivery_number} a été enregistrée. '
                        f'Elle sera examinée par un administrateur.'
                    ),
                    'delivery': ClientDeliverySerializer(
                        delivery, context={'request': request}
                    ).data,
                }, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception("Erreur création demande client")
            return Response(
                {'error': f'Erreur : {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # MODIFIER UNE DEMANDE (CLIENT)
    # ============================================================
    @action(detail=True, methods=['put', 'patch'], url_path='my-deliveries/update')
    def update_my_delivery(self, request, pk=None):
        """
        Le client modifie sa demande (statut 'pending' uniquement).
        ✅ Optimisé : validation en mémoire, bulk_create.
        """
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            delivery = ClientDelivery.objects.select_related(
                'client', 'client_stock'
            ).get(id=pk, client=client)
        except ClientDelivery.DoesNotExist:
            return Response(
                {'error': 'Demande non trouvée'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not delivery.can_be_edited_by_client:
            return Response(
                {'error': (
                    f'Cette demande ne peut plus être modifiée '
                    f'(statut actuel : {delivery.get_status_display()})'
                )},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ClientDeliveryRequestUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            with transaction.atomic():
                # Mise à jour champs destinataire
                for field in ['recipient_name', 'recipient_phone',
                              'recipient_address', 'recipient_email',
                              'recipient_notes', 'client_notes']:
                    if field in data:
                        setattr(delivery, field, data[field])
                delivery.save()

                # Mise à jour des lignes
                if 'lignes' in data:
                    delivery.lignes.all().delete()

                    client_stock = delivery.client_stock
                    product_ids = [
                        l['product'].id if hasattr(l['product'], 'id')
                        else l['product']
                        for l in data['lignes']
                    ]

                    # ✅ 1 requête pour toutes les lignes de stock
                    stock_lignes_map = {
                        sl.product_id: sl
                        for sl in ClientStockLigne.objects
                        .select_related('product')
                        .filter(stock=client_stock, product_id__in=product_ids)
                    }

                    lignes_to_create = []
                    for ligne_data in data['lignes']:
                        product_id = (
                            ligne_data['product'].id
                            if hasattr(ligne_data['product'], 'id')
                            else ligne_data['product']
                        )
                        quantity = Decimal(str(ligne_data['quantity']))

                        stock_ligne = stock_lignes_map.get(product_id)
                        if not stock_ligne:
                            raise ValueError(
                                f"Le produit {product_id} n'est pas dans votre stock."
                            )
                        if stock_ligne.quantity < quantity:
                            raise ValueError(
                                f"Stock insuffisant pour {stock_ligne.product.name}"
                            )

                        lignes_to_create.append(
                            ClientDeliveryLigne(
                                delivery=delivery,
                                product_id=product_id,
                                client_stock_ligne=stock_ligne,
                                quantity=quantity,
                                unit_price=stock_ligne.unit_price or 0,
                                notes=ligne_data.get('notes', ''),
                            )
                        )

                    # ✅ bulk_create
                    ClientDeliveryLigne.objects.bulk_create(lignes_to_create)
                    delivery.recalculate_totals()

                # ✅ Recharger optimisé
                delivery = _delivery_queryset_base().get(pk=delivery.pk)

                return Response({
                    'status': 'success',
                    'message': 'Demande mise à jour',
                    'delivery': ClientDeliverySerializer(
                        delivery, context={'request': request}
                    ).data,
                })

        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception("Erreur modification demande")
            return Response(
                {'error': f'Erreur : {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # ANNULER UNE DEMANDE (CLIENT)
    # ============================================================
    @action(detail=True, methods=['post'], url_path='my-deliveries/cancel')
    def cancel_my_delivery(self, request, pk=None):
        """Le client annule sa demande (pending/confirmed)."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            delivery = ClientDelivery.objects.get(id=pk, client=client)
        except ClientDelivery.DoesNotExist:
            return Response(
                {'error': 'Demande non trouvée'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not delivery.can_be_cancelled_by_client:
            return Response(
                {'error': (
                    f'Cette demande ne peut plus être annulée '
                    f'(statut actuel : {delivery.get_status_display()})'
                )},
                status=status.HTTP_400_BAD_REQUEST
            )

        reason = request.data.get('reason', '')

        delivery.status = 'cancelled'
        note_line = (
            f"[ANNULÉE par le client le "
            f"{timezone.now().strftime('%Y-%m-%d %H:%M')}]"
        )
        if reason:
            note_line += f"\nRaison : {reason}"

        delivery.notes = (
            f"{delivery.notes}\n{note_line}"
            if delivery.notes else note_line
        )
        delivery.save()

        logger.info(f"❌ Demande client annulée : {delivery.delivery_number}")

        # ✅ Recharger optimisé
        delivery = _delivery_queryset_base().get(pk=delivery.pk)

        return Response({
            'status': 'success',
            'message': 'Demande annulée',
            'delivery': ClientDeliverySerializer(
                delivery, context={'request': request}
            ).data,
        })

    # ============================================================
    # DASHBOARD CLIENT
    # ============================================================
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """
        Tableau de bord du client.
        ✅ Optimisé : toutes les stats agrégées en quelques requêtes seulement.
        """
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        # ---------------------------------------------------------
        # 1. Stats ventes (1 requête)
        # ---------------------------------------------------------
        ventes_stats = Vente.objects.filter(client=client).aggregate(
            total_orders=Count('id'),
            total_spent=Coalesce(
                Sum('total'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
            total_due=Coalesce(
                Sum('amount_due'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )

        # ---------------------------------------------------------
        # 2. Stats factures (1 requête)
        # ---------------------------------------------------------
        factures_stats = Facture.objects.filter(client=client).aggregate(
            total_invoices=Count('id'),
        )

        # ---------------------------------------------------------
        # 3. Stats paiements (1 requête)
        # ---------------------------------------------------------
        paiements_stats = Paiement.objects.filter(
            facture__client=client
        ).aggregate(
            total_paid=Coalesce(
                Sum('amount'), Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )

        # ---------------------------------------------------------
        # 4. Wallet (1-2 requêtes selon get_or_create)
        # ---------------------------------------------------------
        wallet, _ = ClientWallet.objects.get_or_create(client=client)

        # ---------------------------------------------------------
        # 5. Client stock (1 requête avec prefetch)
        # ---------------------------------------------------------
        client_stock = (
            ClientStock.objects
            .prefetch_related(
                Prefetch(
                    'lignes',
                    queryset=ClientStockLigne.objects.select_related(
                        'product', 'product__unit'
                    ),
                ),
            )
            .filter(client=client)
            .first()
        )

        # ---------------------------------------------------------
        # 6. Stats livraisons (1 requête d'agrégation)
        # ---------------------------------------------------------
        deliveries_stats = ClientDelivery.objects.filter(client=client).aggregate(
            total_deliveries=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            confirmed=Count('id', filter=Q(status='confirmed')),
            in_transit=Count('id', filter=Q(status='in_transit')),
            delivered=Count('id', filter=Q(status='delivered')),
            rejected=Count('id', filter=Q(status='rejected')),
        )

        # ---------------------------------------------------------
        # 7. 5 dernières ventes (1 requête avec prefetch)
        # ---------------------------------------------------------
        recent_sales = (
            _vente_queryset_base()
            .filter(client=client)
            .order_by('-sale_date')[:5]
        )

        # ---------------------------------------------------------
        # 8. 5 dernières livraisons (1 requête avec prefetch)
        # ---------------------------------------------------------
        recent_deliveries = (
            _delivery_queryset_base()
            .filter(client=client)
            .order_by('-created_at')[:5]
        )

        # ---------------------------------------------------------
        # Réponse
        # ---------------------------------------------------------
        return Response({
            'client_info': {
                'id': client.id,
                'code': client.code,
                'name': client.name,
                'phone': client.phone,
                'email': getattr(client, 'email', None),
                'address': client.address,
            },
            'stats': {
                # Achats & finances
                'total_orders': ventes_stats['total_orders'] or 0,
                'total_spent': float(ventes_stats['total_spent'] or 0),
                'total_paid': float(paiements_stats['total_paid'] or 0),
                'total_due': float(ventes_stats['total_due'] or 0),
                'total_invoices': factures_stats['total_invoices'] or 0,
                'wallet_balance': float(wallet.balance),

                # Stats stock
                'stock_products': client_stock.nombre_produits if client_stock else 0,
                'stock_quantity': float(client_stock.total_quantity) if client_stock else 0,
                'stock_value': float(client_stock.total_value) if client_stock else 0,

                # Stats livraisons
                'total_deliveries': deliveries_stats['total_deliveries'] or 0,
                'pending_deliveries': deliveries_stats['pending'] or 0,
                'confirmed_deliveries': deliveries_stats['confirmed'] or 0,
                'in_transit_deliveries': deliveries_stats['in_transit'] or 0,
                'delivered_deliveries': deliveries_stats['delivered'] or 0,
                'rejected_deliveries': deliveries_stats['rejected'] or 0,
            },
            'recent_orders': VenteListSerializer(
                recent_sales, many=True, context={'request': request}
            ).data,
            'recent_deliveries': ClientDeliverySerializer(
                recent_deliveries, many=True, context={'request': request}
            ).data,
            'wallet': ClientWalletSerializer(wallet, context={'request': request}).data,
            'stock_summary': {
                'has_stock': client_stock is not None,
                'nombre_produits': client_stock.nombre_produits if client_stock else 0,
                'total_quantity': float(client_stock.total_quantity) if client_stock else 0,
                'total_value': float(client_stock.total_value) if client_stock else 0,
            } if client_stock else None,
        })
