# apps/ventes_clients/views_client.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Q
from django.utils import timezone

from .models import Client, Vente, Facture, Paiement, ClientWallet, WalletTransaction
from .serializers import (
    VenteListSerializer, FactureSerializer,
    PaiementSerializer, ClientWalletSerializer,
    WalletTransactionSerializer
)
from users.permissions import IsClient


class ClientSpaceViewSet(viewsets.ViewSet):
    """
    Espace client — vue personnalisée pour le client connecté.
    Toutes les données sont filtrées par son propre profil client.
    """
    permission_classes = [permissions.IsAuthenticated, IsClient]

    def _get_client(self, request):
        """Récupère le profil Client lié à l'utilisateur connecté"""
        return getattr(request.user, 'client_profile', None)

    # ============================================================
    # MES ACHATS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-orders')
    def my_orders(self, request):
        """Historique de mes achats"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        ventes = Vente.objects.filter(client=client).order_by('-sale_date')

        # Filtres
        status_filter = request.query_params.get('status')
        if status_filter:
            ventes = ventes.filter(status=status_filter)

        date_from = request.query_params.get('date_from')
        if date_from:
            ventes = ventes.filter(sale_date__date__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            ventes = ventes.filter(sale_date__date__lte=date_to)

        # Statistiques
        stats = {
            'total_orders': ventes.count(),
            'total_amount': ventes.aggregate(total=Sum('total'))['total'] or 0,
            'total_paid': ventes.aggregate(total=Sum('amount_paid'))['total'] or 0,
            'total_due': ventes.aggregate(total=Sum('amount_due'))['total'] or 0,
        }

        page = self.paginate_queryset(ventes)
        if page is not None:
            serializer = VenteListSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response({
                'stats': stats,
                'results': serializer.data
            })

        serializer = VenteListSerializer(
            ventes, many=True, context={'request': request})
        return Response({
            'stats': stats,
            'results': serializer.data
        })

    # ============================================================
    # MES FACTURES
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-invoices')
    def my_invoices(self, request):
        """Mes factures"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        factures = Facture.objects.filter(
            client=client
        ).order_by('-invoice_date')

        status_filter = request.query_params.get('status')
        if status_filter:
            factures = factures.filter(status=status_filter)

        stats = {
            'total_invoices': factures.count(),
            'total_amount': factures.aggregate(total=Sum('total'))['total'] or 0,
            'total_paid': factures.aggregate(total=Sum('amount_paid'))['total'] or 0,
        }

        page = self.paginate_queryset(factures)
        if page is not None:
            serializer = FactureSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response({
                'stats': stats,
                'results': serializer.data
            })

        serializer = FactureSerializer(
            factures, many=True, context={'request': request})
        return Response({
            'stats': stats,
            'results': serializer.data
        })

    # ============================================================
    # MES PAIEMENTS
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-payments')
    def my_payments(self, request):
        """Mes paiements"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        paiements = Paiement.objects.filter(
            facture__client=client
        ).order_by('-payment_date')

        stats = {
            'total_payments': paiements.count(),
            'total_amount': paiements.aggregate(total=Sum('amount'))['total'] or 0,
        }

        page = self.paginate_queryset(paiements)
        if page is not None:
            serializer = PaiementSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response({
                'stats': stats,
                'results': serializer.data
            })

        serializer = PaiementSerializer(
            paiements, many=True, context={'request': request})
        return Response({
            'stats': stats,
            'results': serializer.data
        })

    # ============================================================
    # MON PORTE-MONNAIE
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-wallet')
    def my_wallet(self, request):
        """Mon porte-monnaie"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        wallet, created = ClientWallet.objects.get_or_create(client=client)
        serializer = ClientWalletSerializer(wallet)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-wallet-transactions')
    def my_wallet_transactions(self, request):
        """Historique de mes transactions wallet"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        wallet, created = ClientWallet.objects.get_or_create(client=client)
        transactions = wallet.transactions.all().order_by('-created_at')[:100]

        serializer = WalletTransactionSerializer(transactions, many=True)
        return Response({
            'balance': wallet.balance,
            'balance_display': f"{wallet.balance:,.0f} FCFA",
            'total_deposits': wallet.total_deposits,
            'total_used': wallet.total_used,
            'transactions': serializer.data
        })

    # ============================================================
    # MON STOCK DE PRODUITS (produits achetés)
    # ============================================================
    @action(detail=False, methods=['get'], url_path='my-stock')
    def my_stock(self, request):
        """Produits achetés (stock client)"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Récupérer les produits achetés
        from ventes_clients.models import LigneVente
        from produits_stocks.models import Product

        lignes = LigneVente.objects.filter(
            sale__client=client,
            sale__status__in=['confirmed', 'paid', 'delivered']
        ).values('product').annotate(
            total_quantity=Sum('quantity'),
            total_spent=Sum('total')
        ).order_by('-total_quantity')

        resultats = []
        for ligne in lignes:
            try:
                product = Product.objects.get(id=ligne['product'])
                resultats.append({
                    'product_id': product.id,
                    'product_name': product.name,
                    'product_code': product.code,
                    'product_reference': product.reference,
                    'total_quantity': ligne['total_quantity'],
                    'total_spent': float(ligne['total_spent'] or 0),
                    'current_stock': product.stock_quantity,
                })
            except Product.DoesNotExist:
                continue

        return Response({
            'count': len(resultats),
            'results': resultats
        })

    # ============================================================
    # DASHBOARD CLIENT
    # ============================================================
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """Tableau de bord du client"""
        client = self._get_client(request)
        if not client:
            return Response(
                {'error': 'Aucun profil client lié à votre compte'},
                status=status.HTTP_404_NOT_FOUND
            )

        ventes = Vente.objects.filter(client=client)
        factures = Facture.objects.filter(client=client)
        paiements = Paiement.objects.filter(facture__client=client)
        wallet, _ = ClientWallet.objects.get_or_create(client=client)

        # Dernières ventes
        recent_sales = ventes.order_by('-sale_date')[:5]

        return Response({
            'client_info': {
                'id': client.id,
                'code': client.code,
                'name': client.name,
                'phone': client.phone,
                'email': client.email if hasattr(client, 'email') else None,
                'address': client.address,
            },
            'stats': {
                'total_orders': ventes.count(),
                'total_spent': float(ventes.aggregate(total=Sum('total'))['total'] or 0),
                'total_paid': float(paiements.aggregate(total=Sum('amount'))['total'] or 0),
                'total_due': float(ventes.aggregate(total=Sum('amount_due'))['total'] or 0),
                'total_invoices': factures.count(),
                'wallet_balance': float(wallet.balance),
            },
            'recent_orders': VenteListSerializer(
                recent_sales, many=True, context={'request': request}
            ).data,
            'wallet': ClientWalletSerializer(wallet).data,
        })