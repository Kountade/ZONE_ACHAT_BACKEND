# apps/ventes_clients/views_client.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal

from .models import (
    Client, Vente, Facture, Paiement,
    ClientWallet, WalletTransaction,
    ClientStock, ClientStockLigne, ClientStockMovement,     # 🆕 ClientStockLigne
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
    ClientDeliveryRequestCreateSerializer,      # 🆕
    ClientDeliveryRequestUpdateSerializer,      # 🆕
)
from users.permissions import IsClient


# ============================================================
# PAGINATION PERSONNALISÉE
# ============================================================
class ClientSpacePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class ClientSpaceViewSet(viewsets.GenericViewSet):
    """
    Espace client — vue personnalisée pour le client connecté.
    Toutes les données sont filtrées par son propre profil client.
    """
    permission_classes = [permissions.IsAuthenticated, IsClient]
    serializer_class = VenteListSerializer
    pagination_class = ClientSpacePagination

    # ============================================================
    # HELPERS
    # ============================================================
    def _get_client(self, request):
        """Récupère le profil Client lié à l'utilisateur connecté."""
        client = getattr(request.user, 'client_profile', None)
        if client:
            return client
        client = getattr(request.user, 'client', None)
        if client:
            return client
        return None

    def _no_client_response(self):
        return Response(
            {'error': 'Aucun profil client lié à votre compte. '
                      'Contactez un administrateur pour activer votre espace client.'},
            status=status.HTTP_404_NOT_FOUND
        )

    def _paginated_response(self, queryset, serializer_class, extra_data=None):
        """
        Helper pour construire une réponse paginée avec données extra.
        """
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

    # ============================================================
    # MES ACHATS (liste)
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-orders')
    def my_orders(self, request):
        """Historique de mes achats"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        ventes = Vente.objects.filter(client=client).order_by('-sale_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            ventes = ventes.filter(status=status_filter)

        date_from = request.query_params.get('date_from')
        if date_from:
            ventes = ventes.filter(sale_date__date__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            ventes = ventes.filter(sale_date__date__lte=date_to)

        stats = {
            'total_orders': ventes.count(),
            'total_amount': float(ventes.aggregate(total=Sum('total'))['total'] or 0),
            'total_paid': float(ventes.aggregate(total=Sum('amount_paid'))['total'] or 0),
            'total_due': float(ventes.aggregate(total=Sum('amount_due'))['total'] or 0),
        }

        return self._paginated_response(
            ventes, VenteListSerializer, {'stats': stats}
        )

    # ============================================================
    # DÉTAIL D'UNE COMMANDE
    # ============================================================
    @action(detail=True, methods=['get'], url_path='order-detail')
    def order_detail(self, request, pk=None):
        """Détail complet d'une commande du client connecté."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            vente = Vente.objects.prefetch_related(
                'lines',
                'lines__product',
                'lines__lot',
                'invoices',
                'invoices__paiements',
            ).get(id=pk, client=client)
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
        """Mes factures"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        factures = Facture.objects.filter(
            client=client
        ).order_by('-invoice_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            factures = factures.filter(status=status_filter)

        stats = {
            'total_invoices': factures.count(),
            'total_amount': float(factures.aggregate(total=Sum('total'))['total'] or 0),
            'total_paid': float(factures.aggregate(total=Sum('amount_paid'))['total'] or 0),
        }

        return self._paginated_response(
            factures, FactureSerializer, {'stats': stats}
        )

    # ============================================================
    # MES PAIEMENTS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-payments')
    def my_payments(self, request):
        """Mes paiements"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        paiements = Paiement.objects.filter(
            facture__client=client
        ).order_by('-payment_date')

        stats = {
            'total_payments': paiements.count(),
            'total_amount': float(paiements.aggregate(total=Sum('amount'))['total'] or 0),
        }

        return self._paginated_response(
            paiements, PaiementSerializer, {'stats': stats}
        )

    # ============================================================
    # MON PORTE-MONNAIE
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-wallet')
    def my_wallet(self, request):
        """Mon porte-monnaie"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        wallet, created = ClientWallet.objects.get_or_create(client=client)
        serializer = ClientWalletSerializer(wallet)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-wallet-transactions')
    def my_wallet_transactions(self, request):
        """Historique de mes transactions wallet"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        wallet, created = ClientWallet.objects.get_or_create(client=client)
        transactions = wallet.transactions.all().order_by('-created_at')[:100]

        serializer = WalletTransactionSerializer(transactions, many=True)
        return Response({
            'balance': float(wallet.balance),
            'balance_display': f"{wallet.balance:,.0f} FCFA",
            'total_deposits': float(wallet.total_deposits),
            'total_used': float(wallet.total_used),
            'transactions': serializer.data
        })

    # ============================================================
    # MON STOCK DE PRODUITS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-stock')
    def my_stock(self, request):
        """Stock de marchandises déposées chez le client."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        stock = ClientStock.objects.filter(client=client).first()

        if not stock:
            return Response({
                'count': 0,
                'total_quantity': 0,
                'total_value': 0,
                'results': []
            })

        serializer = ClientStockSerializer(stock)

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
        """Historique des mouvements de mon stock."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        stock = ClientStock.objects.filter(client=client).first()

        if not stock:
            return Response({
                'client_id': client.id,
                'client_name': client.name,
                'movements': []
            })

        movement_type = request.query_params.get('type')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        movements = stock.movements.select_related('product', 'created_by')

        if movement_type:
            movements = movements.filter(movement_type=movement_type)
        if date_from:
            movements = movements.filter(created_at__date__gte=date_from)
        if date_to:
            movements = movements.filter(created_at__date__lte=date_to)

        movements = movements.order_by('-created_at')[:100]

        serializer = ClientStockMovementSerializer(movements, many=True)

        total_deposits = stock.movements.filter(
            movement_type='deposit'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        total_withdrawals = stock.movements.filter(
            movement_type__in=['withdrawal', 'delivery', 'sale']
        ).aggregate(total=Sum('quantity'))['total'] or 0

        return Response({
            'client_id': client.id,
            'client_name': client.name,
            'stats': {
                'total_deposits': float(total_deposits),
                'total_withdrawals': float(total_withdrawals),
                'current_quantity': float(stock.total_quantity),
            },
            'movements': serializer.data
        })

    # ============================================================
    # MES LIVRAISONS (SUIVI) — SANS PAGINATION
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-deliveries')
    def my_deliveries(self, request):
        """
        Suivi des livraisons de mes produits vers leurs destinataires.
        GET /client-space/my-deliveries/

        ⚠️ SANS PAGINATION pour éviter le conflit avec le frontend.
        """
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        status_filter = request.query_params.get('status')

        deliveries = ClientDelivery.objects.filter(
            client=client
        ).prefetch_related(
            'lignes', 'lignes__product'
        ).order_by('-created_at')

        if status_filter:
            deliveries = deliveries.filter(status=status_filter)

        stats = {
            'total': deliveries.count(),
            'pending': deliveries.filter(status='pending').count(),
            'confirmed': deliveries.filter(status='confirmed').count(),      # 🆕
            'in_transit': deliveries.filter(status='in_transit').count(),
            'delivered': deliveries.filter(status='delivered').count(),
            'cancelled': deliveries.filter(status='cancelled').count(),
            'rejected': deliveries.filter(status='rejected').count(),         # 🆕
        }

        serializer = ClientDeliverySerializer(
            deliveries, many=True, context={'request': request}
        )

        return Response({
            'client_id': client.id,
            'client_name': client.name,
            'stats': stats,
            'count': deliveries.count(),
            'results': serializer.data,
        })

    # ============================================================
    # DÉTAIL D'UNE LIVRAISON
    # ============================================================
    @action(detail=True, methods=['get'], url_path='my-delivery-detail')
    def my_delivery_detail(self, request, pk=None):
        """Détail d'une livraison du client connecté."""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        try:
            delivery = ClientDelivery.objects.prefetch_related(
                'lignes', 'lignes__product'
            ).get(id=pk, client=client)
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
    # 🆕 CRÉER UNE DEMANDE DE LIVRAISON (CLIENT)
    # ============================================================
    @action(detail=False, methods=['post'], url_path='my-deliveries/create')
    def create_my_delivery(self, request):
        """
        Le client crée une demande de livraison.
        Statut initial : 'pending' (à valider par l'admin).

        POST /client-space/my-deliveries/create/
        Body: {
            "recipient_name": "...",
            "recipient_phone": "...",
            "recipient_address": "...",
            "recipient_email": "...",
            "recipient_notes": "...",
            "client_notes": "...",
            "lignes": [
                {"product": 1, "quantity": 5, "notes": ""}
            ]
        }
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
                # Récupérer le stock du client
                client_stock = ClientStock.objects.filter(client=client).first()

                if not client_stock:
                    return Response(
                        {'error': 'Vous n\'avez aucun stock disponible. '
                                  'Contactez l\'administrateur.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Créer la livraison
                delivery = ClientDelivery.objects.create(
                    client=client,
                    client_stock=client_stock,
                    # Destinataire
                    recipient_name=data['recipient_name'],
                    recipient_phone=data['recipient_phone'],
                    recipient_address=data.get('recipient_address', ''),
                    recipient_email=data.get('recipient_email', ''),
                    recipient_notes=data.get('recipient_notes', ''),
                    # Notes client
                    client_notes=data.get('client_notes', ''),
                    # Statut
                    status='pending',
                    created_by=request.user,
                    created_by_client=True,   # ⚠️ Marqueur de demande client
                )

                # Ajouter les lignes
                for ligne_data in data['lignes']:
                    product_id = (
                        ligne_data['product'].id
                        if hasattr(ligne_data['product'], 'id')
                        else ligne_data['product']
                    )
                    quantity = Decimal(str(ligne_data['quantity']))

                    # Vérifier le produit dans le stock
                    stock_ligne = ClientStockLigne.objects.filter(
                        stock=client_stock,
                        product_id=product_id
                    ).first()

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

                    ClientDeliveryLigne.objects.create(
                        delivery=delivery,
                        product_id=product_id,
                        client_stock_ligne=stock_ligne,
                        quantity=quantity,
                        unit_price=stock_ligne.unit_price or 0,
                        notes=ligne_data.get('notes', ''),
                    )

                delivery.recalculate_totals()

                # Log
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"📝 Demande client créée : {delivery.delivery_number} "
                    f"par {request.user.email} ({delivery.total_quantity} unités)"
                )

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
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Erreur création demande client")
            return Response(
                {'error': f'Erreur : {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 🆕 MODIFIER UNE DEMANDE (CLIENT)
    # ============================================================
    @action(detail=True, methods=['put', 'patch'], url_path='my-deliveries/update')
    def update_my_delivery(self, request, pk=None):
        """
        Le client peut modifier sa demande TANT QUE le statut est 'pending'.
        PUT/PATCH /client-space/{id}/my-deliveries/update/
        """
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

        if not delivery.can_be_edited_by_client:
            return Response(
                {
                    'error': (
                        f'Cette demande ne peut plus être modifiée '
                        f'(statut actuel : {delivery.get_status_display()})'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ClientDeliveryRequestUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            with transaction.atomic():
                # Mettre à jour les champs destinataire
                for field in ['recipient_name', 'recipient_phone',
                              'recipient_address', 'recipient_email',
                              'recipient_notes', 'client_notes']:
                    if field in data:
                        setattr(delivery, field, data[field])

                delivery.save()

                # Mettre à jour les lignes si fournies
                if 'lignes' in data:
                    delivery.lignes.all().delete()

                    client_stock = delivery.client_stock

                    for ligne_data in data['lignes']:
                        product_id = (
                            ligne_data['product'].id
                            if hasattr(ligne_data['product'], 'id')
                            else ligne_data['product']
                        )
                        quantity = Decimal(str(ligne_data['quantity']))

                        stock_ligne = ClientStockLigne.objects.filter(
                            stock=client_stock,
                            product_id=product_id
                        ).first()

                        if not stock_ligne:
                            raise ValueError(
                                f"Le produit {product_id} n'est pas dans votre stock."
                            )

                        if stock_ligne.quantity < quantity:
                            raise ValueError(
                                f"Stock insuffisant pour {stock_ligne.product.name}"
                            )

                        ClientDeliveryLigne.objects.create(
                            delivery=delivery,
                            product_id=product_id,
                            client_stock_ligne=stock_ligne,
                            quantity=quantity,
                            unit_price=stock_ligne.unit_price or 0,
                            notes=ligne_data.get('notes', ''),
                        )

                    delivery.recalculate_totals()

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
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Erreur modification demande")
            return Response(
                {'error': f'Erreur : {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ============================================================
    # 🆕 ANNULER UNE DEMANDE (CLIENT)
    # ============================================================
    @action(detail=True, methods=['post'], url_path='my-deliveries/cancel')
    def cancel_my_delivery(self, request, pk=None):
        """
        Le client annule sa demande (si 'pending' ou 'confirmed').
        POST /client-space/{id}/my-deliveries/cancel/
        """
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
                {
                    'error': (
                        f'Cette demande ne peut plus être annulée '
                        f'(statut actuel : {delivery.get_status_display()})'
                    )
                },
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

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"❌ Demande client annulée : {delivery.delivery_number}")

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
        """Tableau de bord du client"""
        client = self._get_client(request)
        if not client:
            return self._no_client_response()

        ventes = Vente.objects.filter(client=client)
        factures = Facture.objects.filter(client=client)
        paiements = Paiement.objects.filter(facture__client=client)
        wallet, _ = ClientWallet.objects.get_or_create(client=client)

        client_stock = ClientStock.objects.filter(client=client).first()

        # Livraisons
        deliveries_qs = ClientDelivery.objects.filter(client=client)
        recent_deliveries = deliveries_qs.order_by('-created_at')[:5]

        recent_sales = ventes.order_by('-sale_date')[:5]

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
                'total_orders': ventes.count(),
                'total_spent': float(ventes.aggregate(total=Sum('total'))['total'] or 0),
                'total_paid': float(paiements.aggregate(total=Sum('amount'))['total'] or 0),
                'total_due': float(ventes.aggregate(total=Sum('amount_due'))['total'] or 0),
                'total_invoices': factures.count(),
                'wallet_balance': float(wallet.balance),

                # Stats stock
                'stock_products': client_stock.nombre_produits if client_stock else 0,
                'stock_quantity': float(client_stock.total_quantity) if client_stock else 0,
                'stock_value': float(client_stock.total_value) if client_stock else 0,

                # Stats livraisons
                'total_deliveries': deliveries_qs.count(),
                'pending_deliveries': deliveries_qs.filter(status='pending').count(),
                'confirmed_deliveries': deliveries_qs.filter(status='confirmed').count(),       # 🆕
                'in_transit_deliveries': deliveries_qs.filter(status='in_transit').count(),
                'delivered_deliveries': deliveries_qs.filter(status='delivered').count(),
                'rejected_deliveries': deliveries_qs.filter(status='rejected').count(),         # 🆕
            },
            'recent_orders': VenteListSerializer(
                recent_sales, many=True, context={'request': request}
            ).data,
            'recent_deliveries': ClientDeliverySerializer(
                recent_deliveries, many=True, context={'request': request}
            ).data,
            'wallet': ClientWalletSerializer(wallet).data,
            'stock_summary': {
                'has_stock': client_stock is not None,
                'nombre_produits': client_stock.nombre_produits if client_stock else 0,
                'total_quantity': float(client_stock.total_quantity) if client_stock else 0,
                'total_value': float(client_stock.total_value) if client_stock else 0,
            } if client_stock else None,
        })