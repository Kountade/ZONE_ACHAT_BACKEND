# apps/tresorerie/pagination.py
# ============================================================
# PAGINATION PERSONNALISEE POUR TRESORERIE
# ============================================================

from rest_framework.pagination import PageNumberPagination


class CaissePagination(PageNumberPagination):
    """
    Pagination pour les caisses.
    - Taille par defaut : 50
    - Taille max : 1000
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


class CompteBancairePagination(PageNumberPagination):
    """
    Pagination pour les comptes bancaires.
    - Taille par defaut : 50
    - Taille max : 500
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class MouvementPagination(PageNumberPagination):
    """
    Pagination pour les mouvements de tresorerie.
    - Taille par defaut : 100
    - Taille max : 2000 (pour les rapports)
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 2000


class FraisPagination(PageNumberPagination):
    """
    Pagination pour les frais.
    - Taille par defaut : 100
    - Taille max : 1000
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class PrevisionPagination(PageNumberPagination):
    """
    Pagination pour les previsions.
    - Taille par defaut : 100
    - Taille max : 500
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class RapprochementPagination(PageNumberPagination):
    """
    Pagination pour les rapprochements bancaires.
    - Taille par defaut : 100
    - Taille max : 500
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class TresorerieJournalierePagination(PageNumberPagination):
    """
    Pagination pour la tresorerie journaliere.
    - Taille par defaut : 100
    - Taille max : 1000 (pour les rapports annuels)
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000
