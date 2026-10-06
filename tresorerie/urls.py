# apps/tresorerie/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()

# Enregistrement des ViewSets
router.register(r'caisses', CaisseViewSet, basename='caisse')
router.register(r'comptes-bancaires', CompteBancaireViewSet,
                basename='compte-bancaire')
router.register(r'mouvements', MouvementTresorerieViewSet,
                basename='mouvement-tresorerie')
router.register(r'frais', FraisViewSet, basename='frais')
router.register(r'previsions', PrevisionTresorerieViewSet,
                basename='prevision')
router.register(r'rapprochements', RapprochementBancaireViewSet,
                basename='rapprochement')
router.register(r'tresorerie-journaliere',
                TresorerieJournaliereViewSet, basename='tresorerie-journaliere')
router.register(r'dashboard', TresorerieDashboardViewSet,
                basename='tresorerie-dashboard')


urlpatterns = [
    path('', include(router.urls)),
]
