# apps/achats_fournisseurs/pagination.py
# ============================================================
# PAGINATION PERSONNALISÉE POUR OPTIMISATION
# ============================================================

from rest_framework.pagination import PageNumberPagination


class SupplierPagination(PageNumberPagination):
    """Pagination pour les fournisseurs (volume moyen)."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class PurchaseOrderPagination(PageNumberPagination):
    """Pagination pour les bons de commande."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class ReceiptPagination(PageNumberPagination):
    """Pagination pour les réceptions."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class SupplierInvoicePagination(PageNumberPagination):
    """Pagination pour les factures fournisseurs."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class PaymentPagination(PageNumberPagination):
    """Pagination pour les paiements fournisseurs."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class OptimizedPagination(PageNumberPagination):
    """Pagination générique pour les gros volumes."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class LargePagination(PageNumberPagination):
    """Pagination pour les endpoints admin."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000
