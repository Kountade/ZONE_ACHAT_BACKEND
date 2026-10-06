from django.shortcuts import render

# Create your views here.
# apps/finances/views.py
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import date, timedelta
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
    DashboardFinancierSerializer
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
        """Marque une dépense comme payée"""
        depense = self.get_object()

        if depense.statut != 'approuve':
            return Response(
                {"error": "Seules les dépenses approuvées peuvent être payées"},
                status=status.HTTP_400_BAD_REQUEST
            )

        depense.payer(request.user)

        return Response({
            'status': depense.statut,
            'message': 'Dépense marquée comme payée',
            'reference': depense.reference,
            'date_paiement': depense.date_paiement
        })

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
        depense.save()

        return Response({
            'status': depense.statut,
            'message': 'Dépense rejetée',
            'reference': depense.reference
        })


# ============================================================
# BUDGET VIEWSET
# ============================================================

class BudgetViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des budgets"""
    queryset = Budget.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]

    def get_serializer_class(self):
        if self.action in ['create']:
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
        """Met à jour le montant utilisé du budget"""
        budget = self.get_object()
        budget.update_utilise()

        return Response({
            'id': budget.id,
            'nom': budget.nom,
            'montant_total': budget.montant_total,
            'montant_utilise': budget.montant_utilise,
            'montant_restant': budget.montant_restant,
            'pourcentage_utilise': (budget.montant_utilise / budget.montant_total * 100) if budget.montant_total > 0 else 0
        })


class BudgetCategorieViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des catégories de budget"""
    queryset = BudgetCategorie.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsComptable]
    serializer_class = BudgetCategorieSerializer


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
