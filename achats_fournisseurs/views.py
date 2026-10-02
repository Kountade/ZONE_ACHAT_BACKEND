from django.shortcuts import render

# Create your views here.
# apps/achats_fournisseurs/views.py
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date

from .models import (
    Supplier, SupplierContact, SupplierProduct, PurchaseOrder,
    PurchaseOrderLine, Receipt, ReceiptLine, PurchaseReturn,
    PurchaseReturnLine, SupplierInvoice, FournisseurPaiement
)
from .serializers import (
    SupplierListSerializer, SupplierDetailSerializer, SupplierWriteSerializer,
    SupplierContactSerializer, SupplierProductSerializer,
    PurchaseOrderListSerializer, PurchaseOrderDetailSerializer,
    PurchaseOrderCreateSerializer, PurchaseOrderUpdateSerializer,
    PurchaseOrderApproveSerializer,
    ReceiptListSerializer, ReceiptDetailSerializer, ReceiptCreateSerializer,
    ReceiptChoiceSerializer,
    PurchaseReturnSerializer, PurchaseReturnCreateSerializer,
    SupplierInvoiceListSerializer, SupplierInvoiceDetailSerializer,
    SupplierInvoiceCreateSerializer, SupplierInvoiceUpdateSerializer,
    SupplierInvoicePaymentSerializer,
    FournisseurPaiementSerializer, FournisseurPaiementCreateSerializer
)
from users.permissions import IsAdmin, IsGestionnaire, IsMagasinier


# ============================================================
# FOURNISSEUR VIEWSET
# ============================================================

