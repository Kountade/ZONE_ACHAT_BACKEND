# apps/users/permissions.py
from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


class IsGestionnaire(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']


class IsComptable(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'comptable']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'comptable']


class IsMagasinier(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'magasinier']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'magasinier']


class IsCaissier(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'caissier']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'caissier']


class IsLivreur(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'livreur']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'livreur']


# ✅ NOUVELLE PERMISSION : CLIENT
class IsClient(permissions.BasePermission):
    """
    Permission pour les clients.
    Vérifie que l'utilisateur est un client approuvé et actif.
    """
    message = "Accès réservé aux clients approuvés."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'client'
            and request.user.is_approved
            and request.user.is_active
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsClientApproved(permissions.BasePermission):
    """
    Permission pour vérifier qu'un client est approuvé.
    Utilisable pour les endpoints qui nécessitent une approbation admin.
    """
    message = "Votre compte est en attente d'approbation."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role != 'client':
            return True  # Les autres rôles ne sont pas concernés
        return request.user.is_approved


class IsStaffOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff


class IsOwnerOrStaff(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.role == 'admin':
            return True
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'created_by'):
            return obj.created_by == request.user
        return False


class CanAccessClientSpace(permissions.BasePermission):
    """
    Permission pour l'espace client.
    Bloque l'accès si le client n'est pas approuvé.
    """
    message = "Votre compte client est en attente d'approbation par un administrateur."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == 'client':
            return request.user.is_approved
        return request.user.role in ['admin', 'gestionnaire', 'vendeur', 'comptable']


# Permissions spécifiques
class CanViewProducts(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier', 'comptable', 'client']


class CanEditProducts(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']


class CanViewStock(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier']


class CanManageStock(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']


class CanViewSales(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'caissier', 'comptable']


class CanCreateSales(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'caissier', 'vendeur']


class CanViewFinances(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'comptable']


class CanManageFinances(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'comptable']


class CanViewUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == 'admin'


class CanManageUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == 'admin'


class CanViewReports(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'comptable']


class CanManageDeliveries(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'livreur']


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role == 'admin'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


class IsGestionnaireOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']


class CanManageLots(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier']
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanManageExpiryAlerts(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier']
        return request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanManageInventory(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier']
        return request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanApproveClients(permissions.BasePermission):
    """Permission pour approuver les clients"""
    message = "Seuls les administrateurs et gestionnaires peuvent approuver des clients."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ['admin', 'gestionnaire']
        )