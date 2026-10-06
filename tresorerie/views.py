from django.shortcuts import render

# Create your views here.
# apps/tresorerie/views.py
from rest_framework import viewsets, status, filters, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import models
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
from produits_stocks.models import Warehouse


# ============================================================
# CAISSE VIEWSET
# ============================================================

class CaisseViewSet(viewsets.ModelViewSet):
    queryset = Caisse.objects.all()
    serializer_class = CaisseSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_caisse', 'is_active', 'is_default']
    search_fields = ['code', 'nom']
    ordering_fields = ['code', 'solde_actuel', 'created_at']


# ============================================================
# COMPTE BANCAIRE VIEWSET
# ============================================================

class CompteBancaireViewSet(viewsets.ModelViewSet):
    queryset = CompteBancaire.objects.all()
    serializer_class = CompteBancaireSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_compte', 'is_active', 'is_default']
    search_fields = ['banque', 'nom', 'numero_compte']
    ordering_fields = ['banque', 'solde_actuel']


# ============================================================
# MOUVEMENT TRÉSORERIE VIEWSET - CORRIGÉ
# ============================================================

class MouvementTresorerieViewSet(viewsets.ModelViewSet):
    queryset = MouvementTresorerie.objects.all()
    serializer_class = MouvementTresorerieSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]

    # ✅ CORRECTION : Supprimer les champs qui n'existent pas
    filterset_fields = [
        'warehouse',
        'type_mouvement',
        'source_type',
        'mode_paiement',
        'status',
        'caisse',
        'compte_bancaire',
        'rapproche'
        # ❌ Supprimer: 'vente', 'purchase_order', 'facture_vente', 'paiement'
    ]
    search_fields = ['reference', 'libelle',
                     'source_reference', 'reference_externe']
    ordering_fields = ['date_mouvement', 'montant', 'created_at']

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'annule':
            return Response(
                {'detail': 'Ce mouvement est déjà annulé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if mouvement.status != 'effectue':
            return Response(
                {'detail': 'Seul un mouvement effectué peut être annulé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        mouvement.annuler()
        return Response(
            {'detail': f'Mouvement {mouvement.reference} annulé avec succès.'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        mouvement = self.get_object()
        if mouvement.status == 'effectue':
            return Response(
                {'detail': 'Ce mouvement est déjà effectué.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        mouvement.status = 'effectue'
        mouvement.valide_par = request.user
        mouvement.date_validation = timezone.now()
        mouvement.save()
        return Response(
            {'detail': f'Mouvement {mouvement.reference} validé et soldes mis à jour.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# FRAIS VIEWSET
# ============================================================

class FraisViewSet(viewsets.ModelViewSet):
    queryset = Frais.objects.all()
    serializer_class = FraisSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    # ❌ Supprimer 'supplier' si n'existe pas
    filterset_fields = ['warehouse', 'categorie', 'status']
    search_fields = ['reference', 'titre', 'beneficiaire']
    ordering_fields = ['date_frais', 'montant', 'created_at']

    @action(detail=True, methods=['post'])
    def payer(self, request, pk=None):
        frais = self.get_object()
        if frais.status == 'paye':
            return Response(
                {'detail': 'Ce frais est déjà payé.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        frais.status = 'paye'
        frais.date_paiement = timezone.now().date()
        frais.save()
        return Response(
            {'detail': f'Frais {frais.reference} marqué comme payé, mouvement généré.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# PRÉVISION TRÉSORERIE VIEWSET
# ============================================================

class PrevisionTresorerieViewSet(viewsets.ModelViewSet):
    queryset = PrevisionTresorerie.objects.all()
    serializer_class = PrevisionTresorerieSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'type_prevision', 'periode', 'statut']
    search_fields = ['reference', 'titre']
    ordering_fields = ['date_debut', 'montant_prevu']


# ============================================================
# RAPPROCHEMENT BANCAIRE VIEWSET
# ============================================================

class RapprochementBancaireViewSet(viewsets.ModelViewSet):
    queryset = RapprochementBancaire.objects.all()
    serializer_class = RapprochementBancaireSerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'compte_bancaire', 'status']
    search_fields = ['reference']
    ordering_fields = ['date_fin', 'created_at']

    @action(detail=True, methods=['post'])
    def valider_rapprochement(self, request, pk=None):
        rapprochement = self.get_object()
        if rapprochement.status == 'complete':
            return Response(
                {'detail': 'Ce rapprochement est déjà complet.'},
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
            {'detail': f'Rapprochement {rapprochement.reference} mis à jour.'},
            status=status.HTTP_200_OK
        )


# ============================================================
# TRÉSORERIE JOURNALIÈRE VIEWSET
# ============================================================

class TresorerieJournaliereViewSet(viewsets.ModelViewSet):
    queryset = TresorerieJournaliere.objects.all()
    serializer_class = TresorerieJournaliereSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'date']
    ordering_fields = ['date']

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
# DASHBOARD TRÉSORERIE VIEWSET
# ============================================================

class TresorerieDashboardViewSet(viewsets.ViewSet):
    """
    ViewSet pour les statistiques du tableau de bord de trésorerie
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        # Récupérer tous les entrepôts actifs
        warehouses = Warehouse.objects.filter(is_active=True)

        # Soldes des caisses actives
        caisses = Caisse.objects.filter(is_active=True)
        total_caisses = caisses.aggregate(
            total=models.Sum('solde_actuel')
        )['total'] or 0

        # Soldes des comptes bancaires actifs
        comptes = CompteBancaire.objects.filter(is_active=True)
        total_comptes = comptes.aggregate(
            total=models.Sum('solde_actuel')
        )['total'] or 0

        total_global = total_caisses + total_comptes
        nb_caisses = caisses.count()
        nb_comptes = comptes.count()

        # 10 derniers mouvements effectués
        mouvements_recents = MouvementTresorerie.objects.filter(
            status='effectue'
        ).order_by('-date_mouvement')[:10]

        mouvements_data = []
        for mvmt in mouvements_recents:
            mouvements_data.append({
                'reference': mvmt.reference,
                'type': mvmt.type_mouvement,
                'montant': str(mvmt.montant),
                'date': mvmt.date_mouvement.strftime('%Y-%m-%d %H:%M'),
                'libelle': mvmt.libelle,
                'caisse': mvmt.caisse.nom if mvmt.caisse else None,
                'compte': mvmt.compte_bancaire.nom if mvmt.compte_bancaire else None,
            })

        # Entrées et sorties du jour
        today = timezone.now().date()
        mouvements_jour = MouvementTresorerie.objects.filter(
            status='effectue',
            date_mouvement__date=today
        )
        entree_total_jour = mouvements_jour.filter(
            type_mouvement='encaissement'
        ).aggregate(
            total=models.Sum('montant')
        )['total'] or 0

        sortie_total_jour = mouvements_jour.filter(
            type_mouvement='decaissement'
        ).aggregate(
            total=models.Sum('montant')
        )['total'] or 0

        # Soldes par entrepôt
        soldes_par_entrepot = []
        for wh in warehouses:
            total_caisses_wh = Caisse.objects.filter(
                warehouse=wh, is_active=True
            ).aggregate(
                total=models.Sum('solde_actuel')
            )['total'] or 0

            total_comptes_wh = CompteBancaire.objects.filter(
                warehouse=wh, is_active=True
            ).aggregate(
                total=models.Sum('solde_actuel')
            )['total'] or 0

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
