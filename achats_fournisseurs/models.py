from django.db import models

# Create your models here.
# apps/achats_fournisseurs/models.py - Version COMPLÈTE
from django.db.models import Sum, F
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import json
import qrcode

from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from users.models import CustomUser
from produits_stocks.models import Product, UnitMeasure, Warehouse, Lot, Stock, StockMovement


# ============================================================
# UTILITAIRES
# ============================================================

def generate_number(model, field_name, prefix):
    """Génère un numéro séquentiel"""
    year = date.today().year

    last_object = (
        model.objects
        .filter(**{
            f"{field_name}__startswith": f"{prefix}-{year}-"
        })
        .order_by("-id")
        .first()
    )

    if last_object:
        last_number = getattr(last_object, field_name)
        try:
            number = int(last_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            number = 1
    else:
        number = 1

    return f"{prefix}-{year}-{number:04d}"


def generate_qr_image(data):
    """Génère une image QR Code"""
    qr_data = json.dumps(data, ensure_ascii=False, default=str)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return qr_data, buffer


# ============================================================
# FOURNISSEUR
# ============================================================

class Supplier(models.Model):
    TYPE_CHOICES = (
        ('local', 'Local'),
        ('international', 'International'),
        ('importateur', 'Importateur'),
        ('distributeur', 'Distributeur'),
        ('fabricant', 'Fabricant'),
    )

    PAYMENT_TERMS_CHOICES = (
        ('cash', 'Comptant'),
        ('15', '15 jours'),
        ('30', '30 jours'),
        ('45', '45 jours'),
        ('60', '60 jours'),
        ('90', '90 jours'),
    )

    code = models.CharField(max_length=50, unique=True,
                            verbose_name="Code fournisseur")
    name = models.CharField(
        max_length=200, verbose_name="Nom / Raison sociale")
    commercial_name = models.CharField(
        max_length=200, blank=True, verbose_name="Nom commercial")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='local', verbose_name="Type")
    contact_person = models.CharField(
        max_length=100, blank=True, verbose_name="Personne de contact")
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    mobile = models.CharField(max_length=20, blank=True, verbose_name="Mobile")
    email = models.EmailField(verbose_name="Email")
    website = models.URLField(blank=True, verbose_name="Site web")
    address = models.TextField(verbose_name="Adresse")
    city = models.CharField(max_length=100, verbose_name="Ville")
    country = models.CharField(
        max_length=100, default='Sénégal', verbose_name="Pays")
    postal_code = models.CharField(
        max_length=20, blank=True, verbose_name="Code postal")
    tax_id = models.CharField(
        max_length=50, blank=True, verbose_name="N° Identification fiscale")
    registration_number = models.CharField(
        max_length=50, blank=True, verbose_name="N° Registre de commerce")
    payment_terms = models.CharField(
        max_length=20, choices=PAYMENT_TERMS_CHOICES, default='30', verbose_name="Délai de paiement")
    delivery_lead_time = models.IntegerField(
        default=7, verbose_name="Délai de livraison (jours)")
    minimum_order = models.IntegerField(
        default=0, verbose_name="Commande minimum")
    rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=0, verbose_name="Note (0-5)")
    total_purchases = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Total achats")
    total_orders = models.IntegerField(
        default=0, verbose_name="Nombre de commandes")
    on_time_delivery_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Taux livraison à temps (%)")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_preferred = models.BooleanField(
        default=False, verbose_name="Fournisseur privilégié")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date modification")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='fournisseurs_created', verbose_name="Créé par")

    class Meta:
        verbose_name = "Fournisseur"
        verbose_name_plural = "Fournisseurs"
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def full_address(self):
        parts = [self.address, self.city, self.country]
        return ", ".join([p for p in parts if p])

    @property
    def total_debt(self):
        total = self.invoices.filter(
            paiement_status__in=['unpaid', 'partial', 'overdue']
        ).aggregate(
            total=Sum(F('total_amount') - F('amount_paid'))
        )['total']
        return total or Decimal('0')

    @property
    def overdue_debt(self):
        total = self.invoices.filter(
            due_date__lt=date.today(),
            paiement_status__in=['unpaid', 'partial']
        ).aggregate(
            total=Sum(F('total_amount') - F('amount_paid'))
        )['total']
        return total or Decimal('0')


