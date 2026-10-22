# apps/produits_stocks/pagination.py
# ============================================================
# PAGINATION PERSONNALISEE POUR PRODUITS_STOCKS
# ============================================================

from rest_framework.pagination import PageNumberPagination


class ProductPagination(PageNumberPagination):
    """
    Pagination pour les produits.
    - Taille par defaut : 50
    - Taille max : 5000 (pour charger tous les produits dans le formulaire de vente)
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 5000


class StockPagination(PageNumberPagination):
    """
    Pagination pour les stocks.
    - Taille par defaut : 100
    - Taille max : 5000
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 5000


class MovementPagination(PageNumberPagination):
    """
    Pagination pour les mouvements.
    - Taille par defaut : 100
    - Taille max : 1000
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class LotPagination(PageNumberPagination):
    """
    Pagination pour les lots.
    - Taille par defaut : 100
    - Taille max : 5000 (pour charger tous les lots dans le formulaire de vente)
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 5000


class LargePagination(PageNumberPagination):
    """
    Pagination large (categories, unites, entrepots, clients).
    - Taille par defaut : 100
    - Taille max : 5000 (pour charger tous les clients dans le formulaire de vente)
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 5000
