from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EtablissementViewSet

router = DefaultRouter()
router.register(r'etablissements', EtablissementViewSet,
                basename='etablissement')

urlpatterns = [
    path('', include(router.urls)),
]