class SupplierContact(models.Model):
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=100, verbose_name="Nom complet")
    position = models.CharField(
        max_length=100, blank=True, verbose_name="Poste")
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    mobile = models.CharField(max_length=20, blank=True, verbose_name="Mobile")
    email = models.EmailField(verbose_name="Email")
    is_primary = models.BooleanField(
        default=False, verbose_name="Contact principal")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contact fournisseur"
        verbose_name_plural = "Contacts fournisseurs"

    def __str__(self):
        return f"{self.name} - {self.supplier.name}"


class SupplierProduct(models.Model):
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='products')
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='suppliers')
    supplier_sku = models.CharField(
        max_length=100, blank=True, verbose_name="Référence fournisseur")
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix d'achat")
    lead_time = models.IntegerField(
        default=7, verbose_name="Délai de livraison (jours)")
    minimum_order = models.IntegerField(
        default=1, verbose_name="Quantité minimum")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    notes = models.TextField(blank=True, verbose_name="Notes")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produit fournisseur"
        verbose_name_plural = "Produits fournisseurs"
        unique_together = ['supplier', 'product']

    def __str__(self):
        return f"{self.supplier.name} - {self.product.name}"


# ============================================================
# BON DE COMMANDE
# ============================================================

# apps/achats_fournisseurs/models.py - Partie PurchaseOrder

