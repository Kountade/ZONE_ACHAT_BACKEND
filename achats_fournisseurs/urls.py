# apps/achats_fournisseurs/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SupplierViewSet,
    PurchaseOrderViewSet,
    ReceiptViewSet,
    PurchaseReturnViewSet,
    SupplierInvoiceViewSet,
    FournisseurPaiementViewSet,
    AchatsDashboardStatsViewSet
)

router = DefaultRouter()

router.register('suppliers', SupplierViewSet, basename='suppliers')
router.register('purchase-orders', PurchaseOrderViewSet,
                basename='purchase-orders')
router.register('receipts', ReceiptViewSet, basename='receipts')
router.register('purchase-returns', PurchaseReturnViewSet,
                basename='purchase-returns')
router.register('supplier-invoices', SupplierInvoiceViewSet,
                basename='supplier-invoices')
router.register('fournisseur-paiements',
                FournisseurPaiementViewSet, basename='fournisseur-paiements')
router.register('dashboard-stats', AchatsDashboardStatsViewSet,
                basename='dashboard-stats')

urlpatterns = [
    path('', include(router.urls)),
]
