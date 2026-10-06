# apps/tresorerie/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

# ============================================================
# SIGNALS POUR LA CRÉATION AUTOMATIQUE DE MOUVEMENTS
# ============================================================


@receiver(post_save, sender='ventes_clients.Vente')
def creer_mouvement_vente(sender, instance, created, **kwargs):
    """
    Crée un mouvement de trésorerie automatiquement lors de la création d'une vente
    """
    # ✅ CORRECTION : Utiliser source_type et source_id au lieu de mouvements_tresorerie
    try:
        from .models import MouvementTresorerie, Caisse

        # Vérifier si un mouvement existe déjà
        existing_movement = MouvementTresorerie.objects.filter(
            source_type='vente',
            source_id=instance.id
        ).first()

        if existing_movement:
            logger.info(
                f"Mouvement déjà existant pour la vente {instance.invoice_number}")
            return

        # Vérifier si la vente est confirmée ou payée
        if instance.status in ['confirmed', 'paid', 'delivered'] and instance.warehouse:
            # Récupérer la caisse par défaut
            caisse = Caisse.objects.filter(
                warehouse=instance.warehouse,
                is_default=True
            ).first()

            if caisse:
                # Créer le mouvement
                mouvement = MouvementTresorerie.objects.create(
                    type_mouvement='encaissement',
                    warehouse=instance.warehouse,
                    source_type='vente',
                    source_id=instance.id,
                    source_reference=instance.invoice_number,
                    montant=instance.total,
                    mode_paiement='especes',
                    caisse=caisse,
                    date_mouvement=instance.sale_date,
                    date_valeur=instance.sale_date.date(),
                    status='effectue',
                    libelle=f"Vente {instance.invoice_number} - {instance.client_name}",
                    created_by=instance.created_by
                )

                # Mettre à jour le solde de la caisse
                caisse.solde_actuel += instance.total
                caisse.save(update_fields=['solde_actuel', 'updated_at'])

                logger.info(
                    f"✅ Mouvement de trésorerie créé par signal pour la vente {instance.invoice_number}")
            else:
                logger.warning(
                    f"Aucune caisse par défaut pour l'entrepôt {instance.warehouse}")
        else:
            logger.info(
                f"Vente {instance.invoice_number} non confirmée, pas de mouvement créé")

    except Exception as e:
        logger.error(f"❌ Erreur dans le signal creer_mouvement_vente: {e}")


@receiver(post_save, sender='ventes_clients.Paiement')
def creer_mouvement_paiement(sender, instance, created, **kwargs):
    """
    Crée un mouvement de trésorerie automatiquement lors de la création d'un paiement
    """
    # ✅ CORRECTION : Utiliser source_type et source_id au lieu de mouvements_tresorerie
    try:
        from .models import MouvementTresorerie, Caisse, CompteBancaire

        if not created:
            return

        # Vérifier si un mouvement existe déjà
        existing_movement = MouvementTresorerie.objects.filter(
            source_type='paiement_client',
            source_id=instance.id
        ).first()

        if existing_movement:
            logger.info(
                f"Mouvement déjà existant pour le paiement {instance.id}")
            return

        # Récupérer la facture et la vente
        facture = instance.facture
        if not facture:
            logger.warning(f"Paiement {instance.id} sans facture")
            return

        sale = facture.sale
        if not sale:
            logger.warning(f"Paiement {instance.id} sans vente")
            return

        if not sale.warehouse:
            logger.warning(f"Paiement {instance.id} sans entrepôt")
            return

        # Récupérer la caisse ou le compte
        caisse = None
        compte = None

        if instance.caisse_destination_id:
            try:
                caisse = Caisse.objects.get(id=instance.caisse_destination_id)
            except Caisse.DoesNotExist:
                pass

        if instance.compte_destination_id:
            try:
                compte = CompteBancaire.objects.get(
                    id=instance.compte_destination_id)
            except CompteBancaire.DoesNotExist:
                pass

        # Si aucune destination, prendre la caisse par défaut
        if not caisse and not compte:
            caisse = Caisse.objects.filter(
                warehouse=sale.warehouse,
                is_default=True
            ).first()

        if not caisse and not compte:
            logger.warning(
                f"Aucune destination pour le paiement {instance.id}")
            return

        # Créer le mouvement
        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='encaissement',
            warehouse=sale.warehouse,
            source_type='paiement_client',
            source_id=instance.id,
            source_reference=instance.reference or f"PAY-{instance.id}",
            montant=instance.amount,
            mode_paiement=instance.method,
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=instance.payment_date,
            date_valeur=instance.payment_date.date(),
            status='effectue',
            libelle=f"Paiement vente {sale.invoice_number} - {sale.client_name}",
            created_by=instance.received_by
        )

        # Mettre à jour le solde de la caisse
        if caisse:
            caisse.solde_actuel += instance.amount
            caisse.save(update_fields=['solde_actuel', 'updated_at'])
            logger.info(
                f" Caisse {caisse.nom} augmentée de {instance.amount:,.0f} FCFA")

        # Mettre à jour le solde du compte
        if compte:
            compte.solde_actuel += instance.amount
            compte.save(update_fields=['solde_actuel', 'updated_at'])
            logger.info(
                f" Compte {compte.nom} augmenté de {instance.amount:,.0f} FCFA")

        logger.info(
            f" Mouvement de trésorerie créé par signal pour le paiements {instance.id}")

    except Exception as e:
        logger.error(f" Erreur dans le signal creer_mouvement_paiement: {e}")