class PurchaseOrder(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyé'),
        ('confirmed', 'Confirmé'),
        ('partial', 'Partiellement reçu'),
        ('received', 'Reçu'),
        ('cancelled', 'Annulé'),
    )

    DISCOUNT_CHOICES = (
        ('percentage', 'Pourcentage'),
        ('amount', 'Montant fixe'),
    )

    po_number = models.CharField(
        max_length=50, unique=True, verbose_name="N° Bon de commande")
    supplier_reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence fournisseur")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, related_name='purchase_orders')
    order_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Date commande")
    expected_delivery_date = models.DateField(
        verbose_name="Date livraison prévue")
    actual_delivery_date = models.DateField(
        null=True, blank=True, verbose_name="Date livraison réelle")
    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Sous-total")
    discount_type = models.CharField(
        max_length=10, choices=DISCOUNT_CHOICES, default='amount', verbose_name="Type de remise")
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Valeur de la remise")
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Montant de la remise")
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Taux TVA (%)")
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Montant TVA")
    shipping_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Frais de livraison")
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Total")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="Statut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    internal_notes = models.TextField(
        blank=True, verbose_name="Notes internes")
    shipping_address = models.TextField(
        blank=True, verbose_name="Adresse de livraison")
    tracking_number = models.CharField(
        max_length=100, blank=True, verbose_name="N° de suivi")

    total_received_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Montant total reçu")
    total_invoiced_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Montant total facturé")
    total_paid_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Montant total payé")
    is_fully_received = models.BooleanField(
        default=False, verbose_name="Entièrement reçue")
    is_fully_invoiced = models.BooleanField(
        default=False, verbose_name="Entièrement facturée")
    is_fully_paid = models.BooleanField(
        default=False, verbose_name="Entièrement payée")

    qr_code = models.ImageField(
        upload_to='qrcodes/purchase_orders/', null=True, blank=True, verbose_name="QR Code")
    qr_code_data = models.TextField(blank=True, verbose_name="Données QR Code")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='purchase_orders', verbose_name="Créé par")
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='approved_orders', verbose_name="Approuvé par")
    approved_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Date approbation")

    class Meta:
        verbose_name = "Bon de commande"
        verbose_name_plural = "Bons de commande"
        ordering = ['-order_date']

    def __str__(self):
        return f"{self.po_number} - {self.supplier.name if self.supplier else 'N/A'}"

    @property
    def remaining_to_receive(self):
        return self.total - self.total_received_amount

    @property
    def remaining_to_invoice(self):
        return self.total - self.total_invoiced_amount

    @property
    def remaining_to_pay(self):
        return self.total_invoiced_amount - self.total_paid_amount

    @property
    def receipt_progress(self):
        if self.total == 0:
            return 0
        return (self.total_received_amount / self.total) * 100

    @property
    def payment_progress(self):
        if self.total_invoiced_amount == 0:
            return 0
        return (self.total_paid_amount / self.total_invoiced_amount) * 100

    def calculate_totals(self):
        self.subtotal = sum(line.total for line in self.lines.all())
        if self.discount_type == 'percentage':
            self.discount_amount = self.subtotal * (self.discount_value / 100)
        else:
            self.discount_amount = self.discount_value
        after_discount = self.subtotal - self.discount_amount
        self.tax_amount = after_discount * (self.tax_rate / 100)
        self.total = after_discount + self.tax_amount + self.shipping_cost
        self.save(update_fields=['subtotal',
                  'discount_amount', 'tax_amount', 'total'])

    def update_receipt_status(self):
        """✅ CORRIGÉ : Met à jour le statut en fonction des quantités reçues"""
        total_ordered = self.lines.aggregate(
            total=Sum('quantity'))['total'] or 0
        total_received = self.lines.aggregate(
            total=Sum('quantity_received'))['total'] or 0

        # Si aucune ligne ou quantité commandée = 0
        if total_ordered == 0:
            self.is_fully_received = False
            if self.status not in ['cancelled', 'draft']:
                self.status = 'confirmed'
        else:
            # Vérifier si tout est reçu
            all_received = True
            for line in self.lines.all():
                if line.quantity_received < line.quantity:
                    all_received = False
                    break

            self.is_fully_received = all_received

            if self.status in ['cancelled', 'draft']:
                pass  # Ne pas changer le statut si annulé ou brouillon
            elif all_received:
                self.status = 'received'
            elif total_received > 0:
                self.status = 'partial'  # ✅ Statut partiel
            else:
                self.status = 'confirmed'  # Pas encore de réception

        self.save(update_fields=['is_fully_received', 'status'])

    def update_invoice_status(self):
        if self.total == 0:
            self.is_fully_invoiced = False
        else:
            total_invoiced = self.invoices.aggregate(
                total=Sum('total_amount'))['total'] or 0
            self.total_invoiced_amount = total_invoiced
            self.is_fully_invoiced = total_invoiced >= self.total
        self.save(update_fields=['total_invoiced_amount', 'is_fully_invoiced'])

    def update_payment_status(self):
        total_paid = self.paiements.filter(status='confirmed').aggregate(
            total=Sum('amount'))['total'] or 0
        self.total_paid_amount = total_paid
        if self.total_invoiced_amount == 0:
            self.is_fully_paid = False
        else:
            self.is_fully_paid = total_paid >= self.total_invoiced_amount
        self.save(update_fields=['total_paid_amount', 'is_fully_paid'])

    def generate_qr_code(self):
        if not self.po_number:
            return
        qr_data = {
            'type': 'purchase_order',
            'id': self.id,
            'number': self.po_number,
            'supplier': self.supplier.name if self.supplier else '',
            'supplier_code': self.supplier.code if self.supplier else '',
            'total': str(self.total),
            'date': self.order_date.strftime('%Y-%m-%d %H:%M:%S'),
            'status': self.status,
            'expected_delivery': self.expected_delivery_date.strftime('%Y-%m-%d') if self.expected_delivery_date else '',
            'url': f'/commandes-fournisseurs/{self.id}/'
        }
        qr_data_str, buffer = generate_qr_image(qr_data)
        self.qr_code_data = qr_data_str
        filename = f"qr_po_{self.po_number}.png"
        self.qr_code.save(filename, File(buffer), save=False)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new or not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(verbose_name="Quantité commandée")
    quantity_received = models.IntegerField(
        default=0, verbose_name="Quantité reçue")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix unitaire")
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Remise")
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="TVA (%)")
    total = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Total ligne")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne de commande"
        verbose_name_plural = "Lignes de commande"

    def __str__(self):
        return f"{self.purchase_order.po_number} - {self.product.name}"

    @property
    def quantity_remaining(self):
        return self.quantity - self.quantity_received

    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.unit_price) - self.discount
        super().save(*args, **kwargs)
        self.purchase_order.calculate_totals()


# ============================================================
# RÉCEPTION
# ============================================================

