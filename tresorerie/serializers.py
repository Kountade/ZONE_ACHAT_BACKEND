# apps/tresorerie/serializers.py
from rest_framework import serializers
from django.utils import timezone
from decimal import Decimal
from django.db import models

from .models import (
    Caisse, CompteBancaire, MouvementTresorerie, Frais,
    PrevisionTresorerie, RapprochementBancaire, TresorerieJournaliere
)


# ----------------------------------------------
# 1. CAISSES
# ----------------------------------------------
class CaisseSerializer(serializers.ModelSerializer):
    est_sous_seuil_min = serializers.BooleanField(read_only=True)
    est_sur_seuil_max = serializers.BooleanField(read_only=True)
    total_mouvements = serializers.IntegerField(read_only=True)
    solde_actuel_formate = serializers.SerializerMethodField()
    solde_initial_formate = serializers.SerializerMethodField()

    class Meta:
        model = Caisse
        fields = [
            'id', 'code', 'nom', 'type_caisse', 'warehouse', 'responsable',
            'solde_initial', 'solde_initial_formate', 'solde_actuel', 'solde_actuel_formate',
            'seuil_min', 'seuil_max',
            'devise', 'is_active', 'is_default', 'description',
            'est_sous_seuil_min', 'est_sur_seuil_max', 'total_mouvements',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['solde_actuel',
                            'created_at', 'updated_at', 'created_by']

    def get_solde_actuel_formate(self, obj):
        return f"{obj.solde_actuel:,.0f} FCFA"

    def get_solde_initial_formate(self, obj):
        return f"{obj.solde_initial:,.0f} FCFA"

    def validate(self, data):
        if data.get('is_default', False):
            warehouse = data.get('warehouse')
            if warehouse and Caisse.objects.filter(
                warehouse=warehouse, is_default=True
            ).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise serializers.ValidationError(
                    {"is_default": "Une caisse par défaut existe déjà pour cet entrepôt."}
                )
        return data


# ----------------------------------------------
# 2. COMPTES BANCAIRES
# ----------------------------------------------
class CompteBancaireSerializer(serializers.ModelSerializer):
    solde_actuel_formate = serializers.SerializerMethodField()
    solde_initial_formate = serializers.SerializerMethodField()

    class Meta:
        model = CompteBancaire
        fields = [
            'id', 'banque', 'code', 'nom', 'type_compte', 'warehouse',
            'numero_compte', 'iban', 'bic', 'devise',
            'solde_initial', 'solde_initial_formate', 'solde_actuel', 'solde_actuel_formate',
            'is_active', 'is_default', 'date_ouverture', 'description',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['solde_actuel',
                            'created_at', 'updated_at', 'created_by']

    def get_solde_actuel_formate(self, obj):
        return f"{obj.solde_actuel:,.0f} FCFA"

    def get_solde_initial_formate(self, obj):
        return f"{obj.solde_initial:,.0f} FCFA"


# ----------------------------------------------
# 3. MOUVEMENTS DE TRÉSORERIE - CORRIGÉ
# ----------------------------------------------
class MouvementTresorerieSerializer(serializers.ModelSerializer):
    # Champs en lecture seule pour l'affichage
    est_encaissement = serializers.BooleanField(read_only=True)
    est_decaissement = serializers.BooleanField(read_only=True)
    est_transfert = serializers.BooleanField(read_only=True)
    montant_formate = serializers.SerializerMethodField()
    caisse_nom = serializers.CharField(
        source='caisse.nom', read_only=True, allow_null=True)
    compte_bancaire_nom = serializers.CharField(
        source='compte_bancaire.nom', read_only=True, allow_null=True
    )
    warehouse_nom = serializers.CharField(
        source='warehouse.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, allow_null=True)
    valide_par_name = serializers.CharField(
        source='valide_par.full_name', read_only=True, allow_null=True)

    class Meta:
        model = MouvementTresorerie
        fields = [
            'id', 'reference', 'type_mouvement', 'warehouse', 'warehouse_nom',
            'source_type', 'source_id', 'source_reference',
            'montant', 'montant_formate', 'mode_paiement',
            'caisse', 'caisse_nom', 'compte_bancaire', 'compte_bancaire_nom',
            'date_mouvement', 'date_valeur', 'date_prevue',
            'status', 'reference_externe', 'piece_justificative',
            'date_rapprochement', 'rapproche',
            'libelle', 'notes',
            # ❌ SUPPRIMER CES CHAMPS : 'vente', 'purchase_order', 'facture_vente', 'paiement'
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'valide_par', 'valide_par_name', 'date_validation',
            'est_encaissement', 'est_decaissement', 'est_transfert'
        ]
        read_only_fields = [
            'reference', 'date_rapprochement', 'rapproche',
            'created_at', 'updated_at', 'created_by', 'valide_par', 'date_validation'
        ]

    def get_montant_formate(self, obj):
        return f"{obj.montant:,.0f} FCFA"

    def validate(self, data):
        # Un mouvement doit être lié soit à une caisse, soit à un compte bancaire
        if not data.get('caisse') and not data.get('compte_bancaire'):
            raise serializers.ValidationError(
                "Vous devez spécifier une caisse ou un compte bancaire."
            )

        # Vérifier que le montant est positif
        if data.get('montant', 0) <= 0:
            raise serializers.ValidationError(
                {"montant": "Le montant doit être supérieur à 0."}
            )

        return data

    def create(self, validated_data):
        # La référence est générée automatiquement par le modèle
        if 'status' not in validated_data:
            validated_data['status'] = 'planifie'

        mouvement = MouvementTresorerie.objects.create(**validated_data)

        if mouvement.status == 'effectue':
            mouvement._mettre_a_jour_soldes()

        return mouvement

    def update(self, instance, validated_data):
        # Si on passe le statut à 'effectué', on met à jour les soldes
        if validated_data.get('status') == 'effectue' and instance.status != 'effectue':
            instance.type_mouvement = validated_data.get(
                'type_mouvement', instance.type_mouvement)
            instance.montant = validated_data.get('montant', instance.montant)
            instance.caisse = validated_data.get('caisse', instance.caisse)
            instance.compte_bancaire = validated_data.get(
                'compte_bancaire', instance.compte_bancaire)
            instance._mettre_a_jour_soldes()

        return super().update(instance, validated_data)


# ----------------------------------------------
# 4. MOUVEMENT TRÉSORERIE - CREATE
# ----------------------------------------------
class MouvementTresorerieCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MouvementTresorerie
        fields = [
            'type_mouvement', 'warehouse', 'source_type', 'source_id',
            'source_reference', 'montant', 'mode_paiement',
            'caisse', 'compte_bancaire', 'date_mouvement', 'date_valeur',
            'date_prevue', 'status', 'reference_externe', 'piece_justificative',
            'libelle', 'notes'
        ]

    def validate(self, data):
        if not data.get('caisse') and not data.get('compte_bancaire'):
            raise serializers.ValidationError(
                "Vous devez spécifier une caisse ou un compte bancaire."
            )

        if data.get('montant', 0) <= 0:
            raise serializers.ValidationError(
                {"montant": "Le montant doit être supérieur à 0."}
            )

        return data


# ----------------------------------------------
# 5. FRAIS
# ----------------------------------------------
# apps/tresorerie/serializers.py
# Modifier FraisSerializer

class FraisSerializer(serializers.ModelSerializer):
    montant_formate = serializers.SerializerMethodField()
    warehouse_nom = serializers.CharField(
        source='warehouse.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True, allow_null=True)
    valide_par_name = serializers.CharField(
        source='valide_par.full_name', read_only=True, allow_null=True)

    # ✅ CORRECTION : Utiliser un SerializerMethodField au lieu d'un champ direct
    mouvement_reference = serializers.SerializerMethodField()
    supplier_name = serializers.SerializerMethodField()

    class Meta:
        model = Frais
        fields = [
            'id', 'reference', 'titre', 'warehouse', 'warehouse_nom', 'categorie',
            'montant', 'montant_formate', 'date_frais', 'date_paiement', 'beneficiaire',
            'piece_justificative', 'mode_paiement',
            # ❌ SUPPRIMER 'mouvement' car il n'existe pas dans le modèle
            'mouvement_reference',  # ✅ Utiliser ce champ à la place
            'supplier_id', 'supplier_name',
            'status', 'notes',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'valide_par', 'valide_par_name', 'date_validation'
        ]
        read_only_fields = ['reference',
                            'created_at', 'updated_at', 'created_by']

    def get_montant_formate(self, obj):
        return f"{obj.montant:,.0f} FCFA"

    def get_supplier_name(self, obj):
        if obj.supplier_id:
            try:
                from achats_fournisseurs.models import Supplier
                supplier = Supplier.objects.get(id=obj.supplier_id)
                return supplier.name
            except:
                return None
        return None

    def get_mouvement_reference(self, obj):
        """Récupère la référence du mouvement associé via l'ID"""
        if obj.mouvement_id:
            try:
                from tresorerie.models import MouvementTresorerie
                mouvement = MouvementTresorerie.objects.get(
                    id=obj.mouvement_id)
                return mouvement.reference
            except:
                return None
        return None

# ----------------------------------------------
# 6. FRAIS - CREATE
# ----------------------------------------------


class FraisCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Frais
        fields = [
            'titre', 'warehouse', 'categorie', 'montant',
            'date_frais', 'beneficiaire', 'piece_justificative',
            'mode_paiement', 'supplier_id', 'notes'
        ]

    def validate_montant(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0.")
        return value


# ----------------------------------------------
# 7. PRÉVISIONS
# ----------------------------------------------
class PrevisionTresorerieSerializer(serializers.ModelSerializer):
    montant_prevu_formate = serializers.SerializerMethodField()
    montant_reel_formate = serializers.SerializerMethodField()
    ecart_formate = serializers.SerializerMethodField()
    warehouse_nom = serializers.CharField(
        source='warehouse.name', read_only=True, allow_null=True)

    class Meta:
        model = PrevisionTresorerie
        fields = [
            'id', 'reference', 'titre', 'warehouse', 'warehouse_nom',
            'type_prevision', 'periode',
            'montant_prevu', 'montant_prevu_formate',
            'montant_reel', 'montant_reel_formate',
            'date_debut', 'date_fin',
            'source_type', 'source_id',
            'categorie', 'sous_categorie',
            'statut', 'probabilite',
            'ecart', 'ecart_formate', 'pourcentage_ecart',
            'notes',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['reference', 'ecart', 'pourcentage_ecart',
                            'created_at', 'updated_at', 'created_by']

    def get_montant_prevu_formate(self, obj):
        return f"{obj.montant_prevu:,.0f} FCFA"

    def get_montant_reel_formate(self, obj):
        return f"{obj.montant_reel:,.0f} FCFA"

    def get_ecart_formate(self, obj):
        return f"{obj.ecart:,.0f} FCFA"


# ----------------------------------------------
# 8. RAPPROCHEMENT BANCAIRE
# ----------------------------------------------
class RapprochementBancaireSerializer(serializers.ModelSerializer):
    est_rapproche = serializers.BooleanField(read_only=True)
    solde_comptable_formate = serializers.SerializerMethodField()
    solde_bancaire_formate = serializers.SerializerMethodField()
    solde_rapproche_formate = serializers.SerializerMethodField()
    ecart_formate = serializers.SerializerMethodField()

    class Meta:
        model = RapprochementBancaire
        fields = [
            'id', 'reference', 'warehouse', 'compte_bancaire',
            'date_debut', 'date_fin',
            'solde_comptable', 'solde_comptable_formate',
            'solde_bancaire', 'solde_bancaire_formate',
            'solde_rapproche', 'solde_rapproche_formate',
            'ecart', 'ecart_formate', 'status',
            'encours_emission', 'encours_encaissement',
            'commissions', 'autres_ecarts',
            'notes',
            'created_at', 'updated_at', 'created_by',
            'valide_par', 'date_validation',
            'est_rapproche'
        ]
        read_only_fields = ['reference', 'solde_rapproche',
                            'ecart', 'created_at', 'updated_at', 'created_by']

    def get_solde_comptable_formate(self, obj):
        return f"{obj.solde_comptable:,.0f} FCFA"

    def get_solde_bancaire_formate(self, obj):
        return f"{obj.solde_bancaire:,.0f} FCFA"

    def get_solde_rapproche_formate(self, obj):
        return f"{obj.solde_rapproche:,.0f} FCFA"

    def get_ecart_formate(self, obj):
        return f"{obj.ecart:,.0f} FCFA"


# ----------------------------------------------
# 9. TRÉSORERIE JOURNALIÈRE
# ----------------------------------------------
class TresorerieJournaliereSerializer(serializers.ModelSerializer):
    variation = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)
    variation_formate = serializers.SerializerMethodField()
    solde_ouverture_formate = serializers.SerializerMethodField()
    solde_fermeture_formate = serializers.SerializerMethodField()
    total_entrees_formate = serializers.SerializerMethodField()
    total_sorties_formate = serializers.SerializerMethodField()

    # ✅ NOUVEAUX CHAMPS DÉTAILLÉS
    frais_details = serializers.SerializerMethodField()
    entrees_details = serializers.SerializerMethodField()
    sorties_details = serializers.SerializerMethodField()

    class Meta:
        model = TresorerieJournaliere
        fields = [
            'id', 'date', 'warehouse',
            'solde_ouverture', 'solde_ouverture_formate',
            'solde_fermeture', 'solde_fermeture_formate',
            'total_entrees', 'total_entrees_formate',
            'total_sorties', 'total_sorties_formate',
            'entrees_ventes', 'entrees_reglements', 'entrees_autres',
            'sorties_achats', 'sorties_frais', 'sorties_salaires', 'sorties_autres',
            'nb_operations', 'nb_entrees', 'nb_sorties',
            'variation', 'variation_formate',
            # ✅ Détails
            'frais_details', 'entrees_details', 'sorties_details',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_variation_formate(self, obj):
        return f"{obj.variation:,.0f} FCFA"

    def get_solde_ouverture_formate(self, obj):
        return f"{obj.solde_ouverture:,.0f} FCFA"

    def get_solde_fermeture_formate(self, obj):
        return f"{obj.solde_fermeture:,.0f} FCFA"

    def get_total_entrees_formate(self, obj):
        return f"{obj.total_entrees:,.0f} FCFA"

    def get_total_sorties_formate(self, obj):
        return f"{obj.total_sorties:,.0f} FCFA"

    def _serialize_mouvements(self, mouvements):
        """Sérialise une liste de dictionnaires de mouvements"""
        result = []
        for m in mouvements:
            item = {}
            for k, v in m.items():
                if hasattr(v, 'strftime'):
                    item[k] = v.strftime('%Y-%m-%d %H:%M')
                elif hasattr(v, '__float__') and not isinstance(v, (str, int)):
                    item[k] = str(v)
                else:
                    item[k] = v
            result.append(item)
        return result

    def get_frais_details(self, obj):
        return self._serialize_mouvements(obj.get_frais_du_jour())

    def get_entrees_details(self, obj):
        return self._serialize_mouvements(obj.get_entrees_du_jour())

    def get_sorties_details(self, obj):
        return self._serialize_mouvements(obj.get_sorties_du_jour())

# ----------------------------------------------
# 10. DASHBOARD TRÉSORERIE
# ----------------------------------------------
# apps/tresorerie/serializers.py
# Modifier la méthode to_representation de TresorerieDashboardSerializer

# apps/tresorerie/serializers.py - Partie TresorerieDashboardSerializer COMPLETE


class TresorerieDashboardSerializer(serializers.Serializer):
    """
    Sérialiseur pour les statistiques du tableau de bord de trésorerie
    """
    total_soldes_caisses = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, default=0
    )
    total_soldes_comptes = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, default=0
    )
    total_global = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, default=0
    )
    nb_caisses = serializers.IntegerField(required=False, default=0)
    nb_comptes = serializers.IntegerField(required=False, default=0)
    mouvements_recents = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    entree_total_jour = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, default=0
    )
    sortie_total_jour = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, default=0
    )
    soldes_par_entrepot = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )

    # Champs formatés (en lecture seule)
    total_soldes_caisses_formate = serializers.SerializerMethodField()
    total_soldes_comptes_formate = serializers.SerializerMethodField()
    total_global_formate = serializers.SerializerMethodField()
    entree_total_jour_formate = serializers.SerializerMethodField()
    sortie_total_jour_formate = serializers.SerializerMethodField()

    def get_total_soldes_caisses_formate(self, obj):
        return self._safe_format(obj.get('total_soldes_caisses', 0))

    def get_total_soldes_comptes_formate(self, obj):
        return self._safe_format(obj.get('total_soldes_comptes', 0))

    def get_total_global_formate(self, obj):
        return self._safe_format(obj.get('total_global', 0))

    def get_entree_total_jour_formate(self, obj):
        return self._safe_format(obj.get('entree_total_jour', 0))

    def get_sortie_total_jour_formate(self, obj):
        return self._safe_format(obj.get('sortie_total_jour', 0))

    def _safe_format(self, value, default=0):
        """
        Formate une valeur en chaîne de caractères avec séparateurs de milliers
        """
        try:
            if value is None:
                return f"{default:,.0f} FCFA"
            if isinstance(value, str):
                value = value.replace(',', '').replace(' ', '')
            val = float(value)
            return f"{val:,.0f} FCFA"
        except (ValueError, TypeError, AttributeError):
            return f"{default:,.0f} FCFA"

    def to_representation(self, instance):
        """
        Convertit l'instance en dictionnaire avec des valeurs formatées
        """
        # S'assurer que toutes les clés existent
        default_data = {
            'total_soldes_caisses': 0,
            'total_soldes_comptes': 0,
            'total_global': 0,
            'nb_caisses': 0,
            'nb_comptes': 0,
            'mouvements_recents': [],
            'entree_total_jour': 0,
            'sortie_total_jour': 0,
            'soldes_par_entrepot': [],
        }

        # Mettre à jour avec les données de l'instance
        if isinstance(instance, dict):
            default_data.update(instance)
        elif hasattr(instance, '__dict__'):
            for key in default_data.keys():
                if hasattr(instance, key):
                    default_data[key] = getattr(instance, key)

        # Appeler le parent pour avoir la représentation de base
        data = super().to_representation(default_data)

        return data
