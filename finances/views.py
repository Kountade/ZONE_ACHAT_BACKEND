import logging
import datetime as dt                          # ✅ LIGNE À AJOUTER
from datetime import date, timedelta
from decimal import Decimal

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db.models import (
    Q, Sum, Count, Avg, F, ExpressionWrapper, DecimalField
)
from django.utils import timezone
from django.shortcuts import get_object_or_404

from .models import (
    CompteComptable,
    EcritureComptable,
    Depense,
    Budget,
    BudgetCategorie,
    BudgetLigne,
    RapportFinancier,
    ConfigurationFinanciere
)

# ⚠️ NE PAS IMPORTER Tresorerie depuis finances.models
# Utiliser tresorerie.models si nécessaire

from .serializers import (
    CompteComptableSerializer,
    CompteComptableCreateSerializer,
    EcritureComptableSerializer,
    EcritureComptableCreateSerializer,
    DepenseSerializer,
    DepenseCreateSerializer,
    DepenseApprouveSerializer,
    BudgetCategorieSerializer,
    BudgetSerializer,
    BudgetCreateSerializer,
    RapportFinancierSerializer,
    RapportFinancierCreateSerializer,
    ConfigurationFinanciereSerializer,
    DashboardFinancierSerializer,
    EcritureComptableLiteSerializer
)
from users.permissions import IsAdmin, IsGestionnaire, IsComptable


# ============================================================
# COMPTE COMPTABLE VIEWSET
# ============================================================

class CompteComptableViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des comptes comptables"""
    queryset = CompteComptable.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CompteComptableCreateSerializer
        return CompteComptableSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(numero__icontains=search) |
                Q(nom__icontains=search) |
                Q(nom_complet__icontains=search)
            )

        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        classe = self.request.query_params.get('classe')
        if classe:
            queryset = queryset.filter(classe=classe)

        is_active = self.request.query_params.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        ordering = self.request.query_params.get('ordering', 'numero')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """Récupère les sous-comptes d'un compte"""
        compte = self.get_object()
        children = compte.children.all()
        serializer = CompteComptableSerializer(children, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def ecritures(self, request, pk=None):
        """Récupère les écritures liées à un compte"""
        compte = self.get_object()
        ecritures = EcritureComptable.objects.filter(
            Q(compte_debit=compte) | Q(compte_credit=compte)
        ).order_by('-date_ecriture')
        serializer = EcritureComptableSerializer(ecritures, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def update_solde(self, request, pk=None):
        """Met à jour le solde d'un compte"""
        compte = self.get_object()
        compte.update_solde()
        return Response({
            'id': compte.id,
            'numero': compte.numero,
            'nom': compte.nom,
            'solde': compte.solde,
            'solde_formate': f"{compte.solde:,.0f} FCFA"
        })


# ============================================================
# ÉCRITURE COMPTABLE VIEWSET
# ============================================================

class EcritureComptableViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des écritures comptables"""
    queryset = EcritureComptable.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def get_serializer_class(self):
        if self.action in ['create']:
            return EcritureComptableCreateSerializer
        return EcritureComptableSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(numero__icontains=search) |
                Q(description__icontains=search) |
                Q(reference__icontains=search)
            )

        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date_ecriture__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date_ecriture__lte=date_to)

        compte = self.request.query_params.get('compte')
        if compte:
            queryset = queryset.filter(
                Q(compte_debit_id=compte) | Q(compte_credit_id=compte)
            )

        ordering = self.request.query_params.get('ordering', '-date_ecriture')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        """Valide une écriture comptable"""
        ecriture = self.get_object()

        if ecriture.statut == 'valide':
            return Response(
                {"error": "Cette écriture est déjà validée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ecriture.valider(request.user)

        return Response({
            'status': ecriture.statut,
            'message': 'Écriture validée avec succès',
            'numero': ecriture.numero
        })

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        """Annule une écriture comptable"""
        ecriture = self.get_object()

        if ecriture.statut == 'annulee':
            return Response(
                {"error": "Cette écriture est déjà annulée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ecriture.statut = 'annulee'
        ecriture.save()

        return Response({
            'status': ecriture.statut,
            'message': 'Écriture annulée avec succès',
            'numero': ecriture.numero
        })


# ============================================================
# DÉPENSE VIEWSET
# ============================================================

# apps/finances/views.py - PARTIE DepenseViewSet

class DepenseViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des dépenses"""
    queryset = Depense.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action in ['create']:
            return DepenseCreateSerializer
        return DepenseSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) |
                Q(description__icontains=search) |
                Q(supplier_name__icontains=search)
            )

        categorie = self.request.query_params.get('categorie')
        if categorie:
            queryset = queryset.filter(categorie=categorie)

        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date_depense__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date_depense__lte=date_to)

        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)

        ordering = self.request.query_params.get('ordering', '-date_depense')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def approuver(self, request, pk=None):
        """Approuve une dépense"""
        depense = self.get_object()

        if depense.statut != 'en_attente':
            return Response(
                {"error": "Seules les dépenses en attente peuvent être approuvées"},
                status=status.HTTP_400_BAD_REQUEST
            )

        depense.approuver(request.user)

        return Response({
            'status': depense.statut,
            'message': 'Dépense approuvée avec succès',
            'reference': depense.reference
        })

    @action(detail=True, methods=['post'])
    def payer(self, request, pk=None):
        """
        ✅ Marque la dépense payée et déclenche :
        - Le mouvement de trésorerie (décaissement)
        - L'écriture comptable automatique
        """
        depense = self.get_object()

        if depense.statut == 'paye':
            return Response(
                {"error": "Cette dépense est déjà payée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if depense.statut not in ['en_attente', 'approuve']:
            return Response(
                {"error": f"Impossible de payer une dépense au statut '{depense.get_statut_display()}'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = depense.payer(request.user)

            depense.refresh_from_db()

            return Response({
                'status': depense.statut,
                'message': 'Dépense payée — Mouvement et écriture comptable créés',
                'reference': depense.reference,
                'date_paiement': depense.date_paiement,
                'mouvement_id': depense.tresorerie_id,
                'ecriture_id': depense.ecriture_id,
                'errors': result.get('errors', []),
            })
        except Exception as e:
            return Response(
                {"error": f"Erreur lors du paiement : {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def rejeter(self, request, pk=None):
        """Rejette une dépense"""
        depense = self.get_object()

        if depense.statut not in ['en_attente', 'approuve']:
            return Response(
                {"error": "Cette dépense ne peut pas être rejetée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        depense.statut = 'rejete'
        depense.save(update_fields=['statut', 'updated_at'])

        return Response({
            'status': depense.statut,
            'message': 'Dépense rejetée',
            'reference': depense.reference
        })

    @action(detail=True, methods=['post'])
    def synchroniser(self, request, pk=None):
        """
        ✅ Force la synchronisation : crée le mouvement de trésorerie
        et l'écriture comptable si absents.
        """
        depense = self.get_object()

        if depense.statut != 'paye':
            return Response(
                {"error": "La dépense doit être payée pour être synchronisée"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = depense.creer_mouvement_et_ecriture(request.user)
            depense.refresh_from_db()

            return Response({
                'message': 'Synchronisation effectuée',
                'mouvement_id': depense.tresorerie_id,
                'ecriture_id': depense.ecriture_id,
                'errors': result.get('errors', []),
            })
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# ============================================================
# BUDGET VIEWSET
# ============================================================

# ============================================================
# BUDGET VIEWSET
# ============================================================


class BudgetViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des budgets"""
    queryset = Budget.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def get_serializer_class(self):
        if self.action == 'create':
            return BudgetCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BudgetCreateSerializer
        return BudgetSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(nom__icontains=search)

        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        statut = self.request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date_debut__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date_fin__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-date_debut')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def update_utilise(self, request, pk=None):
        """Met à jour le montant utilisé du budget (recalcul depuis les lignes)"""
        budget = self.get_object()
        budget.update_utilise()

        return Response({
            'id': budget.id,
            'nom': budget.nom,
            'montant_total': budget.montant_total,
            'montant_utilise': budget.montant_utilise,
            'montant_restant': budget.montant_restant,
            'pourcentage_utilise': (
                budget.montant_utilise / budget.montant_total * 100
            ) if budget.montant_total > 0 else 0
        })

    @action(detail=True, methods=['get'])
    def alertes(self, request, pk=None):
        """Récupère les lignes du budget en alerte (>80%)"""
        budget = self.get_object()
        alertes = []

        for ligne in budget.lignes.all():
            if ligne.montant_prevu > 0:
                pourcentage = (ligne.montant_utilise /
                               ligne.montant_prevu) * 100
                if pourcentage >= 80:
                    alertes.append({
                        'ligne_id': ligne.id,
                        'categorie': ligne.categorie.nom,
                        'categorie_depense': ligne.categorie.categorie_depense,
                        'montant_prevu': float(ligne.montant_prevu),
                        'montant_utilise': float(ligne.montant_utilise),
                        'montant_restant': float(ligne.montant_restant),
                        'pourcentage': round(pourcentage, 2),
                    })

        return Response({
            'budget_id': budget.id,
            'budget_nom': budget.nom,
            'nb_alertes': len(alertes),
            'alertes': alertes
        })

    @action(detail=False, methods=['get'])
    def actifs(self, request):
        """Liste des budgets actuellement en cours"""
        today = timezone.now().date()
        budgets = Budget.objects.filter(
            statut='en_cours',
            date_debut__lte=today,
            date_fin__gte=today
        )
        serializer = BudgetSerializer(budgets, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cloturer(self, request, pk=None):
        """Clôture un budget (le passe en 'termine')"""
        budget = self.get_object()

        if budget.statut == 'termine':
            return Response(
                {"error": "Ce budget est déjà clôturé"},
                status=status.HTTP_400_BAD_REQUEST
            )

        budget.statut = 'termine'
        budget.save(update_fields=['statut', 'updated_at'])

        return Response({
            'status': budget.statut,
            'message': f'Budget "{budget.nom}" clôturé avec succès',
            'montant_utilise': budget.montant_utilise,
            'montant_restant': budget.montant_restant,
        })


class BudgetCategorieViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des catégories de budget"""
    queryset = BudgetCategorie.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]
    serializer_class = BudgetCategorieSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(nom__icontains=search) | Q(code__icontains=search)
            )

        is_active = self.request.query_params.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        return queryset

    @action(detail=False, methods=['get'])
    def non_liees(self, request):
        """Liste les catégories de budget non liées à une catégorie de dépense"""
        categories = self.get_queryset().filter(categorie_depense__isnull=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

# ============================================================
# RAPPORT FINANCIER VIEWSET
# ============================================================


class RapportFinancierViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des rapports financiers"""
    queryset = RapportFinancier.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def get_serializer_class(self):
        if self.action in ['create']:
            return RapportFinancierCreateSerializer
        return RapportFinancierSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(date_debut__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(date_fin__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-created_at')
        if ordering:
            queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ============================================================
# CONFIGURATION FINANCIÈRE VIEWSET
# ============================================================

class ConfigurationFinanciereViewSet(viewsets.ModelViewSet):
    """ViewSet pour la configuration financière"""
    queryset = ConfigurationFinanciere.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    serializer_class = ConfigurationFinanciereSerializer

    def get_queryset(self):
        # Une seule configuration
        return ConfigurationFinanciere.objects.all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


# ============================================================
# DASHBOARD FINANCIER VIEWSET
# ============================================================


# ============================================================
# JOURNAL COMPTABLE VIEWSET
# ============================================================
class JournalComptableViewSet(viewsets.ViewSet):
    """
    Journal comptable : liste chronologique de toutes les écritures.
    ✅ CORRIGÉ : pas de @action sur list()
    """
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def list(self, request):
        """Liste paginée des écritures comptables."""
        queryset = (
            EcritureComptable.objects
            .select_related('compte_debit', 'compte_credit', 'created_by')
            .order_by('date_ecriture', 'id')
        )

        # Filtres
        date_from = request.query_params.get('date_from')
        if date_from:
            try:
                date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
                queryset = queryset.filter(
                    date_ecriture__gte=date_start.date())
            except ValueError:
                pass

        date_to = request.query_params.get('date_to')
        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
                queryset = queryset.filter(date_ecriture__lte=date_end.date())
            except ValueError:
                pass

        compte = request.query_params.get('compte')
        if compte:
            queryset = queryset.filter(
                Q(compte_debit_id=compte) | Q(compte_credit_id=compte)
            )

        type_filter = request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        statut = request.query_params.get('statut')
        if statut:
            queryset = queryset.filter(statut=statut)

        # Totaux (calculés avant pagination)
        totals = queryset.aggregate(
            total_debit=Sum('montant'),
            total_credit=Sum('montant'),
        )
        total_count = queryset.count()

        # Pagination manuelle
        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1

        try:
            page_size = min(
                int(request.query_params.get('page_size', 50)), 200
            )
        except (TypeError, ValueError):
            page_size = 50

        start = (page - 1) * page_size
        end = start + page_size
        page_qs = queryset[start:end]

        serializer = EcritureComptableLiteSerializer(page_qs, many=True)

        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size,
            'total_debit': float(totals['total_debit'] or 0),
            'total_credit': float(totals['total_credit'] or 0),
            'results': serializer.data,
        })


# ============================================================
# GRAND LIVRE VIEWSET
# ============================================================
class GrandLivreViewSet(viewsets.ViewSet):
    """
    Grand livre : détail des mouvements par compte comptable.
    ✅ CORRIGÉ : pas de @action sur list()
    """
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def list(self, request):
        """Retourne le grand livre groupé par compte."""
        compte_id = request.query_params.get('compte')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        comptes_qs = CompteComptable.objects.filter(is_active=True)

        if compte_id:
            comptes_qs = comptes_qs.filter(id=compte_id)

        # Pré-calcul des bornes de date
        date_start = None
        date_end = None

        if date_from:
            try:
                date_start = dt.datetime.strptime(
                    date_from, '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                pass

        result = []

        for compte in comptes_qs.order_by('numero'):
            # Base : écritures validées
            base_qs = EcritureComptable.objects.filter(statut='valide')

            if date_start:
                base_qs = base_qs.filter(date_ecriture__gte=date_start)
            if date_end:
                base_qs = base_qs.filter(date_ecriture__lte=date_end)

            # Débits
            ecritures_debit = list(
                base_qs.filter(compte_debit=compte)
                .values('id', 'numero', 'date_ecriture', 'description',
                        'montant', 'reference')
            )

            # Crédits
            ecritures_credit = list(
                base_qs.filter(compte_credit=compte)
                .values('id', 'numero', 'date_ecriture', 'description',
                        'montant', 'reference')
            )

            mouvements = []

            for e in ecritures_debit:
                mouvements.append({
                    'id': e['id'],
                    'numero': e['numero'],
                    'date': e['date_ecriture'],
                    'description': e['description'],
                    'debit': float(e['montant']),
                    'credit': 0,
                    'reference': e.get('reference', ''),
                })

            for e in ecritures_credit:
                mouvements.append({
                    'id': e['id'],
                    'numero': e['numero'],
                    'date': e['date_ecriture'],
                    'description': e['description'],
                    'debit': 0,
                    'credit': float(e['montant']),
                    'reference': e.get('reference', ''),
                })

            # Tri chronologique
            mouvements.sort(key=lambda x: (x['date'], x['id']))

            if not mouvements:
                continue

            # Solde progressif
            solde = float(compte.solde_initial or 0)
            for m in mouvements:
                solde += m['debit'] - m['credit']
                m['solde'] = solde

            total_debit = sum(m['debit'] for m in mouvements)
            total_credit = sum(m['credit'] for m in mouvements)

            result.append({
                'compte_id': compte.id,
                'numero': compte.numero,
                'nom': compte.nom,
                'solde_initial': float(compte.solde_initial or 0),
                'total_debit': total_debit,
                'total_credit': total_credit,
                'solde_final': solde,
                'mouvements': mouvements,
            })

        return Response({
            'count': len(result),
            'results': result,
        })


# ============================================================
# BALANCE GÉNÉRALE VIEWSET
# ============================================================
class BalanceGeneraleViewSet(viewsets.ViewSet):
    """
    Balance générale : synthèse de tous les comptes.
    ✅ CORRIGÉ : pas de @action sur list()
    """
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def list(self, request):
        """Retourne la balance générale avec équilibre."""
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        # Pré-calcul des bornes
        date_start = None
        date_end = None

        if date_from:
            try:
                date_start = dt.datetime.strptime(
                    date_from, '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Base commune
        base_qs = EcritureComptable.objects.filter(statut='valide')
        if date_start:
            base_qs = base_qs.filter(date_ecriture__gte=date_start)
        if date_end:
            base_qs = base_qs.filter(date_ecriture__lte=date_end)

        # Agrégations par compte (2 requêtes au total)
        debits = (
            base_qs
            .values('compte_debit_id')
            .annotate(total=Sum('montant'))
        )
        credits = (
            base_qs
            .values('compte_credit_id')
            .annotate(total=Sum('montant'))
        )

        debit_map = {row['compte_debit_id']: float(
            row['total'] or 0) for row in debits}
        credit_map = {row['compte_credit_id']: float(
            row['total'] or 0) for row in credits}

        comptes = CompteComptable.objects.filter(
            is_active=True).order_by('numero')

        result = []
        total_debit_general = 0.0
        total_credit_general = 0.0
        total_solde_debiteur = 0.0
        total_solde_crediteur = 0.0

        for compte in comptes:
            total_debit = debit_map.get(compte.id, 0.0)
            total_credit = credit_map.get(compte.id, 0.0)

            if total_debit == 0 and total_credit == 0:
                continue

            solde = total_debit - total_credit
            solde_debiteur = max(solde, 0)
            solde_crediteur = max(-solde, 0)

            total_debit_general += total_debit
            total_credit_general += total_credit
            total_solde_debiteur += solde_debiteur
            total_solde_crediteur += solde_crediteur

            result.append({
                'compte_id': compte.id,
                'numero': compte.numero,
                'nom': compte.nom,
                'type': compte.type,
                'classe': compte.classe,
                'total_debit': total_debit,
                'total_credit': total_credit,
                'solde': solde,
                'solde_debiteur': solde_debiteur,
                'solde_crediteur': solde_crediteur,
            })

        return Response({
            'count': len(result),
            'totaux': {
                'total_debit': total_debit_general,
                'total_credit': total_credit_general,
                'total_solde_debiteur': total_solde_debiteur,
                'total_solde_crediteur': total_solde_crediteur,
                'equilibre': abs(
                    total_debit_general - total_credit_general
                ) < 0.01,
            },
            'results': result,
        })


class DashboardFinancierViewSet(viewsets.ViewSet):
    """ViewSet pour le dashboard financier"""
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Statistiques financières pour le dashboard"""
        today = date.today()
        start_of_month = today.replace(day=1)
        start_of_year = today.replace(month=1, day=1)

        # Calcul des totaux
        total_ventes = 0
        total_achats = 0
        total_depenses = 0
        solde_tresorerie = 0

        # Récupérer les données depuis les autres apps avec imports différés
        try:
            from ventes_clients.models import Vente
            total_ventes = Vente.objects.filter(
                status__in=['confirmed', 'paid', 'delivered'],
                sale_date__date__gte=start_of_month
            ).aggregate(total=Sum('total'))['total'] or 0
        except:
            pass

        try:
            from achats_fournisseurs.models import PurchaseOrder
            total_achats = PurchaseOrder.objects.filter(
                status__in=['confirmed', 'partial', 'received'],
                order_date__date__gte=start_of_month
            ).aggregate(total=Sum('total'))['total'] or 0
        except:
            pass

        try:
            # Récupérer les dépenses
            total_depenses = Depense.objects.filter(
                statut='paye',
                date_depense__gte=start_of_month
            ).aggregate(total=Sum('total'))['total'] or 0
        except:
            pass

        try:
            # Récupérer le solde de trésorerie
            from tresorerie.models import Caisse
            solde_tresorerie = Caisse.objects.filter(
                is_active=True
            ).aggregate(total=Sum('solde_actuel'))['total'] or 0
        except:
            pass

        # Calcul du bénéfice
        benefice = total_ventes - total_achats - total_depenses

        # Budget
        budgets = Budget.objects.filter(
            statut='en_cours'
        )
        budget_total = budgets.aggregate(
            total=Sum('montant_total'))['total'] or 0
        budget_utilise = budgets.aggregate(
            total=Sum('montant_utilise'))['total'] or 0
        budget_restant = budget_total - budget_utilise

        # Factures impayées
        factures_impayees = 0
        factures_echues = 0

        try:
            from achats_fournisseurs.models import SupplierInvoice
            factures_impayees = SupplierInvoice.objects.filter(
                paiement_status__in=['unpaid', 'partial', 'overdue']
            ).count()

            factures_echues = SupplierInvoice.objects.filter(
                due_date__lt=today,
                paiement_status__in=['unpaid', 'partial']
            ).count()
        except:
            pass

        # Alertes budget
        alertes_budget = []
        for budget in budgets:
            pourcentage = (budget.montant_utilise / budget.montant_total *
                           100) if budget.montant_total > 0 else 0
            if pourcentage > 80:
                alertes_budget.append({
                    'budget': budget.nom,
                    'pourcentage': pourcentage,
                    'montant_utilise': budget.montant_utilise,
                    'montant_total': budget.montant_total
                })

        data = {
            'total_ventes': total_ventes,
            'total_achats': total_achats,
            'total_depenses': total_depenses,
            'solde_tresorerie': solde_tresorerie,
            'benefice': benefice,
            'budget_utilise': budget_utilise,
            'budget_restant': budget_restant,
            'factures_impayees': factures_impayees,
            'factures_echues': factures_echues,
            'alertes_budget': alertes_budget
        }

        serializer = DashboardFinancierSerializer(data)
        return Response(serializer.data)