class Receipt(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminée'),
        ('cancelled', 'Annulée'),
    )

    receipt_number = models.CharField(
        max_length=50, unique=True, verbose_name="N° de réception")
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='receipts')
    receipt_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de réception")
    expected_date = models.DateField(verbose_name="Date prévue")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, verbose_name="Entrepôt de destination")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    delivery_note = models.CharField(
        max_length=100, blank=True, verbose_name="N° Bon de livraison")
    invoice_number = models.CharField(
        max_length=100, blank=True, verbose_name="N° Facture")

    is_invoiced = models.BooleanField(default=False, verbose_name="Facturée")
    supplier_invoice = models.ForeignKey(
        'SupplierInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='receipts',
        verbose_name="Facture associée"
    )
    auto_invoice = models.BooleanField(
        default=True, verbose_name="Créer facture automatiquement")
    auto_invoice_number = models.CharField(
        max_length=100, blank=True, verbose_name="N° Facture auto")

    caisse_destination_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Caisse de décaissement")
    compte_destination_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Compte bancaire de décaissement")
    montant_decaissement = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Montant décaissé")
    mouvement_tresorerie_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Mouvement de trésorerie")

    qr_code = models.ImageField(
        upload_to='qrcodes/receipts/', null=True, blank=True, verbose_name="QR Code")
    qr_code_data = models.TextField(blank=True, verbose_name="Données QR Code")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='receptions_created', verbose_name="Réceptionné par")

    class Meta:
        verbose_name = "Réception"
        verbose_name_plural = "Réceptions"
        ordering = ['-receipt_date']

    def __str__(self):
        return f"{self.receipt_number} - {self.purchase_order.po_number}"

    @property
    def total_received_amount(self):
        total = Decimal('0')
        for line in self.lines.all():
            total += line.quantity_received * line.po_line.unit_price
        return total

    def generate_qr_code(self):
        if not self.receipt_number:
            return
        qr_data = {
            'type': 'receipt',
            'id': self.id,
            'number': self.receipt_number,
            'purchase_order': self.purchase_order.po_number if self.purchase_order else '',
            'supplier': self.purchase_order.supplier.name if self.purchase_order and self.purchase_order.supplier else '',
            'warehouse': self.warehouse.name if self.warehouse else '',
            'date': self.receipt_date.strftime('%Y-%m-%d %H:%M:%S') if self.receipt_date else '',
            'status': self.status,
            'url': f'/receptions/{self.id}/'
        }
        qr_data_str, buffer = generate_qr_image(qr_data)
        self.qr_code_data = qr_data_str
        filename = f"qr_rec_{self.receipt_number}.png"
        self.qr_code.save(filename, File(buffer), save=False)

    def creer_mouvement_decaissement(self, user):
        if self.mouvement_tresorerie_id:
            return self.mouvement_tresorerie_id

        try:
            from tresorerie.models import MouvementTresorerie, Caisse, CompteBancaire
        except ImportError:
            return None

        total_recu = self.total_received_amount

        if total_recu <= 0:
            return None

        self.montant_decaissement = total_recu

        caisse = None
        compte = None

        if self.caisse_destination_id:
            try:
                caisse = Caisse.objects.get(id=self.caisse_destination_id)
            except Caisse.DoesNotExist:
                pass

        if self.compte_destination_id:
            try:
                compte = CompteBancaire.objects.get(
                    id=self.compte_destination_id)
            except CompteBancaire.DoesNotExist:
                pass

        if not caisse and not compte:
            if self.warehouse:
                caisse = Caisse.objects.filter(
                    warehouse=self.warehouse, is_default=True).first()
            if not caisse and not compte:
                caisse = Caisse.objects.filter(is_default=True).first()

        if not caisse and not compte:
            return None

        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='decaissement',
            warehouse=self.warehouse,
            source_type='achat',
            source_id=self.purchase_order.id,
            source_reference=self.purchase_order.po_number,
            montant=total_recu,
            mode_paiement='virement',
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=timezone.now(),
            date_valeur=timezone.now().date(),
            status='effectue',
            libelle=f"Décaissement pour réception {self.receipt_number} - commande {self.purchase_order.po_number}",
            created_by=user
        )

        self.mouvement_tresorerie_id = mouvement.id
        self.save(update_fields=[
                  'montant_decaissement', 'mouvement_tresorerie_id'])

        return self.mouvement_tresorerie_id

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new or not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])


