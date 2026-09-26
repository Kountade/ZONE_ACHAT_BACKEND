# apps/config/permissions.py (nouveau fichier)
from rest_framework import permissions


class IsAdminOrVendeur(permissions.BasePermission):
    """
    - Lecture : accessible à tout utilisateur authentifié
    - Écriture : réservé aux administrateurs
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Lecture seule → autorisée
        if request.method in permissions.SAFE_METHODS:
            return True

        # Écriture → seulement admin
        return request.user.role == 'admin'

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        return request.user.role == 'admin'
