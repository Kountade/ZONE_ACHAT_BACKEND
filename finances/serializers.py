# apps/finances/serializers.py
# ============================================================
# SERIALIZERS COMPLET OPTIMISÉ
# ============================================================

from rest_framework import serializers
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
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


# ============================================================
# ✅ SERIALIZERS LITE (pour éviter N+1)
# ============================================================

class CompteComptableLiteSerializer(serializers.ModelSerializer):
    """Serializer ULTRA-LÉGER pour listes déroulantes."""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True
    )
    classe_display = serializers.CharField(
        source='get_classe_display', read_only=True
    )

    class Meta:
        model = CompteComptable
        fields = [
            'id', 'numero', 'nom', 'type', 'type_display',
            'classe', 'classe_display', 'is_active',
        ]
        read_only_fields = ['id']


class BudgetCategorieLiteSerializer(serializers.ModelSerializer):
    """Serializer léger pour les catégories de budget."""
    categorie_depense_display = serializers.CharField(
        source='get_categorie_depense_display', read_only=True
    )

    class Meta:
        model = BudgetCategorie
        fields = [
            'id', 'code', 'nom',
            'categorie_depense', 'categorie_depense_display',
            'is_active',
        ]
        read_only_fields = ['id']


class BudgetLiteSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes de budgets."""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True
    )
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True
    )
    pourcentage_utilise = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            'id', 'nom', 'type', 'type_display', 'statut', 'statut_display',
            'montant_total', 'montant_utilise', 'montant_restant',
            'pourcentage_utilise',
            'date_debut', 'date_fin',
        ]
        read_only_fields = ['id']

    def get_pourcentage_utilise(self, obj):
        if obj.montant_total > 0:
            return round((obj.montant_utilise / obj.montant_total) * 100, 2)
        return 0


class DepenseLiteSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes de dépenses."""
    categorie_display = serializers.CharField(
        source='get_categorie_display', read_only=True
    )
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True
    )

    class Meta:
        model = Depense
        fields = [
            'id', 'reference', 'categorie', 'categorie_display',
            'description', 'montant', 'total',
            'date_depense', 'statut', 'statut_display',
        ]
        read_only_fields = ['id']


class EcritureComptableLiteSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes d'écritures."""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True
    )
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True
    )
    compte_debit_nom = serializers.CharField(
        source='compte_debit.nom', read_only=True
    )
    compte_credit_nom = serializers.CharField(
        source='compte_credit.nom', read_only=True
    )

    class Meta:
        model = EcritureComptable
        fields = [
            'id', 'numero', 'date_ecriture',
            'compte_debit', 'compte_debit_nom',
            'compte_credit', 'compte_credit_nom',
            'montant', 'total', 'type', 'type_display',
            'statut', 'statut_display', 'reference',
        ]
        read_only_fields = ['id']


# ============================================================
# COMPTE COMPTABLE
# ============================================================

class CompteComptableSerializer(serializers.ModelSerializer):
    """Serializer pour le plan comptable"""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    classe_display = serializers.CharField(
        source='get_classe_display', read_only=True)
    parent_nom = serializers.CharField(
        source='parent.nom', read_only=True, allow_null=True)
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
        instance_id = self.instance.id if self.instance else None
        if CompteComptable.objects.exclude(id=instance_id).filter(
            numero=value
        ).exists():
            raise serializers.ValidationError(
                "Ce numéro de compte existe déjà"
            )
        return value


# ============================================================
# ÉCRITURE COMPTABLE
# ============================================================

class EcritureComptableSerializer(serializers.ModelSerializer):
    """Serializer pour les écritures comptables"""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True)
    compte_debit_nom = serializers.CharField(
        source='compte_debit.nom', read_only=True)
    compte_debit_numero = serializers.CharField(
        source='compte_debit.numero', read_only=True)
    compte_credit_nom = serializers.CharField(
        source='compte_credit.nom', read_only=True)
    compte_credit_numero = serializers.CharField(
        source='compte_credit.numero', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)
    validated_by_name = serializers.CharField(
        source='validated_by.full_name', read_only=True)
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
            'compte_debit', 'compte_debit_nom', 'compte_debit_numero',
            'compte_credit', 'compte_credit_nom', 'compte_credit_numero',
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
        read_only_fields = ['id', 'numero',
                            'date_comptable', 'created_at', 'updated_at']

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


# ============================================================
# DÉPENSE
# ============================================================