class ReceiptLine(models.Model):
    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE, related_name='lines')
    po_line = models.ForeignKey(
        PurchaseOrderLine, on_delete=models.CASCADE, related_name='receipt_lines')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity_ordered = models.IntegerField(verbose_name="Quantité commandée")
    quantity_received = models.IntegerField(verbose_name="Quantité reçue")
    quantity_damaged = models.IntegerField(
        default=0, verbose_name="Quantité endommagée")
    lot = models.ForeignKey(Lot, on_delete=models.SET_NULL,
                            null=True, blank=True, verbose_name="Lot associé")
    lot_number = models.CharField(
        max_length=100, blank=True, verbose_name="Numéro de lot")
    expiry_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'expiration")
    manufacturing_date = models.DateField(
        null=True, blank=True, verbose_name="Date de fabrication")
    is_quality_checked = models.BooleanField(
        default=False, verbose_name="Contrôle qualité effectué")
    quality_status = models.CharField(max_length=20, blank=True, choices=[(
        'passed', 'Approuvé'), ('failed', 'Refusé'), ('pending', 'En attente')], default='pending')
    quality_notes = models.TextField(blank=True, verbose_name="Notes qualité")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne de réception"
        verbose_name_plural = "Lignes de réception"

    def __str__(self):
        return f"{self.receipt.receipt_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        total_received = ReceiptLine.objects.filter(po_line=self.po_line).aggregate(
            total=Sum('quantity_received'))['total'] or 0
        self.po_line.quantity_received = total_received
        self.po_line.save()
        self.receipt.purchase_order.update_receipt_status()


# ============================================================
# RETOUR FOURNISSEUR - AJOUTÉ
# ============================================================

class PurchaseReturn(models.Model):
    REASON_CHOICES = (
        ('defective', 'Produit défectueux'),
        ('wrong_product', 'Produit incorrect'),
        ('expired', 'Produit expiré'),
        ('damaged', 'Produit endommagé'),
        ('other', 'Autre'),
    )
    STATUS_CHOICES = (
        ('requested', 'Demandé'),
        ('approved', 'Approuvé'),
        ('shipped', 'Expédié'),
        ('refunded', 'Remboursé'),
        ('replaced', 'Remplacé'),
        ('rejected', 'Refusé'),
    )

    return_number = models.CharField(
        max_length=50, unique=True, verbose_name="N° de retour")
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='returns')
    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE, null=True, blank=True, related_name='returns')
    return_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de retour")
    reason = models.CharField(
        max_length=20, choices=REASON_CHOICES, verbose_name="Raison")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='requested', verbose_name="Statut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL,
                                   null=True, related_name='returns_created', verbose_name="Créé par")
    qr_code = models.ImageField(
        upload_to='qrcodes/purchase_returns/', null=True, blank=True, verbose_name="QR Code")
    qr_code_data = models.TextField(blank=True, verbose_name="Données QR Code")

    class Meta:
        verbose_name = "Retour fournisseur"
        verbose_name_plural = "Retours fournisseurs"
        ordering = ['-return_date']

    def __str__(self):
        return f"{self.return_number} - {self.purchase_order.po_number}"

    def generate_qr_code(self):
        if not self.return_number:
            return
        qr_data = {
            'type': 'purchase_return',
            'id': self.id,
            'number': self.return_number,
            'purchase_order': self.purchase_order.po_number if self.purchase_order else '',
            'supplier': self.purchase_order.supplier.name if self.purchase_order and self.purchase_order.supplier else '',
            'reason': self.reason,
            'status': self.status,
            'date': self.return_date.strftime('%Y-%m-%d %H:%M:%S') if self.return_date else '',
            'url': f'/purchase-returns/{self.id}/'
        }
        qr_data_str, buffer = generate_qr_image(qr_data)
        self.qr_code_data = qr_data_str
        filename = f"qr_ret_{self.return_number}.png"
        self.qr_code.save(filename, File(buffer), save=False)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new or not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])


class PurchaseReturnLine(models.Model):
    purchase_return = models.ForeignKey(
        PurchaseReturn, on_delete=models.CASCADE, related_name='lines')
    receipt_line = models.ForeignKey(
        ReceiptLine, on_delete=models.CASCADE, related_name='return_lines')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(verbose_name="Quantité retournée")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix unitaire")
    total = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Total")

    class Meta:
        verbose_name = "Ligne de retour"
        verbose_name_plural = "Lignes de retour"

    def __str__(self):
        return f"{self.purchase_return.return_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


# ============================================================
# FACTURE FOURNISSEUR - CORRIGÉ
# ============================================================
# apps/achats_fournisseurs/models.py - Partie SupplierInvoice

