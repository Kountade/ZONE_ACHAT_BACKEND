# apps/finances/pagination.py
# ============================================================
# PAGINATION PERSONNALISÉE POUR LE MODULE FINANCES
# ============================================================

from rest_framework.pagination import PageNumberPagination


class CompteComptablePagination(PageNumberPagination):
    """Pagination pour les comptes comptables."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class EcritureComptablePagination(PageNumberPagination):
    """Pagination pour les écritures comptables."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class DepensePagination(PageNumberPagination):
    """Pagination pour les dépenses."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class BudgetPagination(PageNumberPagination):
    """Pagination pour les budgets."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class RapportFinancierPagination(PageNumberPagination):
    """Pagination pour les rapports."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class OptimizedPagination(PageNumberPagination):
    """Pagination générique pour les gros volumes."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500