class DepenseSerializer(serializers.ModelSerializer):
    """Serializer pour les dépenses (lecture + détail)"""
    categorie_display = serializers.CharField(
        source='get_categorie_display', read_only=True)
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)
    approuve_par_name = serializers.CharField(
        source='approuve_par.full_name', read_only=True)
    montant_formate = serializers.SerializerMethodField()
    total_formate = serializers.SerializerMethodField()

    # ✅ Références trésorerie et comptabilité
    mouvement_reference = serializers.SerializerMethodField()
    mouvement_date = serializers.SerializerMethodField()
    ecriture_numero = serializers.SerializerMethodField()
    ecriture_date = serializers.SerializerMethodField()

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
            'tresorerie_id', 'mouvement_reference', 'mouvement_date',
            'ecriture_id', 'ecriture_numero', 'ecriture_date',
            'purchase_order_id', 'purchase_order_info', 'notes',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'approuve_par', 'approuve_par_name', 'approuve_le'
        ]
        read_only_fields = [
            'id', 'reference', 'created_at', 'updated_at',
            'tresorerie_id', 'ecriture_id', 'approuve_le'
        ]

    def get_montant_formate(self, obj):
        return f"{obj.montant:,.0f} FCFA"

    def get_total_formate(self, obj):
        return f"{obj.total:,.0f} FCFA"

    def get_mouvement_reference(self, obj):
        """Récupère la référence du mouvement de trésorerie associé"""
        if obj.tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie
                mvt = MouvementTresorerie.objects.get(id=obj.tresorerie_id)
                return mvt.reference
            except Exception:
                return None
        return None

    def get_mouvement_date(self, obj):
        """Récupère la date du mouvement associé"""
        if obj.tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie
                mvt = MouvementTresorerie.objects.get(id=obj.tresorerie_id)
                return mvt.date_mouvement
            except Exception:
                return None
        return None

    def get_ecriture_numero(self, obj):
        """Récupère le numéro de l'écriture comptable associée"""
        if obj.ecriture_id:
            try:
                ecriture = EcritureComptable.objects.get(id=obj.ecriture_id)
                return ecriture.numero
            except Exception:
                return None
        return None

    def get_ecriture_date(self, obj):
        """Récupère la date de l'écriture comptable"""
        if obj.ecriture_id:
            try:
                ecriture = EcritureComptable.objects.get(id=obj.ecriture_id)
                return ecriture.date_ecriture
            except Exception:
                return None
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
            'supplier_id', 'supplier_name', 'piece_jointe', 'notes',
            'purchase_order_id'
        ]

    def validate_montant(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0")
        return value


class DepenseApprouveSerializer(serializers.Serializer):
    """Serializer pour l'approbation d'une dépense"""
    approuve = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True)


# ============================================================
# BUDGET CATÉGORIE
# ============================================================

class BudgetCategorieSerializer(serializers.ModelSerializer):
    """Serializer pour les catégories de budget"""
    categorie_depense_display = serializers.CharField(
        source='get_categorie_depense_display',
        read_only=True
    )

    class Meta:
        model = BudgetCategorie
        fields = [
            'id', 'nom', 'description', 'code',
            'categorie_depense', 'categorie_depense_display',
            'is_active'
        ]
        read_only_fields = ['id']

    def validate_categorie_depense(self, value):
        """Vérifie qu'une seule catégorie de budget est liée à une catégorie de dépense"""
        if value:
            instance_id = self.instance.id if self.instance else None
            if BudgetCategorie.objects.exclude(id=instance_id).filter(
                categorie_depense=value
            ).exists():
                raise serializers.ValidationError(
                    f"Une autre catégorie de budget est déjà liée à '{value}'"
                )
        return value


# ============================================================
# BUDGET LIGNE
# ============================================================