class SupplierInvoice(models.Model):
    """Facture fournisseur avec suivi des paiements"""
    STATUS_CHOICES = (
        ('received', 'Reçue'),
        ('verified', 'Vérifiée'),
        ('paid', 'Payée'),
        ('partial', 'Partiellement payée'),
        ('disputed', 'Contestée'),
    )
    PAIEMENT_STATUS_CHOICES = (
        ('unpaid', 'Non payée'),
        ('partial', 'Partiellement payée'),
        ('paid', 'Payée'),
        ('overdue', 'En retard'),
    )

    invoice_number = models.CharField(
        max_length=100, unique=True, verbose_name="N° Facture")
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='invoices')
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE, related_name='invoices')
    invoice_date = models.DateField(verbose_name="Date facture")
    due_date = models.DateField(verbose_name="Date d'échéance")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Montant HT")
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="TVA")
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Total TTC")
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Montant payé")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='received', verbose_name="Statut")
    paiement_status = models.CharField(
        max_length=20, choices=PAIEMENT_STATUS_CHOICES, default='unpaid', verbose_name="Statut paiement")
    is_fully_paid = models.BooleanField(
        default=False, verbose_name="Entièrement payée")

    payment_date = models.DateField(
        null=True, blank=True, verbose_name="Date de paiement")
    payment_reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence paiement")
    pdf_file = models.FileField(
        upload_to='invoices/', null=True, blank=True, verbose_name="PDF facture")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Facture fournisseur"
        verbose_name_plural = "Factures fournisseurs"
        ordering = ['-invoice_date']

    def __str__(self):
        return f"{self.invoice_number} - {self.supplier.name}"

    def get_remaining_amount(self):
        """✅ Montant restant à payer - METHODE"""
        return self.total_amount - self.amount_paid

    @property
    def remaining_amount(self):
        """✅ Montant restant à payer - PROPRIÉTÉ CALCULÉE"""
        return self.total_amount - self.amount_paid

    @property
    def paid_percentage(self):
        """✅ Pourcentage payé"""
        if self.total_amount == 0:
            return 0
        return (self.amount_paid / self.total_amount) * 100

    @property
    def is_overdue(self):
        return date.today() > self.due_date and not self.is_fully_paid

    @property
    def days_overdue(self):
        if self.is_overdue:
            return (date.today() - self.due_date).days
        return 0

    def update_payment_status(self):
        """✅ Met à jour le statut de paiement - CORRIGÉ"""
        from .models import FournisseurPaiement

        # ✅ Recalculer le montant payé à partir des paiements confirmés
        total_paid = self.paiements.filter(status='confirmed').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        self.amount_paid = total_paid

        # ✅ Calculer le reste
        remaining = self.total_amount - self.amount_paid

        if remaining <= 0:
            self.is_fully_paid = True
            self.paiement_status = 'paid'
            self.status = 'paid'
            if not self.payment_date:
                self.payment_date = timezone.now().date()
        elif self.amount_paid > 0:
            self.is_fully_paid = False
            self.paiement_status = 'partial'
            self.status = 'partial'
            if not self.payment_date:
                self.payment_date = timezone.now().date()
        else:
            self.is_fully_paid = False
            if self.is_overdue:
                self.paiement_status = 'overdue'
                self.status = 'received'
            else:
                self.paiement_status = 'unpaid'
                self.status = 'received'

        # ✅ Mettre à jour la commande
        if self.purchase_order:
            self.purchase_order.update_invoice_status()
            self.purchase_order.update_payment_status()

        # ✅ Sauvegarder
        self.save(update_fields=[
            'amount_paid',
            'is_fully_paid',
            'paiement_status',
            'status',
            'payment_date',
            'updated_at'
        ])

    @classmethod
    def get_available_for_payment(cls, supplier_id=None):
        """✅ Récupère les factures disponibles pour paiement"""
        queryset = cls.objects.filter(is_fully_paid=False)
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        return queryset.order_by('due_date')

# ============================================================
# PAIEMENT FOURNISSEUR - CORRIGÉ
# ============================================================


