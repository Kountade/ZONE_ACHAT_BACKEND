# apps/ventes_clients/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ClientViewSet,
    VenteViewSet,
    PaiementViewSet,
    FactureViewSet,
    AvoirViewSet,
    TaxeViewSet,
    RemiseViewSet,
    SalesDashboardStatsViewSet,
    DevisViewSet,
    WalletViewSet,
    ClientWalletViewSet,
    ClientStockViewSet,
    ClientDeliveryViewSet,   # 🆕 AJOUT
)

# ✅ ESPACE CLIENT
from .views_client import ClientSpaceViewSet


router = DefaultRouter()

# ============================================================
# ENDPOINTS STANDARDS
# ============================================================
router.register('clients', ClientViewSet, basename='clients')
router.register('devis', DevisViewSet, basename='devis')
router.register('payments', PaiementViewSet, basename='payments')
router.register('factures', FactureViewSet, basename='factures')
router.register('avoirs', AvoirViewSet, basename='avoirs')
router.register('taxes', TaxeViewSet, basename='taxes')
router.register('remises', RemiseViewSet, basename='remises')
router.register(
    'dashboard-sales-stats',
    SalesDashboardStatsViewSet,
    basename='dashboard-sales-stats'
)

# ============================================================
# WALLET
# ============================================================
router.register('wallet', WalletViewSet, basename='wallet')

# ============================================================
# ESPACE CLIENT
# ============================================================
router.register('client-space', ClientSpaceViewSet, basename='client-space')

# ============================================================
# STOCK CLIENT
# ============================================================
router.register('client-stock', ClientStockViewSet, basename='client-stock')

# ============================================================
# 🆕 LIVRAISON CLIENT
# ============================================================
router.register('client-delivery', ClientDeliveryViewSet,
                basename='client-delivery')

# ============================================================
# VENTES (deux basenames différents)
# ============================================================
router.register('sales', VenteViewSet, basename='sales')
router.register('pos', VenteViewSet, basename='pos')


urlpatterns = [
    path('', include(router.urls)),
]