class BudgetLigneSerializer(serializers.ModelSerializer):
    """Serializer pour les lignes de budget"""
    categorie_nom = serializers.CharField(
        source='categorie.nom', read_only=True)
    categorie_depense = serializers.CharField(
        source='categorie.categorie_depense', read_only=True)
    montant_prevu_formate = serializers.SerializerMethodField()
    montant_utilise_formate = serializers.SerializerMethodField()
    montant_restant_formate = serializers.SerializerMethodField()
    pourcentage_utilise = serializers.SerializerMethodField()

    class Meta:
        model = BudgetLigne
        fields = [
            'id', 'categorie', 'categorie_nom', 'categorie_depense',
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


# ============================================================
# BUDGET
# ============================================================

class BudgetSerializer(serializers.ModelSerializer):
    """Serializer pour les budgets"""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    statut_display = serializers.CharField(
        source='get_statut_display', read_only=True)
    lignes = BudgetLigneSerializer(many=True, read_only=True)
    montant_total_formate = serializers.SerializerMethodField()
    montant_utilise_formate = serializers.SerializerMethodField()
    montant_restant_formate = serializers.SerializerMethodField()
    pourcentage_utilise = serializers.SerializerMethodField()
    is_alerte = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

    class Meta:
        model = Budget
        fields = [
            'id', 'nom', 'type', 'type_display',
            'montant_total', 'montant_total_formate',
            'montant_utilise', 'montant_utilise_formate',
            'montant_restant', 'montant_restant_formate',
            'pourcentage_utilise', 'is_alerte',
            'date_debut', 'date_fin', 'statut', 'statut_display',
            'categories', 'lignes', 'notes',
            'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'montant_utilise', 'montant_restant',
                            'created_at', 'updated_at']

    def get_montant_total_formate(self, obj):
        return f"{obj.montant_total:,.0f} FCFA"

    def get_montant_utilise_formate(self, obj):
        return f"{obj.montant_utilise:,.0f} FCFA"

    def get_montant_restant_formate(self, obj):
        return f"{obj.montant_restant:,.0f} FCFA"

    def get_pourcentage_utilise(self, obj):
        if obj.montant_total > 0:
            return round((obj.montant_utilise / obj.montant_total) * 100, 2)
        return 0

    def get_is_alerte(self, obj):
        """Vérifie si le budget dépasse le seuil d'alerte (80% par défaut)"""
        if obj.montant_total > 0:
            pourcentage = (obj.montant_utilise / obj.montant_total) * 100
            return pourcentage >= 80
        return False


class BudgetCreateSerializer(serializers.ModelSerializer):
    """
    Serializer pour la création et modification d'un budget.

    ✅ CORRECTION :
    - created_by est retiré de validated_data avant create()
      pour éviter le TypeError "multiple values for keyword argument"
    - Idempotent sur update (protège les lignes déjà consommées)
    """

    lignes = BudgetLigneSerializer(many=True, required=False)

    class Meta:
        model = Budget
        fields = [
            'id', 'nom', 'type', 'montant_total', 'date_debut',
            'date_fin', 'categories', 'lignes', 'notes', 'statut'
        ]
        read_only_fields = ['id']

    # ============================================================
    # VALIDATION
    # ============================================================

    def validate_nom(self, value):
        """Vérifie que le nom n'est pas vide"""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "Le nom du budget est obligatoire"
            )
        return value.strip()

    def validate_montant_total(self, value):
        """Le montant total doit être positif"""
        if value is None or value <= 0:
            raise serializers.ValidationError(
                "Le montant total doit être supérieur à 0"
            )
        return value

    def validate(self, data):
        """Validation globale"""

        # 1. Vérifier les dates
        date_debut = data.get('date_debut')
        date_fin = data.get('date_fin')

        if date_debut and date_fin:
            if date_debut > date_fin:
                raise serializers.ValidationError({
                    'date_fin': "La date de fin doit être postérieure à la date de début"
                })

        # 2. Vérifier les lignes
        lignes = data.get('lignes', [])

        if lignes:
            # Vérifier les doublons de catégorie
            categories_ids = []
            for ligne in lignes:
                cat = ligne.get('categorie')
                if cat:
                    cat_id = cat.id if hasattr(cat, 'id') else cat
                    categories_ids.append(cat_id)

            if len(categories_ids) != len(set(categories_ids)):
                raise serializers.ValidationError({
                    'lignes': "Une catégorie ne peut apparaître qu'une seule fois dans le budget"
                })

            # Vérifier que les montants prévus sont positifs
            for i, ligne in enumerate(lignes):
                montant = ligne.get('montant_prevu', 0)
                if montant is None or montant <= 0:
                    raise serializers.ValidationError({
                        'lignes': f"Ligne {i+1} : le montant prévu doit être supérieur à 0"
                    })

        # 3. Vérifier la cohérence du montant total par rapport aux lignes
        montant_total = data.get('montant_total')
        if lignes and montant_total:
            total_lignes = sum(
                ligne.get('montant_prevu', 0) or 0
                for ligne in lignes
            )
            # ⚠️ Alerte seulement (pas bloquant) : tolérance de 1 FCFA
            if total_lignes > montant_total + 1:
                raise serializers.ValidationError({
                    'montant_total': (
                        f"La somme des lignes ({total_lignes:,.0f} FCFA) "
                        f"dépasse le montant total ({montant_total:,.0f} FCFA)"
                    )
                })

        return data

    # ============================================================
    # CREATE
    # ============================================================

    @transaction.atomic
    def create(self, validated_data):
        """
        Crée un nouveau budget avec ses lignes budgétaires.

        ✅ CORRECTION : On retire 'created_by' de validated_data
        pour éviter le conflit avec created_by=user
        """
        # 1. Extraire les lignes
        lignes_data = validated_data.pop('lignes', [])

        # 2. Extraire les catégories M2M (si présentes)
        categories_data = validated_data.pop('categories', None)

        # 3. ✅ SUPPRIMER created_by s'il est présent dans validated_data
        # (peut arriver si un perform_create le passe aussi)
        validated_data.pop('created_by', None)

        # 4. Récupérer l'utilisateur depuis le contexte
        request = self.context.get('request')
        user = request.user if request and request.user.is_authenticated else None

        # 5. Créer le budget
        budget = Budget.objects.create(
            created_by=user,
            **validated_data
        )

        # 6. Créer les lignes budgétaires
        for ligne_data in lignes_data:
            # Extraire la catégorie si c'est un objet
            categorie = ligne_data.pop('categorie', None)
            if categorie:
                BudgetLigne.objects.create(
                    budget=budget,
                    categorie=categorie,
                    **ligne_data
                )

        # 7. Ajouter les catégories M2M (via through, donc optionnel)
        if categories_data:
            budget.categories.set(categories_data)

        # 8. Recalculer les totaux
        budget.update_utilise()

        return budget

    # ============================================================
    # UPDATE
    # ============================================================

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Met à jour un budget existant.

        ⚠️ Protection : refuse la modification des lignes déjà consommées.
        """
        # 1. Extraire les lignes
        lignes_data = validated_data.pop('lignes', None)

        # 2. Extraire les catégories M2M
        categories_data = validated_data.pop('categories', None)

        # 3. ✅ SUPPRIMER created_by (il ne doit pas être modifié)
        validated_data.pop('created_by', None)

        # 4. Mettre à jour les champs simples
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # 5. Gérer les catégories M2M
        if categories_data is not None:
            instance.categories.set(categories_data)

        # 6. Gérer les lignes si fournies
        if lignes_data is not None:
            # 6.1 Vérifier qu'aucune ligne n'a été consommée
            for ligne in instance.lignes.all():
                if ligne.montant_utilise and ligne.montant_utilise > 0:
                    raise serializers.ValidationError({
                        'lignes': (
                            f"Impossible de modifier le budget : la ligne "
                            f"'{ligne.categorie.nom}' a déjà été utilisée "
                            f"({ligne.montant_utilise:,.0f} FCFA). "
                            f"Créez un nouveau budget à la place."
                        )
                    })

            # 6.2 Supprimer les anciennes lignes
            instance.lignes.all().delete()

            # 6.3 Créer les nouvelles lignes
            for ligne_data in lignes_data:
                categorie = ligne_data.pop('categorie', None)
                if categorie:
                    BudgetLigne.objects.create(
                        budget=instance,
                        categorie=categorie,
                        **ligne_data
                    )

        # 7. Recalculer les totaux
        instance.update_utilise()

        return instance


# ============================================================
# RAPPORT FINANCIER
# ============================================================

class RapportFinancierSerializer(serializers.ModelSerializer):
    """Serializer pour les rapports financiers"""
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    format_display = serializers.CharField(
        source='get_format_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

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


# ============================================================
# CONFIGURATION FINANCIÈRE
# ============================================================

class ConfigurationFinanciereSerializer(serializers.ModelSerializer):
    """Serializer pour la configuration financière"""
    updated_by_name = serializers.CharField(
        source='updated_by.full_name', read_only=True)

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


# ============================================================
# DASHBOARD FINANCIER
# ============================================================

class DashboardFinancierSerializer(serializers.Serializer):
    """Serializer pour le dashboard financier"""
    total_ventes = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_achats = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_depenses = serializers.DecimalField(max_digits=15, decimal_places=2)
    solde_tresorerie = serializers.DecimalField(
        max_digits=15, decimal_places=2)
    benefice = serializers.DecimalField(max_digits=15, decimal_places=2)
    budget_utilise = serializers.DecimalField(max_digits=15, decimal_places=2)
    budget_restant = serializers.DecimalField(max_digits=15, decimal_places=2)
    factures_impayees = serializers.IntegerField()
    factures_echues = serializers.IntegerField()
    alertes_budget = serializers.ListField(child=serializers.DictField())