class FournisseurPaiement(models.Model):
    METHOD_CHOICES = (
        ('especes', 'Espèces'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement bancaire'),
        ('transfert', 'Transfert'),
        ('mobile_money', 'Mobile Money'),
        ('autre', 'Autre'),
    )
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('confirmed', 'Confirmé'),
        ('cancelled', 'Annulé'),
    )

    reference = models.CharField(
        max_length=50, unique=True, verbose_name="Référence paiement")
    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name='paiements', verbose_name="Facture fournisseur")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE,
                                       related_name='paiements', null=True, blank=True, verbose_name="Commande associée")
    amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant payé")
    method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default='virement', verbose_name="Méthode")
    reference_number = models.CharField(
        max_length=100, blank=True, verbose_name="N° de référence")
    payment_date = models.DateTimeField(
        default=timezone.now, verbose_name="Date de paiement")

    caisse_destination_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Caisse de décaissement")
    compte_destination_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Compte bancaire de décaissement")
    mouvement_tresorerie_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID Mouvement de trésorerie")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Statut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='paiements_fournisseurs', verbose_name="Créé par")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    qr_code = models.ImageField(
        upload_to='qrcodes/fournisseur_paiements/', null=True, blank=True, verbose_name="QR Code")
    qr_code_data = models.TextField(blank=True, verbose_name="Données QR Code")

    class Meta:
        verbose_name = "Paiement fournisseur"
        verbose_name_plural = "Paiements fournisseurs"
        ordering = ['-payment_date']

    def __str__(self):
        return f"{self.reference} - {self.supplier_invoice.invoice_number} - {self.amount:,.0f} FCFA"

    def generate_qr_code(self):
        if not self.reference:
            return
        qr_data = {
            'type': 'fournisseur_paiement',
            'id': self.id,
            'reference': self.reference,
            'invoice': self.supplier_invoice.invoice_number,
            'supplier': self.supplier_invoice.supplier.name,
            'amount': str(self.amount),
            'date': self.payment_date.strftime('%Y-%m-%d %H:%M:%S'),
            'method': self.method,
            'status': self.status
        }
        qr_data_str, buffer = generate_qr_image(qr_data)
        self.qr_code_data = qr_data_str
        filename = f"qr_fournisseur_paiement_{self.reference}.png"
        self.qr_code.save(filename, File(buffer), save=False)

    def creer_mouvement_tresorerie(self, user):
        if self.mouvement_tresorerie_id:
            return self.mouvement_tresorerie_id

        try:
            from tresorerie.models import MouvementTresorerie, Caisse, CompteBancaire
        except ImportError:
            return None

        caisse = None
        compte = None

        if self.caisse_destination_id:
            try:
                caisse = Caisse.objects.get(id=self.caisse_destination_id)
            except Caisse.DoesNotExist:
                pass

        if self.compte_destination_id:
            try:
                compte = CompteBancaire.objects.get(
                    id=self.compte_destination_id)
            except CompteBancaire.DoesNotExist:
                pass

        if not caisse and not compte:
            caisse = Caisse.objects.filter(is_default=True).first()

        if not caisse and not compte:
            return None

        warehouse = None
        if self.purchase_order:
            receipt = self.purchase_order.receipts.first()
            if receipt:
                warehouse = receipt.warehouse

        if not warehouse and self.supplier_invoice and self.supplier_invoice.purchase_order:
            receipt = self.supplier_invoice.purchase_order.receipts.first()
            if receipt:
                warehouse = receipt.warehouse

        if not warehouse and caisse:
            warehouse = caisse.warehouse

        mouvement = MouvementTresorerie.objects.create(
            type_mouvement='decaissement',
            warehouse=warehouse,
            source_type='paiement_fournisseur',
            source_id=self.id,
            source_reference=self.reference,
            montant=self.amount,
            mode_paiement=self.method,
            caisse=caisse,
            compte_bancaire=compte,
            date_mouvement=self.payment_date,
            date_valeur=self.payment_date.date(),
            status='effectue',
            libelle=f"Paiement fournisseur - {self.supplier_invoice.invoice_number} - {self.supplier_invoice.supplier.name}",
            created_by=user
        )

        if caisse:
            caisse.solde_actuel -= self.amount
            caisse.save(update_fields=['solde_actuel', 'updated_at'])

        self.mouvement_tresorerie_id = mouvement.id
        self.save(update_fields=['mouvement_tresorerie_id'])

        return self.mouvement_tresorerie_id

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new and not self.reference:
            last_paiement = FournisseurPaiement.objects.order_by('-id').first()
            num = 1
            if last_paiement and last_paiement.reference:
                try:
                    num = int(last_paiement.reference.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            self.reference = f"PAYF-{date.today().year}-{num:04d}"

        super().save(*args, **kwargs)
        if is_new or not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])
