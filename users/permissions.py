# apps/users/permissions.py
from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """
    Permission pour les administrateurs uniquement
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


class IsGestionnaire(permissions.BasePermission):
    """
    Permission pour les gestionnaires et administrateurs
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']


class IsComptable(permissions.BasePermission):
    """
    Permission pour les comptables et administrateurs
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'comptable']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'comptable']


class IsMagasinier(permissions.BasePermission):
    """
    Permission pour les magasiniers, gestionnaires et administrateurs
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'magasinier']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'magasinier']


class IsCaissier(permissions.BasePermission):
    """
    Permission pour les caissiers, gestionnaires et administrateurs
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'caissier']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'caissier']


class IsLivreur(permissions.BasePermission):
    """
    Permission pour les livreurs, gestionnaires et administrateurs
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'livreur']

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire', 'livreur']


class IsStaffOrReadOnly(permissions.BasePermission):
    """
    Lecture seule pour tous, écriture seulement pour le staff
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff


class IsOwnerOrStaff(permissions.BasePermission):
    """
    Permission: l'utilisateur peut modifier ses propres données
    Le staff peut tout modifier
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Le staff a tous les droits
        if request.user.is_staff or request.user.role == 'admin':
            return True

        # Vérifier si l'objet appartient à l'utilisateur
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'created_by'):
            return obj.created_by == request.user

        return False


class HasRolePermission(permissions.BasePermission):
    """
    Permission basée sur les rôles et permissions spécifiques
    Utilise la méthode has_permission du modèle CustomUser
    """

    def __init__(self, required_permission):
        self.required_permission = required_permission

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.has_permission(self.required_permission)

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return request.user.has_permission(self.required_permission)


# Classes factory pour créer des permissions dynamiques
class PermissionFactory:
    """Factory pour créer des permissions personnalisées"""

    @staticmethod
    def require_permission(permission_name):
        """Crée une permission qui requiert une permission spécifique"""
        return type(
            f'Require{permission_name.title()}',
            (permissions.BasePermission,),
            {
                'has_permission': lambda self, request, view: (
                    request.user and request.user.is_authenticated and
                    request.user.has_permission(permission_name)
                ),
                'has_object_permission': lambda self, request, view, obj: (
                    request.user and request.user.is_authenticated and
                    request.user.has_permission(permission_name)
                )
            }
        )

    @staticmethod
    def require_any_role(roles):
        """Crée une permission qui accepte plusieurs rôles"""
        return type(
            f'RequireAnyRole',
            (permissions.BasePermission,),
            {
                'has_permission': lambda self, request, view: (
                    request.user and request.user.is_authenticated and
                    request.user.role in roles
                ),
                'has_object_permission': lambda self, request, view, obj: (
                    request.user and request.user.is_authenticated and
                    request.user.role in roles
                )
            }
        )


# Permissions pré-définies pour les actions spécifiques
class CanViewProducts(permissions.BasePermission):
    """Permission pour voir les produits"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier', 'comptable']


class CanEditProducts(permissions.BasePermission):
    """Permission pour modifier les produits"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']


class CanViewStock(permissions.BasePermission):
    """Permission pour voir les stocks"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier']


class CanManageStock(permissions.BasePermission):
    """Permission pour gérer les stocks (entrées/sorties)"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']


class CanViewSales(permissions.BasePermission):
    """Permission pour voir les ventes"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'caissier', 'comptable']


class CanCreateSales(permissions.BasePermission):
    """Permission pour créer des ventes"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'caissier']


class CanViewFinances(permissions.BasePermission):
    """Permission pour voir les finances"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'comptable']


class CanManageFinances(permissions.BasePermission):
    """Permission pour gérer les finances"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'comptable']


class CanViewUsers(permissions.BasePermission):
    """Permission pour voir les utilisateurs"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == 'admin'


class CanManageUsers(permissions.BasePermission):
    """Permission pour gérer les utilisateurs"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == 'admin'


class CanViewReports(permissions.BasePermission):
    """Permission pour voir les rapports"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'comptable']


class CanManageDeliveries(permissions.BasePermission):
    """Permission pour gérer les livraisons"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ['admin', 'gestionnaire', 'livreur']


# Combinaison de permissions
class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Lecture seule pour tous, écriture seulement pour les admins
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role == 'admin'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


class IsGestionnaireOrReadOnly(permissions.BasePermission):
    """
    Lecture seule pour tous, écriture seulement pour les gestionnaires et admins
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.role in ['admin', 'gestionnaire']


# Permission pour l'API de gestion des lots (FIFO)
class CanManageLots(permissions.BasePermission):
    """
    Permission pour gérer les lots (création, modification, consommation)
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Actions en lecture seule
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier']

        # Actions d'écriture
        return request.user.role in ['admin', 'gestionnaire', 'magasinier']

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier', 'caissier']

        return request.user.role in ['admin', 'gestionnaire', 'magasinier']


# Permission pour les alertes d'expiration
class CanManageExpiryAlerts(permissions.BasePermission):
    """
    Permission pour gérer les alertes d'expiration
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Tout le monde peut voir les alertes
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier']

        # Seuls les gestionnaires et admins peuvent traiter les alertes
        return request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


# Permission pour les inventaires
class CanManageInventory(permissions.BasePermission):
    """
    Permission pour gérer les inventaires
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return request.user.role in ['admin', 'gestionnaire', 'magasinier']

        return request.user.role in ['admin', 'gestionnaire']

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
