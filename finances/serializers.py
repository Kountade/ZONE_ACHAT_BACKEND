# apps/finances/serializers.py
from rest_framework import serializers
from django.db import transaction
from decimal import Decimal
from datetime import date

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
# Tresorerie est maintenant dans tresorerie.models


class CompteComptableSerializer(serializers.ModelSerializer):
    """Serializer pour le plan comptable"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    classe_display = serializers.CharField(source='get_classe_display', read_only=True)
    parent_nom = serializers.CharField(source='parent.nom', read_only=True, allow_null=True)
    full_path = serializers.SerializerMethodField()
    solde_formate = serializers.SerializerMethodField()

    class Meta:
        model = CompteComptable
        fields = [
            'id', 'numero', 'nom', 'nom_complet', 'type', 'type_display',
            'classe', 'classe_display', 'parent', 'parent_nom', 'niveau',
            'solde', 'solde_formate', 'solde_initial', 'is_analytique',
            'is_budgetaire', 'is_active', 'is_imported', 'notes',
            'full_path', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'solde', 'created_at', 'updated_at']

    def get_full_path(self, obj):
        return obj.get_full_path()

    def get_solde_formate(self, obj):
        return f"{obj.solde:,.0f} FCFA"


class CompteComptableCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un compte comptable"""
    class Meta:
        model = CompteComptable
        fields = [
            'numero', 'nom', 'nom_complet', 'type', 'classe',
            'parent', 'niveau', 'solde_initial', 'is_analytique',
            'is_budgetaire', 'is_active', 'notes'
        ]

    def validate_numero(self, value):
        if CompteComptable.objects.filter(numero=value).exists():
            raise serializers.ValidationError("Ce numéro de compte existe déjà")
        return value


class EcritureComptableSerializer(serializers.ModelSerializer):
    """Serializer pour les écritures comptables"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    statut_display = serializers.CharField(source='get_statut_display', read_only=True)
    compte_debit_nom = serializers.CharField(source='compte_debit.nom', read_only=True)
    compte_credit_nom = serializers.CharField(source='compte_credit.nom', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    validated_by_name = serializers.CharField(source='validated_by.full_name', read_only=True)
    montant_formate = serializers.SerializerMethodField()
    total_formate = serializers.SerializerMethodField()

    # Informations liées (avec imports différés)
    vente_info = serializers.SerializerMethodField()
    facture_info = serializers.SerializerMethodField()
    paiement_info = serializers.SerializerMethodField()
    supplier_invoice_info = serializers.SerializerMethodField()
    purchase_order_info = serializers.SerializerMethodField()
    supplier_info = serializers.SerializerMethodField()
    client_info = serializers.SerializerMethodField()

    class Meta:
        model = EcritureComptable
        fields = [
            'id', 'numero', 'date_ecriture', 'date_comptable', 'date_echeance',
            'compte_debit', 'compte_debit_nom', 'compte_credit', 'compte_credit_nom',
            'montant', 'montant_formate', 'taxe', 'total', 'total_formate',
            'reference', 'type', 'type_display', 'statut', 'statut_display',
            'description', 'notes',
            'vente_id', 'facture_id', 'paiement_id', 'supplier_invoice_id',
            'purchase_order_id', 'supplier_id', 'client_id',
            'vente_info', 'facture_info', 'paiement_info',
            'supplier_invoice_info', 'purchase_order_info',
            'supplier_info', 'client_info',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'validated_by', 'validated_by_name', 'validated_at'
        ]
        read_only_fields = ['id', 'numero', 'date_comptable', 'created_at', 'updated_at']

    def get_montant_formate(self, obj):
        return f"{obj.montant:,.0f} FCFA"

    def get_total_formate(self, obj):
        return f"{obj.total:,.0f} FCFA"

    def get_vente_info(self, obj):
        vente = obj.get_vente()
        if vente:
            return {
                'id': vente.id,
                'invoice_number': vente.invoice_number,
                'client_name': vente.client_name
            }
        return None

    def get_facture_info(self, obj):
        facture = obj.get_facture()
        if facture:
            return {
                'id': facture.id,
                'invoice_number': facture.invoice_number,
                'client_name': facture.client.name if facture.client else None
            }
        return None

    def get_paiement_info(self, obj):
        paiement = obj.get_paiement()
        if paiement:
            return {
                'id': paiement.id,
                'reference': paiement.reference,
                'amount': paiement.amount
            }
        return None

    def get_supplier_invoice_info(self, obj):
        invoice = obj.get_supplier_invoice()
        if invoice:
            return {
                'id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'supplier_name': invoice.supplier.name if invoice.supplier else None
            }
        return None

    def get_purchase_order_info(self, obj):
        po = obj.get_purchase_order()
        if po:
            return {
                'id': po.id,
                'po_number': po.po_number,
                'supplier_name': po.supplier.name if po.supplier else None
            }
        return None

    def get_supplier_info(self, obj):
        supplier = obj.get_supplier()
        if supplier:
            return {
                'id': supplier.id,
                'name': supplier.name,
                'code': supplier.code
            }
        return None

    def get_client_info(self, obj):
        client = obj.get_client()
        if client:
            return {
                'id': client.id,
                'name': client.name,
                'code': client.code
            }
        return None


class EcritureComptableCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une écriture comptable"""
    class Meta:
        model = EcritureComptable
        fields = [
            'date_ecriture', 'date_echeance',
            'compte_debit', 'compte_credit',
            'montant', 'taxe',
            'reference', 'type',
            'description', 'notes',
            'vente_id', 'facture_id', 'paiement_id',
            'supplier_invoice_id', 'purchase_order_id',
            'supplier_id', 'client_id'
        ]

    def validate(self, data):
        compte_debit = data.get('compte_debit')
        compte_credit = data.get('compte_credit')
        
        if compte_debit == compte_credit:
            raise serializers.ValidationError(
                "Les comptes débit et crédit doivent être différents"
            )
        
        if data.get('montant', 0) <= 0:
            raise serializers.ValidationError(
                {"montant": "Le montant doit être supérieur à 0"}
            )
        
        return data

    @transaction.atomic
    def create(self, validated_data):
        user = self.context['request'].user
        
        # Générer le numéro d'écriture
        from datetime import datetime
        prefix = f"ECR{datetime.now().strftime('%Y%m')}"
        last = EcritureComptable.objects.filter(
            numero__startswith=prefix
        ).order_by('-id').first()
        
        if last:
            try:
                last_num = int(last.numero.replace(prefix, ''))
                numero = f"{prefix}{str(last_num + 1).zfill(4)}"
            except (ValueError, AttributeError):
                numero = f"{prefix}0001"
        else:
            numero = f"{prefix}0001"
        
        validated_data['numero'] = numero
        validated_data['created_by'] = user
        
        return super().create(validated_data)


