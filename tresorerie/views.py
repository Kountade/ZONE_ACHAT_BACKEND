# apps/tresorerie/views.py
from rest_framework import viewsets, status, filters, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import models
from django.db.models import Sum, Count, Q, F, Value, DecimalField, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Caisse, CompteBancaire, MouvementTresorerie, Frais,
    PrevisionTresorerie, RapprochementBancaire, TresorerieJournaliere
)
from .serializers import (
    CaisseSerializer, CompteBancaireSerializer, MouvementTresorerieSerializer,
    FraisSerializer, PrevisionTresorerieSerializer,
    RapprochementBancaireSerializer, TresorerieJournaliereSerializer,
    TresorerieDashboardSerializer
)
from .pagination import (
    CaissePagination,
    CompteBancairePagination,
    MouvementPagination,
    FraisPagination,
    PrevisionPagination,
    RapprochementPagination,
    TresorerieJournalierePagination,
)
from produits_stocks.models import Warehouse


# ============================================================
# CAISSE VIEWSET
# ============================================================

class CaisseViewSet(viewsets.ModelViewSet):
    serializer_class = CaisseSerializer
    pagination_class = CaissePagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_caisse', 'is_active', 'is_default']
    search_fields = ['code', 'nom']
    ordering_fields = ['code', 'solde_actuel', 'created_at']

    def get_queryset(self):
        return (
            Caisse.objects
            .select_related('warehouse', 'responsable', 'created_by')
            .annotate(
                total_mouvements_annotated=Count('mouvements')
            )
            .order_by('code')
        )


# ============================================================
# COMPTE BANCAIRE VIEWSET
# ============================================================

class CompteBancaireViewSet(viewsets.ModelViewSet):
    serializer_class = CompteBancaireSerializer
    pagination_class = CompteBancairePagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_compte', 'is_active', 'is_default']
    search_fields = ['banque', 'nom', 'numero_compte']
    ordering_fields = ['banque', 'solde_actuel']

    def get_queryset(self):
        return (
            CompteBancaire.objects
            .select_related('warehouse', 'created_by')
            .order_by('banque', 'code')
        )


# ============================================================
# MOUVEMENT TRESORERIE VIEWSET
# ============================================================