class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return SupplierWriteSerializer
        return SupplierDetailSerializer

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
        is_active = self.request.query_params.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)
        is_preferred = self.request.query_params.get('is_preferred')
        if is_preferred == 'true':
            queryset = queryset.filter(is_preferred=True)
        ordering = self.request.query_params.get('ordering', 'name')
        if ordering:
            queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def debt_status(self, request, pk=None):
        supplier = self.get_object()
        return Response({
            'total_debt': supplier.total_debt,
            'overdue_debt': supplier.overdue_debt,
            'total_invoices': supplier.invoices.count(),
            'overdue_invoices': supplier.invoices.filter(
                due_date__lt=date.today(),
                paiement_status__in=['unpaid', 'partial']
            ).count()
        })

    @action(detail=True, methods=['get'])
    def orders_status(self, request, pk=None):
        supplier = self.get_object()
        orders = supplier.purchase_orders.all()
        return Response({
            'total_orders': orders.count(),
            'total_amount': orders.aggregate(total=Sum('total'))['total'] or 0,
            'received_amount': orders.aggregate(total=Sum('total_received_amount'))['total'] or 0,
            'invoiced_amount': orders.aggregate(total=Sum('total_invoiced_amount'))['total'] or 0,
            'paid_amount': orders.aggregate(total=Sum('total_paid_amount'))['total'] or 0,
            'orders_by_status': {
                status_code: orders.filter(status=status_code).count()
                for status_code, _ in PurchaseOrder.STATUS_CHOICES
                if orders.filter(status=status_code).count() > 0
            }
        })

    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        supplier = self.get_object()
        contacts = supplier.contacts.all()
        serializer = SupplierContactSerializer(contacts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_contact(self, request, pk=None):
        supplier = self.get_object()
        serializer = SupplierContactSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(supplier=supplier)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        supplier = self.get_object()
        products = supplier.products.filter(is_active=True)
        serializer = SupplierProductSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def purchase_orders(self, request, pk=None):
        supplier = self.get_object()
        orders = supplier.purchase_orders.all().order_by('-order_date')
        serializer = PurchaseOrderListSerializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        supplier = self.get_object()
        invoices = supplier.invoices.all().order_by('-invoice_date')
        serializer = SupplierInvoiceListSerializer(invoices, many=True)
        return Response(serializer.data)


# ============================================================
# BON DE COMMANDE VIEWSET
# ============================================================
# apps/achats_fournisseurs/views.py - Partie PurchaseOrderViewSet

class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseOrderListSerializer
        elif self.action == 'create':
            return PurchaseOrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PurchaseOrderUpdateSerializer
        return PurchaseOrderDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(po_number__icontains=search) |
                Q(supplier__name__icontains=search) |
                Q(supplier__code__icontains=search)
            )
        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)

        # ✅ CORRECTION : Gestion du statut pour les réceptions
        status_filter = self.request.query_params.get('status')
        if status_filter == 'confirmed':
            # Pour la liste des réceptions : inclure 'confirmed' ET 'partial'
            queryset = queryset.filter(status__in=['confirmed', 'partial'])
        elif status_filter:
            queryset = queryset.filter(status=status_filter)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(order_date__date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(order_date__date__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-order_date')
        if ordering:
            queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def available_for_receipt(self, request):
        """
        ✅ NOUVEL ENDPOINT : Récupère les commandes disponibles pour réception
        - Commandes confirmées (status='confirmed')
        - Commandes partiellement reçues (status='partial') qui ne sont pas encore entièrement reçues
        """
        queryset = PurchaseOrder.objects.filter(
            status__in=['confirmed', 'partial'],
            is_fully_received=False
        ).order_by('-order_date')

        # Filtrer par recherche
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(po_number__icontains=search) |
                Q(supplier__name__icontains=search)
            )

        # Filtrer par fournisseur
        supplier = request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)

        # Exclure les commandes déjà entièrement reçues (sécurité)
        queryset = queryset.filter(is_fully_received=False)

        serializer = PurchaseOrderListSerializer(
            queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        purchase_order = self.get_object()
        serializer = PurchaseOrderApproveSerializer(data=request.data)
        if serializer.is_valid():
            if serializer.validated_data['approved']:
                purchase_order.status = 'confirmed'
                purchase_order.approved_by = request.user
                purchase_order.approved_at = timezone.now()
            else:
                purchase_order.status = 'cancelled'
            purchase_order.save()
            purchase_order.generate_qr_code()
            purchase_order.save()
            return Response({
                'status': purchase_order.status,
                'approved': serializer.validated_data['approved']
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        purchase_order = self.get_object()
        if purchase_order.status not in ['draft', 'sent']:
            return Response(
                {"error": "Cette commande ne peut pas être annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )
        purchase_order.status = 'cancelled'
        purchase_order.save()
        purchase_order.generate_qr_code()
        purchase_order.save()
        return Response({
            'status': purchase_order.status,
            'message': 'Commande annulée avec succès'
        })

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        purchase_order = self.get_object()
        if purchase_order.status != 'draft':
            return Response(
                {"error": "Seules les commandes en brouillon peuvent être envoyées"},
                status=status.HTTP_400_BAD_REQUEST
            )
        purchase_order.status = 'sent'
        purchase_order.save()
        purchase_order.generate_qr_code()
        purchase_order.save()
        return Response({
            'status': purchase_order.status,
            'message': 'Commande envoyée avec succès'
        })

    @action(detail=True, methods=['get'])
    def receipts(self, request, pk=None):
        purchase_order = self.get_object()
        receipts = purchase_order.receipts.all()
        serializer = ReceiptListSerializer(receipts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        purchase_order = self.get_object()
        invoices = purchase_order.invoices.all()
        serializer = SupplierInvoiceListSerializer(invoices, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        purchase_order = self.get_object()
        payments = purchase_order.paiements.filter(status='confirmed')
        serializer = FournisseurPaiementSerializer(payments, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        purchase_order = self.get_object()
        if not purchase_order.qr_code:
            purchase_order.generate_qr_code()
            purchase_order.save()
        if purchase_order.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(purchase_order.qr_code.url),
                'qr_code_data': purchase_order.qr_code_data
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# ============================================================
# RÉCEPTION VIEWSET
# ============================================================


# ============================================================
# RÉCEPTION VIEWSET
# ============================================================

class ReceiptViewSet(viewsets.ModelViewSet):
    queryset = Receipt.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsMagasinier]

    def get_serializer_class(self):
        if self.action == 'list':
            return ReceiptListSerializer
        elif self.action == 'create':
            return ReceiptCreateSerializer
        elif self.action == 'available_for_invoice':
            return ReceiptChoiceSerializer
        return ReceiptDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'purchase_order',
            'purchase_order__supplier',
            'warehouse',
            'created_by'
        ).prefetch_related('lines', 'lines__product')

        # Filtre par commande
        purchase_order = self.request.query_params.get('purchase_order')
        if purchase_order:
            queryset = queryset.filter(purchase_order_id=purchase_order)

        # Filtre par statut
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # ✅ NOUVEAU : Filtre par is_invoiced
        is_invoiced = self.request.query_params.get('is_invoiced')
        if is_invoiced is not None:
            if is_invoiced.lower() == 'true':
                queryset = queryset.filter(is_invoiced=True)
            elif is_invoiced.lower() == 'false':
                queryset = queryset.filter(is_invoiced=False)

        # Filtre par entrepôt
        warehouse = self.request.query_params.get('warehouse')
        if warehouse:
            queryset = queryset.filter(warehouse_id=warehouse)

        # Filtre par fournisseur
        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(purchase_order__supplier_id=supplier)

        # Filtre par date
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(receipt_date__date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(receipt_date__date__lte=date_to)

        # Recherche
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(receipt_number__icontains=search) |
                Q(purchase_order__po_number__icontains=search) |
                Q(purchase_order__supplier__name__icontains=search)
            )

        # Tri
        ordering = self.request.query_params.get('ordering', '-receipt_date')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    # ✅ CORRECTION CRITIQUE : Retirer created_by
    # Le serializer ReceiptCreateSerializer le passe déjà lui-même
    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=['get'])
    def available_for_invoice(self, request):
        """Récupère les réceptions disponibles pour facturation"""
        purchase_order_id = request.query_params.get('purchase_order')
        supplier_id = request.query_params.get('supplier')

        queryset = Receipt.objects.filter(
            status='completed',
            is_invoiced=False
        ).select_related('purchase_order', 'purchase_order__supplier')

        if purchase_order_id:
            queryset = queryset.filter(purchase_order_id=purchase_order_id)
        if supplier_id:
            queryset = queryset.filter(purchase_order__supplier_id=supplier_id)

        queryset = queryset.order_by('-receipt_date')
        serializer = ReceiptChoiceSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler une réception"""
        receipt = self.get_object()

        if receipt.status != 'in_progress':
            return Response(
                {"error": "Cette réception ne peut pas être annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        receipt.status = 'cancelled'
        receipt.save()
        receipt.generate_qr_code()
        receipt.save()

        return Response({
            'status': receipt.status,
            'message': 'Réception annulée avec succès'
        })

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Terminer une réception"""
        receipt = self.get_object()

        if receipt.status != 'in_progress':
            return Response(
                {"error": "Seules les réceptions en cours peuvent être terminées"},
                status=status.HTTP_400_BAD_REQUEST
            )

        receipt.status = 'completed'
        receipt.save()
        receipt.generate_qr_code()
        receipt.save()

        return Response({
            'status': receipt.status,
            'message': 'Réception terminée avec succès'
        })

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        """Générer le QR Code d'une réception"""
        receipt = self.get_object()

        if not receipt.qr_code:
            receipt.generate_qr_code()
            receipt.save()

        if receipt.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(receipt.qr_code.url),
                'qr_code_data': receipt.qr_code_data
            })

        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    @action(detail=True, methods=['get'])
    def pdf_data(self, request, pk=None):
        """
        ✅ Endpoint dédié pour récupérer les données du PDF
        Utile pour la génération côté client
        """
        receipt = self.get_object()
        serializer = ReceiptDetailSerializer(
            receipt, context={'request': request}
        )
        return Response(serializer.data)

# ============================================================
# RETOUR FOURNISSEUR VIEWSET
# ============================================================

# apps/achats_fournisseurs/views.py


class PurchaseReturnViewSet(viewsets.ModelViewSet):
    queryset = PurchaseReturn.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseReturnCreateSerializer
        return PurchaseReturnSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'purchase_order', 'purchase_order__supplier', 'receipt', 'created_by'
        ).prefetch_related('lines', 'lines__product')

        purchase_order = self.request.query_params.get('purchase_order')
        if purchase_order:
            queryset = queryset.filter(purchase_order_id=purchase_order)

        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(purchase_order__supplier_id=supplier)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        reason = self.request.query_params.get('reason')
        if reason:
            queryset = queryset.filter(reason=reason)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(return_number__icontains=search) |
                Q(purchase_order__po_number__icontains=search) |
                Q(purchase_order__supplier__name__icontains=search)
            )

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(return_date__date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(return_date__date__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-return_date')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    # ✅ CORRECTION : NE PAS passer created_by (déjà fait dans le serializer)
    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Passer le retour en 'approved'"""
        retour = self.get_object()
        if retour.status != 'requested':
            return Response(
                {"error": f"Impossible d'approuver un retour au statut '{retour.get_status_display()}'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        retour.status = 'approved'
        if request.data.get('notes'):
            retour.notes = (retour.notes + "\n" +
                            request.data['notes']).strip()
        retour.save()
        retour.generate_qr_code()
        retour.save()
        return Response({
            'status': retour.status,
            'status_display': retour.get_status_display(),
            'message': '✅ Retour approuvé'
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Refuser le retour"""
        retour = self.get_object()
        if retour.status not in ['requested', 'approved']:
            return Response(
                {"error": f"Impossible de refuser un retour au statut '{retour.get_status_display()}'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        retour.status = 'rejected'
        if request.data.get('notes'):
            retour.notes = (retour.notes + "\n" +
                            request.data['notes']).strip()
        retour.save()
        retour.generate_qr_code()
        retour.save()
        return Response({
            'status': retour.status,
            'status_display': retour.get_status_display(),
            'message': '❌ Retour refusé'
        })

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        """Marquer le retour comme expédié"""
        retour = self.get_object()
        if retour.status != 'approved':
            return Response(
                {"error": f"Le retour doit être 'Approuvé'. Statut actuel : {retour.get_status_display()}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        retour.status = 'shipped'
        retour.save()
        retour.generate_qr_code()
        retour.save()
        return Response({
            'status': retour.status,
            'status_display': retour.get_status_display(),
            'message': '🚚 Retour expédié'
        })

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        """Marquer le retour comme remboursé"""
        retour = self.get_object()
        if retour.status != 'shipped':
            return Response(
                {"error": f"Le retour doit être 'Expédié'. Statut actuel : {retour.get_status_display()}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        retour.status = 'refunded'
        retour.save()
        retour.generate_qr_code()
        retour.save()
        return Response({
            'status': retour.status,
            'status_display': retour.get_status_display(),
            'message': '💰 Retour remboursé'
        })

    @action(detail=True, methods=['post'])
    def replace(self, request, pk=None):
        """Marquer le retour comme remplacé"""
        retour = self.get_object()
        if retour.status != 'shipped':
            return Response(
                {"error": f"Le retour doit être 'Expédié'. Statut actuel : {retour.get_status_display()}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        retour.status = 'replaced'
        retour.save()
        retour.generate_qr_code()
        retour.save()
        return Response({
            'status': retour.status,
            'status_display': retour.get_status_display(),
            'message': '🔄 Retour remplacé'
        })

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        retour = self.get_object()
        if not retour.qr_code:
            retour.generate_qr_code()
            retour.save()
        if retour.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(retour.qr_code.url),
                'qr_code_data': retour.qr_code_data
            })
        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# ============================================================
# FACTURE FOURNISSEUR VIEWSET - CORRIGÉ
# ============================================================


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    queryset = SupplierInvoice.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierInvoiceListSerializer
        elif self.action == 'create':
            return SupplierInvoiceCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return SupplierInvoiceUpdateSerializer
        return SupplierInvoiceDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()

        purchase_order = self.request.query_params.get('purchase_order')
        if purchase_order:
            queryset = queryset.filter(purchase_order_id=purchase_order)

        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        paiement_status = self.request.query_params.get('paiement_status')
        if paiement_status:
            if ',' in paiement_status:
                statuses = paiement_status.split(',')
                queryset = queryset.filter(paiement_status__in=statuses)
            else:
                queryset = queryset.filter(paiement_status=paiement_status)

        # ✅ Filtrer les factures disponibles pour paiement
        available_for_payment = self.request.query_params.get(
            'available_for_payment')
        if available_for_payment == 'true':
            queryset = queryset.filter(is_fully_paid=False)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(invoice_date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(invoice_date__lte=date_to)

        is_overdue = self.request.query_params.get('is_overdue')
        if is_overdue == 'true':
            queryset = queryset.filter(
                due_date__lt=date.today(),
                paiement_status__in=['unpaid', 'partial']
            )

        ordering = self.request.query_params.get('ordering', '-invoice_date')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def add_payment(self, request, pk=None):
        """✅ Ajouter un paiement à une facture"""
        invoice = self.get_object()

        if invoice.is_fully_paid:
            return Response({
                "error": "❌ Cette facture est déjà entièrement payée"
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = SupplierInvoicePaymentSerializer(data=request.data)

        if serializer.is_valid():
            amount = serializer.validated_data['amount']

            if amount > invoice.remaining_amount:
                return Response({
                    "error": f"⚠️ Le montant ({amount:,.0f} FCFA) dépasse le solde restant ({invoice.remaining_amount:,.0f} FCFA)"
                }, status=status.HTTP_400_BAD_REQUEST)

            payment_data = {
                'supplier_invoice': invoice.id,
                'amount': amount,
                'payment_date': serializer.validated_data['payment_date'],
                'method': serializer.validated_data['method'],
                'reference_number': serializer.validated_data.get('payment_reference', ''),
                'caisse_destination_id': serializer.validated_data.get('caisse_destination_id'),
                'compte_destination_id': serializer.validated_data.get('compte_destination_id'),
                'notes': f"Paiement enregistré depuis la facture {invoice.invoice_number}"
            }

            payment_serializer = FournisseurPaiementCreateSerializer(
                data=payment_data,
                context={'request': request}
            )

            if payment_serializer.is_valid():
                payment = payment_serializer.save()
                invoice.refresh_from_db()

                return Response({
                    'status': 'success',
                    'message': '✅ Paiement enregistré avec succès',
                    'payment': FournisseurPaiementSerializer(payment).data,
                    'invoice': SupplierInvoiceDetailSerializer(invoice).data,
                    'remaining_amount': invoice.remaining_amount,
                    'is_fully_paid': invoice.is_fully_paid
                }, status=status.HTTP_201_CREATED)
            else:
                return Response(payment_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def available_for_payment(self, request):
        """✅ Récupère les factures disponibles pour paiement"""
        supplier_id = request.query_params.get('supplier')
        queryset = SupplierInvoice.objects.filter(
            is_fully_paid=False).order_by('due_date')
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        serializer = SupplierInvoiceListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def payment_status(self, request, pk=None):
        """✅ Obtenir le statut de paiement d'une facture"""
        invoice = self.get_object()
        return Response({
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'total_amount': invoice.total_amount,
            'amount_paid': invoice.amount_paid,
            'remaining_amount': invoice.remaining_amount,
            'paid_percentage': invoice.paid_percentage,
            'is_fully_paid': invoice.is_fully_paid,
            'paiement_status': invoice.paiement_status,
            'paiement_status_display': invoice.get_paiement_status_display()
        })


# ============================================================
# PAIEMENT FOURNISSEUR VIEWSET - CORRIGÉ
# ============================================================

class FournisseurPaiementViewSet(viewsets.ModelViewSet):
    queryset = FournisseurPaiement.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'create':
            return FournisseurPaiementCreateSerializer
        return FournisseurPaiementSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()

        supplier_invoice = self.request.query_params.get('supplier_invoice')
        if supplier_invoice:
            queryset = queryset.filter(supplier_invoice_id=supplier_invoice)

        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_invoice__supplier_id=supplier)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        method = self.request.query_params.get('method')
        if method:
            queryset = queryset.filter(method=method)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(payment_date__date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(payment_date__date__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-payment_date')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    # ✅ CORRECTION : Ne pas passer created_by dans save()
    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        paiement = self.get_object()

        if paiement.status == 'cancelled':
            return Response(
                {"error": "Ce paiement est déjà annulé"},
                status=status.HTTP_400_BAD_REQUEST
            )

        supplier_invoice = paiement.supplier_invoice
        supplier_invoice.amount_paid -= paiement.amount
        supplier_invoice.update_payment_status()

        purchase_order = paiement.purchase_order or supplier_invoice.purchase_order
        if purchase_order:
            purchase_order.update_payment_status()

        if paiement.mouvement_tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie
                mouvement = MouvementTresorerie.objects.get(
                    id=paiement.mouvement_tresorerie_id)
                mouvement.status = 'cancelled'
                mouvement.save()
            except:
                pass

        paiement.status = 'cancelled'
        paiement.save()

        return Response({
            'status': paiement.status,
            'message': 'Paiement annulé avec succès'
        })

    @action(detail=True, methods=['get'])
    def generate_qr(self, request, pk=None):
        paiement = self.get_object()

        if not paiement.qr_code:
            paiement.generate_qr_code()
            paiement.save()

        if paiement.qr_code:
            return Response({
                'qr_code_url': request.build_absolute_uri(paiement.qr_code.url),
                'qr_code_data': paiement.qr_code_data
            })

        return Response(
            {"error": "Impossible de générer le QR Code"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================
# DASHBOARD STATS VIEWSET
# ============================================================

class AchatsDashboardStatsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        today = date.today()

        total_orders = PurchaseOrder.objects.count()
        pending_orders = PurchaseOrder.objects.filter(
            status__in=['draft', 'sent', 'confirmed']
        ).count()
        orders_this_month = PurchaseOrder.objects.filter(
            order_date__month=today.month,
            order_date__year=today.year
        ).count()

        total_amount = PurchaseOrder.objects.aggregate(total=Sum('total'))[
            'total'] or 0
        amount_this_month = PurchaseOrder.objects.filter(
            order_date__month=today.month,
            order_date__year=today.year
        ).aggregate(total=Sum('total'))['total'] or 0

        total_received = Receipt.objects.filter(status='completed').count()
        pending_receipts = Receipt.objects.filter(
            status__in=['pending', 'in_progress']).count()
        non_invoiced_receipts = Receipt.objects.filter(
            is_invoiced=False, status='completed').count()

        received_amount = PurchaseOrder.objects.aggregate(
            total=Sum('total_received_amount'))['total'] or 0
        remaining_to_receive = total_amount - received_amount

        total_invoices = SupplierInvoice.objects.count()
        unpaid_invoices = SupplierInvoice.objects.filter(
            paiement_status__in=['unpaid', 'partial', 'overdue']).count()
        overdue_invoices = SupplierInvoice.objects.filter(
            due_date__lt=today,
            paiement_status__in=['unpaid', 'partial']
        ).count()

        total_invoiced = SupplierInvoice.objects.aggregate(
            total=Sum('total_amount'))['total'] or 0
        total_paid = SupplierInvoice.objects.aggregate(
            total=Sum('amount_paid'))['total'] or 0
        total_remaining_to_pay = total_invoiced - total_paid

        top_suppliers = Supplier.objects.annotate(
            total_orders=Count('purchase_orders'),
            total_amount=Sum('purchase_orders__total')
        ).order_by('-total_amount')[:5]

        top_suppliers_data = []
        for supplier in top_suppliers:
            top_suppliers_data.append({
                'id': supplier.id,
                'name': supplier.name,
                'total_orders': supplier.total_orders,
                'total_amount': supplier.total_amount or 0
            })

        orders_by_status = {}
        for status_code, status_label in PurchaseOrder.STATUS_CHOICES:
            count = PurchaseOrder.objects.filter(status=status_code).count()
            if count > 0:
                orders_by_status[status_code] = count

        alerts = {
            'overdue_invoices': overdue_invoices,
            'pending_receipts': pending_receipts,
            'pending_orders': pending_orders,
            'non_invoiced_receipts': non_invoiced_receipts,
        }

        return Response({
            'orders': {
                'total': total_orders,
                'pending': pending_orders,
                'this_month': orders_this_month,
                'total_amount': total_amount,
                'amount_this_month': amount_this_month,
                'by_status': orders_by_status,
            },
            'receipts': {
                'total': total_received,
                'pending': pending_receipts,
                'non_invoiced': non_invoiced_receipts,
                'received_amount': received_amount,
                'remaining_to_receive': remaining_to_receive,
            },
            'invoices': {
                'total': total_invoices,
                'unpaid': unpaid_invoices,
                'overdue': overdue_invoices,
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_remaining_to_pay': total_remaining_to_pay,
            },
            'suppliers': {
                'total': Supplier.objects.filter(is_active=True).count(),
                'top': top_suppliers_data,
            },
            'alerts': alerts,
        })
