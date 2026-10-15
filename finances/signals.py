# apps/finances/signals.py
"""
Signaux de synchronisation automatique :
- MouvementTresorerie → EcritureComptable
- Depense → MouvementTresorerie + EcritureComptable + Budget
"""
import logging
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============================================================
# 1. MOUVEMENT DE TRÉSORERIE → ÉCRITURE COMPTABLE
# ============================================================

@receiver(post_save, sender='tresorerie.MouvementTresorerie')
def creer_ecriture_depuis_mouvement(sender, instance, created, **kwargs):
    """
    Crée automatiquement une écriture comptable quand un mouvement
    de trésorerie est EFFECTUÉ.
    """
    if instance.status != 'effectue':
        return

    # Idempotence : pas de doublon
    from finances.models import EcritureComptable
    existing = EcritureComptable.objects.filter(
        reference=instance.reference,
        type='tresorerie'
    ).exists()
    if existing:
        return

    try:
        from finances.models import CompteComptable

        def get_compte(numero, nom, type_compte, classe):
            compte, _ = CompteComptable.objects.get_or_create(
                numero=numero,
                defaults={'nom': nom, 'type': type_compte, 'classe': classe}
            )
            return compte

        # Déterminer comptes débit/crédit selon type + source
        if instance.type_mouvement == 'encaissement':
            if instance.source_type == 'vente':
                compte_debit = get_compte('571', 'Caisse', 'actif', '5')
                compte_credit = get_compte(
                    '701', 'Ventes de marchandises', 'produits', '7')
            elif instance.source_type == 'paiement_client':
                compte_debit = get_compte('571', 'Caisse', 'actif', '5')
                compte_credit = get_compte('411', 'Clients', 'actif', '4')
            elif instance.source_type == 'wallet_deposit':
                compte_debit = get_compte('571', 'Caisse', 'actif', '5')
                compte_credit = get_compte(
                    '419', 'Clients - Avances reçues', 'passif', '4')
            else:
                compte_debit = get_compte('571', 'Caisse', 'actif', '5')
                compte_credit = get_compte(
                    '771', 'Produits exceptionnels', 'produits', '7')

        else:  # decaissement
            if instance.source_type == 'achat':
                compte_debit = get_compte(
                    '601', 'Achats de marchandises', 'charges', '6')
                compte_credit = get_compte('521', 'Banque', 'actif', '5')
            elif instance.source_type == 'frais':
                compte_debit = get_compte(
                    '628', 'Frais divers', 'charges', '6')
                compte_credit = get_compte('571', 'Caisse', 'actif', '5')
            elif instance.source_type == 'paiement_fournisseur':
                compte_debit = get_compte('401', 'Fournisseurs', 'passif', '4')
                compte_credit = get_compte('521', 'Banque', 'actif', '5')
            elif instance.source_type == 'depense':
                compte_debit = get_compte(
                    '658', 'Charges diverses', 'charges', '6')
                compte_credit = get_compte('571', 'Caisse', 'actif', '5')
            elif instance.source_type == 'avoir':
                compte_debit = get_compte(
                    '709', 'Rabais, remises, ristournes accordés', 'charges', '7')
                compte_credit = get_compte('571', 'Caisse', 'actif', '5')
            else:
                compte_debit = get_compte(
                    '658', 'Charges diverses', 'charges', '6')
                compte_credit = get_compte('571', 'Caisse', 'actif', '5')

        # Créer l'écriture
        ecriture = EcritureComptable.objects.create(
            numero=f"ECR-TRE-{timezone.now().strftime('%Y%m%d%H%M%S')}-{instance.id}",
            date_ecriture=instance.date_valeur or timezone.now().date(),
            compte_debit=compte_debit,
            compte_credit=compte_credit,
            montant=instance.montant,
            taxe=Decimal('0'),
            total=instance.montant,
            reference=instance.reference,
            type='tresorerie',
            statut='valide',
            description=f"[{instance.get_type_mouvement_display()}] {instance.libelle}",
            notes=f"Mouvement {instance.reference} - source: {instance.source_type}",
            created_by=instance.created_by,
            validated_by=instance.created_by,
            validated_at=timezone.now()
        )

        logger.info(f"✅ Écriture comptable créée : {ecriture.numero}")

    except Exception as e:
        logger.error(
            f"❌ Erreur création écriture depuis mouvement {instance.reference} : {e}")


# ============================================================
# 2. DÉPENSE PAYÉE → MOUVEMENT + ÉCRITURE
# ============================================================

@receiver(post_save, sender='finances.Depense')
def depense_payee_sync(sender, instance, created, **kwargs):
    """
    Si une dépense est sauvegardée avec statut 'paye' mais sans mouvement
    ni écriture, on les crée automatiquement.
    """
    if instance.statut != 'paye':
        return

    if instance.tresorerie_id and instance.ecriture_id:
        return  # Déjà synchronisé

    try:
        result = instance.creer_mouvement_et_ecriture(
            instance.approuve_par or instance.created_by
        )
        if result['errors']:
            logger.warning(
                f"⚠️ Synchronisation dépense {instance.reference} : {result['errors']}")
        else:
            logger.info(f"✅ Dépense {instance.reference} synchronisée")
    except Exception as e:
        logger.error(f"❌ Erreur sync dépense {instance.reference} : {e}")


# ============================================================
# 3. MISE À JOUR BUDGET SUR DÉPENSE PAYÉE (CORRIGÉ)
# ============================================================

@receiver(post_save, sender='finances.Depense')
def update_budget_on_depense(sender, instance, **kwargs):
    """
    ✅ CORRECTION : Met à jour les lignes de budget en cherchant par
    categorie_depense (code technique), pas par nom.

    Le lien est : 
        BudgetCategorie.categorie_depense == Depense.categorie
    """
    if instance.statut != 'paye':
        return

    try:
        from finances.models import Budget, BudgetLigne, BudgetCategorie

        today = timezone.now().date()

        # Récupérer les budgets actifs sur la période
        budgets = Budget.objects.filter(
            statut='en_cours',
            date_debut__lte=today,
            date_fin__gte=today
        )

        # ✅ Rechercher les catégories de budget liées à cette dépense
        categories_budget = BudgetCategorie.objects.filter(
            categorie_depense=instance.categorie,  # ← LIEN PAR CODE
            is_active=True
        )

        if not categories_budget.exists():
            logger.warning(
                f"⚠️ Aucune catégorie de budget liée à '{instance.categorie}' "
                f"pour la dépense {instance.reference}. "
                f"Créez une BudgetCategorie avec categorie_depense='{instance.categorie}'."
            )
            return

        # ✅ Mettre à jour les lignes de budget
        updated_count = 0
        for budget in budgets:
            lignes = budget.lignes.filter(
                categorie__in=categories_budget  # ← Filtre par FK
            )
            for ligne in lignes:
                ancien_montant = ligne.montant_utilise or Decimal('0')
                ligne.montant_utilise = ancien_montant + instance.total
                ligne.save()  # Déclenche update_utilise() du budget parent
                updated_count += 1

                logger.info(
                    f"✅ Budget '{budget.nom}' - Ligne '{ligne.categorie.nom}' : "
                    f"{ancien_montant:,.0f} → {ligne.montant_utilise:,.0f} FCFA "
                    f"(+{instance.total:,.0f})"
                )

        if updated_count == 0:
            logger.warning(
                f"⚠️ Dépense {instance.reference} payée mais aucune ligne de budget "
                f"n'a été mise à jour (aucun budget en cours ne contient la catégorie "
                f"'{instance.categorie}')."
            )

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour budget : {e}", exc_info=True)
