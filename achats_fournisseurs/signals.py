# apps/achats_fournisseurs/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from .models import Receipt, SupplierInvoice


@receiver(post_save, sender=Receipt)
def create_invoice_on_receipt_completion(sender, instance, created, **kwargs):
    """
    ✅ Crée automatiquement une facture fournisseur lorsque la réception est terminée
    et que auto_invoice est True
    """
    # Vérifier que la réception est terminée, non facturée et que auto_invoice est activé
    if (instance.status == 'completed' and
        not instance.is_invoiced and
            instance.auto_invoice):

        try:
            purchase_order = instance.purchase_order
            supplier = purchase_order.supplier

            # Calculer le montant total reçu
            total_amount = instance.total_received_amount

            if total_amount <= 0:
                # Pas de montant à facturer
                return

            # Générer un numéro de facture automatique
            year = date.today().year
            last_invoice = SupplierInvoice.objects.filter(
                invoice_number__startswith=f"FAC-AUTO-{year}-"
            ).order_by('-id').first()

            if last_invoice:
                try:
                    num = int(last_invoice.invoice_number.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1

            auto_invoice_number = f"FAC-AUTO-{year}-{num:04d}"

            # Calculer la date d'échéance (par défaut 30 jours)
            due_date = date.today() + timedelta(days=30)

            # Créer la facture
            invoice = SupplierInvoice.objects.create(
                invoice_number=auto_invoice_number,
                purchase_order=purchase_order,
                supplier=supplier,
                invoice_date=date.today(),
                due_date=due_date,
                amount=total_amount,
                tax_amount=Decimal('0'),
                total_amount=total_amount,
                amount_paid=Decimal('0'),
                status='received',
                paiement_status='unpaid',
                is_fully_paid=False,
                notes=f"Facture automatique générée depuis la réception {instance.receipt_number}"
            )

            # Lier la réception à la facture
            instance.is_invoiced = True
            instance.supplier_invoice = invoice
            instance.auto_invoice_number = auto_invoice_number
            instance.save(
                update_fields=['is_invoiced', 'supplier_invoice', 'auto_invoice_number'])

            # Mettre à jour la commande
            purchase_order.update_invoice_status()

            print(
                f"✅ Facture automatique créée : {auto_invoice_number} pour la réception {instance.receipt_number}")

        except Exception as e:
            print(
                f"❌ Erreur lors de la création automatique de la facture : {str(e)}")