class DepenseSerializer(serializers.ModelSerializer):
    """Serializer pour les dépenses"""
    categorie_display = serializers.CharField(source='get_categorie_display', read_only=True)
    statut_display = serializers.CharField(source='get_statut_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    approuve_par_name = serializers.CharField(source='approuve_par.full_name', read_only=True)
    montant_formate = serializers.SerializerMethodField()
    total_formate = serializers.SerializerMethodField()
    
    supplier_info = serializers.SerializerMethodField()
    purchase_order_info = serializers.SerializerMethodField()

    class Meta:
        model = Depense
        fields = [
            'id', 'reference', 'categorie', 'categorie_display',
            'description', 'montant', 'montant_formate', 'taxe',
            'total', 'total_formate', 'date_depense', 'date_echeance',
            'mode_paiement', 'reference_paiement', 'date_paiement',
            'supplier_id', 'supplier_name', 'supplier_info',
            'statut', 'statut_display', 'piece_jointe',
            'tresorerie_id', 'ecriture_id', 'purchase_order_id',
            'purchase_order_info', 'notes',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'approuve_par', 'approuve_par_name', 'approuve_le'
        ]
        read_only_fields = ['id', 'reference', 'created_at', 'updated_at']

    def get_montant_formate(self, obj):
        return f"{obj.montant:,.0f} FCFA"

    def get_total_formate(self, obj):
        return f"{obj.total:,.0f} FCFA"

    def get_supplier_info(self, obj):
        supplier = obj.get_supplier()
        if supplier:
            return {
                'id': supplier.id,
                'name': supplier.name,
                'code': supplier.code
            }
        return None

    def get_purchase_order_info(self, obj):
        po = obj.get_purchase_order()
        if po:
            return {
                'id': po.id,
                'po_number': po.po_number
            }
        return None


class DepenseCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'une dépense"""
    class Meta:
        model = Depense
        fields = [
            'categorie', 'description', 'montant', 'taxe',
            'date_depense', 'date_echeance', 'mode_paiement',
            'supplier_id', 'supplier_name', 'piece_jointe', 'notes'
        ]

    def validate_montant(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le montant doit être supérieur à 0")
        return value


class DepenseApprouveSerializer(serializers.Serializer):
    """Serializer pour l'approbation d'une dépense"""
    approuve = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True)


class BudgetCategorieSerializer(serializers.ModelSerializer):
    """Serializer pour les catégories de budget"""
    class Meta:
        model = BudgetCategorie
        fields = ['id', 'nom', 'description', 'code', 'is_active']
        read_only_fields = ['id']


class BudgetLigneSerializer(serializers.ModelSerializer):
    """Serializer pour les lignes de budget"""
    categorie_nom = serializers.CharField(source='categorie.nom', read_only=True)
    montant_prevu_formate = serializers.SerializerMethodField()
    montant_utilise_formate = serializers.SerializerMethodField()
    montant_restant_formate = serializers.SerializerMethodField()
    pourcentage_utilise = serializers.SerializerMethodField()

    class Meta:
        model = BudgetLigne
        fields = [
            'id', 'categorie', 'categorie_nom',
            'montant_prevu', 'montant_prevu_formate',
            'montant_utilise', 'montant_utilise_formate',
            'montant_restant', 'montant_restant_formate',
            'pourcentage_utilise', 'notes'
        ]

    def get_montant_prevu_formate(self, obj):
        return f"{obj.montant_prevu:,.0f} FCFA"

    def get_montant_utilise_formate(self, obj):
        return f"{obj.montant_utilise:,.0f} FCFA"

    def get_montant_restant_formate(self, obj):
        return f"{obj.montant_restant:,.0f} FCFA"

    def get_pourcentage_utilise(self, obj):
        if obj.montant_prevu > 0:
            return (obj.montant_utilise / obj.montant_prevu) * 100
        return 0


class BudgetSerializer(serializers.ModelSerializer):
    """Serializer pour les budgets"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    statut_display = serializers.CharField(source='get_statut_display', read_only=True)
    lignes = BudgetLigneSerializer(many=True, read_only=True)
    montant_total_formate = serializers.SerializerMethodField()
    montant_utilise_formate = serializers.SerializerMethodField()
    montant_restant_formate = serializers.SerializerMethodField()
    pourcentage_utilise = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = Budget
        fields = [
            'id', 'nom', 'type', 'type_display',
            'montant_total', 'montant_total_formate',
            'montant_utilise', 'montant_utilise_formate',
            'montant_restant', 'montant_restant_formate',
            'pourcentage_utilise',
            'date_debut', 'date_fin', 'statut', 'statut_display',
            'categories', 'lignes', 'notes',
            'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_montant_total_formate(self, obj):
        return f"{obj.montant_total:,.0f} FCFA"

    def get_montant_utilise_formate(self, obj):
        return f"{obj.montant_utilise:,.0f} FCFA"

    def get_montant_restant_formate(self, obj):
        return f"{obj.montant_restant:,.0f} FCFA"

    def get_pourcentage_utilise(self, obj):
        if obj.montant_total > 0:
            return (obj.montant_utilise / obj.montant_total) * 100
        return 0


class BudgetCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un budget"""
    lignes = BudgetLigneSerializer(many=True, required=False)

    class Meta:
        model = Budget
        fields = [
            'nom', 'type', 'montant_total', 'date_debut',
            'date_fin', 'categories', 'lignes', 'notes'
        ]

    def validate(self, data):
        if data.get('date_debut') and data.get('date_fin'):
            if data['date_debut'] > data['date_fin']:
                raise serializers.ValidationError(
                    "La date de début doit être antérieure à la date de fin"
                )
        return data

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes', [])
        budget = Budget.objects.create(**validated_data)
        
        for ligne_data in lignes_data:
            BudgetLigne.objects.create(budget=budget, **ligne_data)
        
        budget.update_utilise()
        return budget


class RapportFinancierSerializer(serializers.ModelSerializer):
    """Serializer pour les rapports financiers"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    format_display = serializers.CharField(source='get_format_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = RapportFinancier
        fields = [
            'id', 'type', 'type_display', 'nom',
            'date_debut', 'date_fin', 'format', 'format_display',
            'contenu', 'fichier',
            'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']


class RapportFinancierCreateSerializer(serializers.ModelSerializer):
    """Serializer pour la création d'un rapport financier"""
    class Meta:
        model = RapportFinancier
        fields = ['type', 'nom', 'date_debut', 'date_fin', 'format']


class ConfigurationFinanciereSerializer(serializers.ModelSerializer):
    """Serializer pour la configuration financière"""
    updated_by_name = serializers.CharField(source='updated_by.full_name', read_only=True)

    class Meta:
        model = ConfigurationFinanciere
        fields = [
            'id', 'devise', 'devise_symbole',
            'exercice_debut', 'exercice_fin',
            'taxe_default', 'arrondi',
            'auto_validation', 'budget_alerte',
            'updated_at', 'updated_by', 'updated_by_name'
        ]
        read_only_fields = ['id']


class DashboardFinancierSerializer(serializers.Serializer):
    """Serializer pour le dashboard financier"""
    total_ventes = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_achats = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_depenses = serializers.DecimalField(max_digits=15, decimal_places=2)
    solde_tresorerie = serializers.DecimalField(max_digits=15, decimal_places=2)
    benefice = serializers.DecimalField(max_digits=15, decimal_places=2)
    budget_utilise = serializers.DecimalField(max_digits=15, decimal_places=2)
    budget_restant = serializers.DecimalField(max_digits=15, decimal_places=2)
    factures_impayees = serializers.IntegerField()
    factures_echues = serializers.IntegerField()
    alertes_budget = serializers.ListField(child=serializers.DictField())