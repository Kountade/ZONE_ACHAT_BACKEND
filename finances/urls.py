# apps/finances/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CompteComptableViewSet,
    EcritureComptableViewSet,
    DepenseViewSet,
    BudgetViewSet,
    BudgetCategorieViewSet,
    RapportFinancierViewSet,
    ConfigurationFinanciereViewSet,
    JournalComptableViewSet,
    GrandLivreViewSet,
    BalanceGeneraleViewSet,
    DashboardFinancierViewSet
)

router = DefaultRouter()
router.register('comptes-comptables', CompteComptableViewSet,
                basename='comptes-comptables')
router.register('ecritures-comptables', EcritureComptableViewSet,
                basename='ecritures-comptables')
router.register('depenses', DepenseViewSet, basename='depenses')
router.register('budgets', BudgetViewSet, basename='budgets')
router.register('budget-categories', BudgetCategorieViewSet,
                basename='budget-categories')
router.register('rapports-financiers', RapportFinancierViewSet,
                basename='rapports-financiers')
router.register('configuration-financiere',
                ConfigurationFinanciereViewSet, basename='configuration-financiere')
router.register('journal-comptable', JournalComptableViewSet,
                basename='journal-comptable')
router.register('grand-livre', GrandLivreViewSet, basename='grand-livre')
router.register('balance-generale', BalanceGeneraleViewSet,
                basename='balance-generale')
router.register('dashboard-financier', DashboardFinancierViewSet,
                basename='dashboard-financier')

urlpatterns = [
    path('', include(router.urls)),
]