class MouvementTresorerieViewSet(viewsets.ModelViewSet):
    serializer_class = MouvementTresorerieSerializer
    pagination_class = MouvementPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]

    filterset_fields = [
        'warehouse',
        'type_mouvement',
        'source_type',
        'mode_paiement',
        'status',
        'caisse',
        'compte_bancaire',
        'rapproche'
    ]
    search_fields = ['reference', 'libelle',
                     'source_reference', 'reference_externe']
    ordering_fields = ['date_mouvement', 'montant', 'created_at']

    def get_queryset(self):
        return (
            MouvementTresorerie.objects
            .select_related(
                'warehouse',
                'caisse',
                'caisse__warehouse',
                'compte_bancaire',
                'compte_bancaire__warehouse',
                'created_by',
                'valide_par',
            )
            .order_by('-date_mouvement')
        )

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'annule':
            return Response(
                {'detail': 'Ce mouvement est deja annule.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if mouvement.status != 'effectue':
            return Response(
                {'detail': 'Seul un mouvement effectue peut etre annule.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        mouvement.annuler()
        return Response(
            {'detail': f'Mouvement {mouvement.reference} annule avec succes.'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'effectue':
            return Response(
                {'detail': 'Ce mouvement est deja effectue.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        mouvement.status = 'effectue'
        mouvement.valide_par = request.user
        mouvement.date_validation = timezone.now()
        mouvement.save()
        return Response(
            {'detail': f'Mouvement {mouvement.reference} valide et soldes mis a jour.'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='sync-comptabilite')
    def sync_comptabilite(self, request, pk=None):
        mouvement = self.get_object()

        if mouvement.status != 'effectue':
            return Response(
                {'detail': 'Seuls les mouvements effectues peuvent etre synchronises.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            from finances.models import EcritureComptable

            existing = EcritureComptable.objects.filter(
                reference=mouvement.reference,
                type='tresorerie'
            ).first()

            if existing:
                return Response({
                    'detail': 'Ecriture deja existante',
                    'ecriture_id': existing.id,
                    'numero': existing.numero,
                    'created': False
                })

            from finances.signals import creer_ecriture_depuis_mouvement
            creer_ecriture_depuis_mouvement(
                sender=MouvementTresorerie,
                instance=mouvement,
                created=False
            )

            ecriture = EcritureComptable.objects.filter(
                reference=mouvement.reference,
                type='tresorerie'
            ).first()

            if ecriture:
                return Response({
                    'detail': 'Ecriture creee avec succes',
                    'ecriture_id': ecriture.id,
                    'numero': ecriture.numero,
                    'created': True
                })
            else:
                return Response(
                    {'detail': "Echec de la creation de l'ecriture. Verifiez les logs."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except ImportError as e:
            return Response(
                {'error': f"Module finances indisponible : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'], url_path='ecriture')
    def get_ecriture(self, request, pk=None):
        mouvement = self.get_object()

        try:
            from finances.models import EcritureComptable

            ecriture = (
                EcritureComptable.objects
                .select_related('compte_debit', 'compte_credit')
                .filter(
                    reference=mouvement.reference,
                    type='tresorerie'
                )
                .first()
            )

            if ecriture:
                return Response({
                    'has_ecriture': True,
                    'ecriture': {
                        'id': ecriture.id,
                        'numero': ecriture.numero,
                        'date_ecriture': ecriture.date_ecriture,
                        'compte_debit': ecriture.compte_debit.numero,
                        'compte_debit_nom': ecriture.compte_debit.nom,
                        'compte_credit': ecriture.compte_credit.numero,
                        'compte_credit_nom': ecriture.compte_credit.nom,
                        'montant': str(ecriture.montant),
                        'total': str(ecriture.total),
                        'statut': ecriture.statut,
                        'description': ecriture.description,
                    }
                })
            else:
                return Response({
                    'has_ecriture': False,
                    'ecriture': None
                })

        except ImportError:
            return Response({
                'has_ecriture': False,
                'ecriture': None,
                'error': 'Module finances indisponible'
            })


# ============================================================
# FRAIS VIEWSET
# ============================================================

class FraisViewSet(viewsets.ModelViewSet):
    serializer_class = FraisSerializer
    pagination_class = FraisPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'categorie', 'status']
    search_fields = ['reference', 'titre', 'beneficiaire']
    ordering_fields = ['date_frais', 'montant', 'created_at']

    def get_queryset(self):
        return (
            Frais.objects
            .select_related('warehouse', 'created_by', 'valide_par')
            .order_by('-date_frais')
        )

    @action(detail=True, methods=['post'])
    def payer(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'paye':
            return Response(
                {'detail': 'Ce frais est deja paye.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        frais.status = 'paye'
        frais.date_paiement = timezone.now().date()
        frais.save()
        return Response(
            {'detail': f'Frais {frais.reference} marque comme paye, mouvement genere.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# PREVISION TRESORERIE VIEWSET
# ============================================================

class PrevisionTresorerieViewSet(viewsets.ModelViewSet):
    serializer_class = PrevisionTresorerieSerializer
    pagination_class = PrevisionPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_prevision', 'periode', 'statut']
    search_fields = ['reference', 'titre']
    ordering_fields = ['date_debut', 'montant_prevu']

    def get_queryset(self):
        return (
            PrevisionTresorerie.objects
            .select_related('warehouse', 'created_by')
            .order_by('-date_debut')
        )


# ============================================================
# RAPPROCHEMENT BANCAIRE VIEWSET
# ============================================================

class RapprochementBancaireViewSet(viewsets.ModelViewSet):
    serializer_class = RapprochementBancaireSerializer
    pagination_class = RapprochementPagination
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'compte_bancaire', 'status']
    search_fields = ['reference']
    ordering_fields = ['date_fin', 'created_at']

    def get_queryset(self):
        return (
            RapprochementBancaire.objects
            .select_related(
                'warehouse',
                'compte_bancaire',
                'compte_bancaire__warehouse',
                'created_by',
                'valide_par',
            )
            .order_by('-date_fin')
        )

    @action(detail=True, methods=['post'])
    def valider_rapprochement(self, request, pk=None):
        rapprochement = self.get_object()
        if rapprochement.status == 'complete':
            return Response(
                {'detail': 'Ce rapprochement est deja complet.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if abs(rapprochement.ecart) < 1:
            rapprochement.status = 'complete'
        else:
            rapprochement.status = 'ecart'
        rapprochement.valide_par = request.user
        rapprochement.date_validation = timezone.now()
        rapprochement.save()
        return Response(
            {'detail': f'Rapprochement {rapprochement.reference} mis a jour.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# TRESORERIE JOURNALIERE VIEWSET
# ============================================================

class TresorerieJournaliereViewSet(viewsets.ModelViewSet):
    serializer_class = TresorerieJournaliereSerializer
    pagination_class = TresorerieJournalierePagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'date']
    ordering_fields = ['date']

    def get_queryset(self):
        return (
            TresorerieJournaliere.objects
            .select_related('warehouse')
            .order_by('-date')
        )

    @action(detail=False, methods=['post'])
    def generer(self, request):
        from datetime import datetime

        date_str = request.data.get('date')
        if date_str:
            try:
                date_jour = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'detail': 'Format de date invalide. Utilisez YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            date_jour = timezone.now().date()

        warehouse_id = request.data.get('warehouse')
        if not warehouse_id:
            return Response(
                {'detail': 'Le champ "warehouse" est obligatoire.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        obj, created = TresorerieJournaliere.objects.get_or_create(
            date=date_jour,
            warehouse_id=warehouse_id
        )
        obj.generer_journaliere(date_jour)
        serializer = self.get_serializer(obj)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================
# DASHBOARD TRESORERIE VIEWSET
# ============================================================

class TresorerieDashboardViewSet(viewsets.ViewSet):
    """
    ViewSet pour les statistiques du tableau de bord de tresorerie.
    Toutes les requetes sont optimisees avec aggregate/annotate.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        # Recuperer tous les entrepots actifs
        warehouses = Warehouse.objects.filter(is_active=True)

        # Soldes des caisses actives (1 requete)
        caisses_qs = Caisse.objects.filter(is_active=True)
        total_caisses = caisses_qs.aggregate(
            total=Coalesce(Sum('solde_actuel'), Value(
                0, output_field=DecimalField()))
        )['total'] or 0
        nb_caisses = caisses_qs.count()

        # Soldes des comptes bancaires actifs (1 requete)
        comptes_qs = CompteBancaire.objects.filter(is_active=True)
        total_comptes = comptes_qs.aggregate(
            total=Coalesce(Sum('solde_actuel'), Value(
                0, output_field=DecimalField()))
        )['total'] or 0
        nb_comptes = comptes_qs.count()

        total_global = total_caisses + total_comptes

        # 10 derniers mouvements effectues (1 requete avec select_related)
        mouvements_recents = (
            MouvementTresorerie.objects
            .select_related('caisse', 'compte_bancaire')
            .filter(status='effectue')
            .order_by('-date_mouvement')[:10]
        )

        mouvements_data = [
            {
                'reference': mvmt.reference,
                'type': mvmt.type_mouvement,
                'montant': str(mvmt.montant),
                'date': mvmt.date_mouvement.strftime('%Y-%m-%d %H:%M'),
                'libelle': mvmt.libelle,
                'caisse': mvmt.caisse.nom if mvmt.caisse else None,
                'compte': mvmt.compte_bancaire.nom if mvmt.compte_bancaire else None,
            }
            for mvmt in mouvements_recents
        ]

        # Entrees et sorties du jour (2 requetes)
        today = timezone.now().date()
        mouvements_jour = MouvementTresorerie.objects.filter(
            status='effectue',
            date_mouvement__date=today
        )

        entree_total_jour = mouvements_jour.filter(
            type_mouvement='encaissement'
        ).aggregate(
            total=Coalesce(Sum('montant'), Value(
                0, output_field=DecimalField()))
        )['total'] or 0

        sortie_total_jour = mouvements_jour.filter(
            type_mouvement='decaissement'
        ).aggregate(
            total=Coalesce(Sum('montant'), Value(
                0, output_field=DecimalField()))
        )['total'] or 0

        # Soldes par entrepot - OPTIMISE : 2 requetes au lieu de 2*N
        warehouse_ids = list(warehouses.values_list('id', flat=True))

        caisses_par_wh = {
            row['warehouse_id']: row['total']
            for row in Caisse.objects.filter(
                warehouse_id__in=warehouse_ids,
                is_active=True
            ).values('warehouse_id').annotate(
                total=Coalesce(Sum('solde_actuel'), Value(
                    0, output_field=DecimalField()))
            )
        }

        comptes_par_wh = {
            row['warehouse_id']: row['total']
            for row in CompteBancaire.objects.filter(
                warehouse_id__in=warehouse_ids,
                is_active=True
            ).values('warehouse_id').annotate(
                total=Coalesce(Sum('solde_actuel'), Value(
                    0, output_field=DecimalField()))
            )
        }

        soldes_par_entrepot = []
        for wh in warehouses:
            total_caisses_wh = caisses_par_wh.get(wh.id, 0)
            total_comptes_wh = comptes_par_wh.get(wh.id, 0)
            soldes_par_entrepot.append({
                'warehouse_id': wh.id,
                'warehouse_name': wh.name,
                'total_caisses': total_caisses_wh,
                'total_comptes': total_comptes_wh,
                'total': total_caisses_wh + total_comptes_wh,
            })

        data = {
            'total_soldes_caisses': total_caisses,
            'total_soldes_comptes': total_comptes,
            'total_global': total_global,
            'nb_caisses': nb_caisses,
            'nb_comptes': nb_comptes,
            'mouvements_recents': mouvements_data,
            'entree_total_jour': entree_total_jour,
            'sortie_total_jour': sortie_total_jour,
            'soldes_par_entrepot': soldes_par_entrepot,
        }

        serializer = TresorerieDashboardSerializer(data)
        return Response(serializer.data)
