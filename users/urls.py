# apps/users/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegisterViewset,
    ClientRegisterViewset,
    LoginViewset,
    UserViewset,
    ProfileViewset,
)

router = DefaultRouter()
router.register('register', RegisterViewset, basename='register')
router.register('register-client', ClientRegisterViewset,
                basename='register-client')
router.register('login', LoginViewset, basename='login')
router.register('users', UserViewset, basename='users')
router.register('profile', ProfileViewset, basename='profile')


# ============================================================
# ✅ ROUTES MANUELLES (placées AVANT le router)
# pour éviter le conflit avec /users/{pk}/
# ============================================================
urlpatterns = [
    # /users/me/ → utilisateur connecté
    path(
        'users/me/',
        UserViewset.as_view({'get': 'me'}),
        name='user-me'
    ),

    # /users/pending-clients/ → clients en attente d'approbation
    path(
        'users/pending-clients/',
        UserViewset.as_view({'get': 'pending_clients'}),
        name='users-pending-clients'
    ),

    # /users/approved-clients/ → clients approuvés
    path(
        'users/approved-clients/',
        UserViewset.as_view({'get': 'approved_clients'}),
        name='users-approved-clients'
    ),

    # /users/{id}/check-client-profile/ → diagnostic
    path(
        'users/<int:pk>/check-client-profile/',
        UserViewset.as_view({'get': 'check_client_profile'}),
        name='users-check-client-profile'
    ),

    # ✅ Ensuite, les routes du router
    path('', include(router.urls)),
]
