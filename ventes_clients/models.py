# apps/ventes_clients/models.py
# ============================================================
# MODELS COMPLET OPTIMISÉ — LOGICIEL B
# Index identiques au Logiciel A sur TOUS les modèles
# ============================================================

import logging
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
from produits_stocks.models import (
    Product,
    Lot,
    Warehouse,
    Stock,
    StockMovement,
)

logger = logging.getLogger(__name__)


# ============================================================
# UTILITAIRES
# ============================================================

def generate_number(model, field_name, prefix):
    """
    Génère un numéro séquentiel :
    DEV-2026-0001
    INV-2026-0001
    FAC-2026-0001
    AV-2026-0001
    """
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
    """Génère une image QR Code."""
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
# CLIENT
# ============================================================

class Client(models.Model):
    """Modèle Client avec 7 champs essentiels."""

    TYPE_CHOICES = (
        ("particulier", "Particulier"),
        ("entreprise", "Entreprise"),
        ("revendeur", "Revendeur"),
        ("grossiste", "Grossiste"),
    )

    STATUT_CHOICES = (
        ("actif", "Actif"),
        ("inactif", "Inactif"),
        ("bloque", "Bloqué"),
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Code client"
    )
    name = models.CharField(
        max_length=200,
        verbose_name="Nom / Raison sociale"
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="particulier",
        verbose_name="Type"
    )
    phone = models.CharField(
        max_length=20,
        verbose_name="Téléphone"
    )
    address = models.TextField(
        blank=True,
        verbose_name="Adresse"
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default="actif",
        verbose_name="Statut"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Notes"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients_created",
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        ordering = ["name"]
        indexes = [
            models.Index(fields=['code'], name='client_code_idx'),
            models.Index(fields=['name'], name='client_name_idx'),
            models.Index(fields=['phone'], name='client_phone_idx'),
            models.Index(fields=['statut'], name='client_statut_idx'),
            models.Index(fields=['type'], name='client_type_idx'),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @classmethod
    def create_anonymous(cls, created_by=None):
        """Crée un client anonyme de manière sécurisée."""
        client = cls.objects.filter(
            name="Client anonyme",
            statut="actif"
        ).first()

        if client:
            return client

        count = cls.objects.count()
        return cls.objects.create(
            code=f"ANON-{date.today().year}-{count + 1:04d}",
            name="Client anonyme",
            type="particulier",
            phone="00000000",
            address="Non renseigné",
            statut="actif",
            notes="Client créé automatiquement",
            created_by=created_by
        )


# ============================================================
# DEVIS
# ============================================================

class Devis(models.Model):
    """Devis / Proforma."""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyé'),
        ('accepted', 'Accepté'),
        ('refused', 'Refusé'),
        ('expired', 'Expiré'),
        ('converted', 'Converti en vente'),
    )

    devis_number = models.CharField(
        max_length=50, unique=True, verbose_name="N° Devis"
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devis'
    )
    client_name = models.CharField(
        max_length=200, verbose_name="Nom client"
    )
    client_phone = models.CharField(
        max_length=20, blank=True, verbose_name="Téléphone client"
    )
    client_email = models.EmailField(
        blank=True, verbose_name="Email client"
    )
    client_address = models.TextField(
        blank=True, verbose_name="Adresse client"
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devis',
        verbose_name="Entrepôt"
    )

    devis_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Date devis"
    )
    valid_until = models.DateField(
        verbose_name="Valable jusqu'au"
    )

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Sous-total"
    )
    discount_type = models.CharField(
        max_length=20,
        choices=[
            ('percentage', 'Pourcentage'),
            ('amount', 'Montant')
        ],
        default='percentage',
        verbose_name="Type remise"
    )
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Valeur remise"
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Montant remise"
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Taux TVA (%)"
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Montant TVA"
    )
    shipping_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="Frais de livraison"
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Total TTC"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name="Statut"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    internal_notes = models.TextField(
        blank=True, verbose_name="Notes internes")

    sale = models.ForeignKey(
        'Vente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devis_source'
    )

    qr_code = models.ImageField(
        upload_to='qrcodes/devis/',
        null=True,
        blank=True,
        verbose_name="QR Code"
    )
    qr_code_data = models.TextField(
        blank=True, verbose_name="Données QR Code"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création"
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date modification"
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='devis',
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Devis"
        verbose_name_plural = "Devis"
        ordering = ['-devis_date']
        indexes = [
            models.Index(fields=['-devis_date'], name='devis_date_idx'),
            models.Index(fields=['status'], name='devis_status_idx'),
            models.Index(fields=['client', '-devis_date'],
                         name='devis_client_date_idx'),
            models.Index(fields=['devis_number'], name='devis_number_idx'),
            models.Index(fields=['warehouse'], name='devis_warehouse_idx'),
        ]

    def __str__(self):
        return f"{self.devis_number} - {self.client_name}"

    def calculate_totals(self):
        """Calcule les totaux du devis."""
        self.subtotal = sum(line.total for line in self.lignes.all())

        if self.discount_type == 'percentage':
            self.discount_amount = self.subtotal * (self.discount_value / 100)
        else:
            self.discount_amount = self.discount_value

        after_discount = self.subtotal - self.discount_amount
        self.tax_amount = after_discount * (self.tax_rate / 100)
        self.total = after_discount + self.tax_amount + self.shipping_fee

        super().save(update_fields=[
            'subtotal', 'discount_amount', 'tax_amount', 'total'
        ])

    def generate_qr_code(self):
        """Génère un QR Code pour le devis."""
        if not self.devis_number:
            return

        qr_data = {
            'type': 'devis',
            'id': self.id,
            'number': self.devis_number,
            'client': self.client_name,
            'total': str(self.total),
            'date': self.devis_date.strftime('%Y-%m-%d %H:%M:%S'),
            'valid_until': self.valid_until.strftime('%Y-%m-%d'),
            'status': self.status,
            'url': f'/devis/{self.id}/'
        }

        qr_data_str = json.dumps(qr_data, ensure_ascii=False)
        self.qr_code_data = qr_data_str

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data_str)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format='PNG')

        filename = f"qr_devis_{self.devis_number}.png"
        self.qr_code.save(filename, File(buffer), save=False)

    def save(self, *args, **kwargs):
        """Sauvegarde avec génération automatique du QR Code."""
        if not self.pk:
            super().save(*args, **kwargs)

        if not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])
        else:
            super().save(*args, **kwargs)

    def convert_to_sale(self, user=None):
        """Convertit le devis en vente."""
        from .models import Vente, LigneVente

        if not self.warehouse:
            raise ValueError(
                "L'entrepôt doit être défini pour convertir le devis en vente"
            )

        if self.status != 'accepted':
            raise ValueError(
                "Seul un devis accepté peut être converti en vente"
            )

        if self.sale:
            raise ValueError("Ce devis a déjà été converti en vente")

        last_vente = Vente.objects.order_by('-id').first()
        if last_vente and last_vente.invoice_number:
            try:
                num = int(last_vente.invoice_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        invoice_number = f"INV-{date.today().year}-{num:04d}"

        vente = Vente(
            invoice_number=invoice_number,
            client=self.client,
            client_name=self.client_name or "Client anonyme",
            client_phone=self.client_phone,
            client_email=self.client_email,
            client_address=self.client_address,
            warehouse=self.warehouse,
            payment_due_date=date.today() + timedelta(days=30),
            subtotal=self.subtotal,
            discount_type=self.discount_type,
            discount_value=self.discount_value,
            discount_amount=self.discount_amount,
            tax_rate=self.tax_rate,
            tax_amount=self.tax_amount,
            shipping_fee=self.shipping_fee,
            total=self.total,
            notes=self.notes,
            internal_notes=self.internal_notes,
            status='draft',
            created_by=user
        )
        vente.save()

        for ligne_devis in self.lignes.all():
            LigneVente.objects.create(
                sale=vente,
                product=ligne_devis.product,
                quantity=ligne_devis.quantity,
                unit_price=ligne_devis.unit_price,
                discount=ligne_devis.discount,
                tax_rate=ligne_devis.tax_rate,
                total=ligne_devis.total,
                notes=ligne_devis.notes
            )

        self.status = 'converted'
        self.sale = vente
        self.save(update_fields=['status', 'sale'])

        vente.calculate_totals()
        vente.generate_qr_code()
        vente.save(update_fields=['qr_code', 'qr_code_data'])

        return vente


# ============================================================
# LIGNE DEVIS
# ============================================================

class LigneDevis(models.Model):
    devis = models.ForeignKey(
        Devis,
        on_delete=models.CASCADE,
        related_name="lignes"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Ligne de devis"
        verbose_name_plural = "Lignes de devis"
        indexes = [
            models.Index(fields=['devis'], name='lignedevis_devis_idx'),
            models.Index(fields=['product'], name='lignedevis_product_idx'),
        ]

    def __str__(self):
        return f"{self.devis.devis_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        if self.quantity <= 0:
            raise ValidationError("La quantité doit être supérieure à zéro.")

        gross_total = Decimal(self.quantity) * self.unit_price
        self.total = max(
            Decimal("0.00"),
            gross_total - self.discount
        )

        super().save(*args, **kwargs)
        self.devis.calculate_totals()


# ============================================================
# VENTE
# ============================================================

class Vente(models.Model):

    STATUS_CHOICES = (
        ("draft", "Brouillon"),
        ("confirmed", "Confirmée"),
        ("paid", "Payée"),
        ("delivered", "Livrée"),
        ("cancelled", "Annulée"),
        ("returned", "Retournée"),
    )

    PAYMENT_STATUS_CHOICES = (
        ("pending", "En attente"),
        ("partial", "Paiement partiel"),
        ("paid", "Payé"),
    )

    invoice_number = models.CharField(max_length=50, unique=True)
    order_number = models.CharField(
        max_length=50, unique=True, null=True, blank=True
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales"
    )
    client_name = models.CharField(max_length=200, blank=True)
    client_phone = models.CharField(max_length=20, blank=True)
    client_email = models.EmailField(blank=True)
    client_address = models.TextField(blank=True)

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventes"
    )

    sale_date = models.DateTimeField(auto_now_add=True)
    delivery_date = models.DateTimeField(null=True, blank=True)
    payment_due_date = models.DateField(null=True, blank=True)

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    discount_type = models.CharField(
        max_length=20,
        choices=[
            ("percentage", "Pourcentage"),
            ("amount", "Montant"),
        ],
        default="percentage"
    )
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    shipping_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    payment_method = models.CharField(max_length=50, blank=True)
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="pending"
    )
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    amount_due = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    delivery_method = models.CharField(max_length=50, blank=True)
    delivery_address = models.TextField(blank=True, null=True)
    delivery_status = models.CharField(max_length=50, default="pending")
    tracking_number = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft"
    )
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    qr_code = models.ImageField(
        upload_to="qrcodes/sales/",
        null=True,
        blank=True
    )
    qr_code_data = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_created"
    )

    class Meta:
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        ordering = ["-sale_date"]
        indexes = [
            models.Index(fields=['-sale_date'], name='vente_sale_date_idx'),
            models.Index(fields=['sale_date', 'status'],
                         name='vente_date_status_idx'),
            models.Index(fields=['sale_date', 'payment_status'],
                         name='vente_date_pay_idx'),
            models.Index(fields=['status'], name='vente_status_idx'),
            models.Index(fields=['payment_status'],
                         name='vente_pay_status_idx'),
            models.Index(fields=['client', '-sale_date'],
                         name='vente_client_date_idx'),
            models.Index(fields=['warehouse', '-sale_date'],
                         name='vente_wh_date_idx'),
            models.Index(fields=['invoice_number'], name='vente_invoice_idx'),
            models.Index(fields=['created_by'], name='vente_created_by_idx'),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.client_name}"

    def get_or_create_anonymous_client(self):
        """Récupère ou crée un client anonyme."""
        client = Client.objects.filter(
            name="Client anonyme",
            statut="actif"
        ).first()

        if client:
            return client

        count = Client.objects.count()
        return Client.objects.create(
            code=f"ANON-{date.today().year}-{count + 1:04d}",
            name="Client anonyme",
            type="particulier",
            phone="00000000",
            address="Non renseigné",
            statut="actif",
            notes="Client créé automatiquement pour des ventes sans client",
            created_by=self.created_by
        )

    def calculate_totals(self, save=True):
        self.subtotal = sum(
            (line.total for line in self.lines.all()),
            Decimal("0.00")
        )

        if self.discount_type == "percentage":
            self.discount_amount = (
                self.subtotal * self.discount_value / Decimal("100")
            )
        else:
            self.discount_amount = self.discount_value

        self.discount_amount = min(self.discount_amount, self.subtotal)
        after_discount = self.subtotal - self.discount_amount

        self.tax_amount = after_discount * self.tax_rate / Decimal("100")

        self.total = after_discount + self.tax_amount + self.shipping_fee

        self.amount_due = max(
            Decimal("0.00"),
            self.total - self.amount_paid
        )

        if self.amount_due <= 0:
            self.payment_status = "paid"
        elif self.amount_paid > 0:
            self.payment_status = "partial"
        else:
            self.payment_status = "pending"

        if save and self.pk:
            super().save(update_fields=[
                "subtotal", "discount_amount", "tax_amount",
                "total", "amount_due", "payment_status", "updated_at"
            ])

    def generate_qr_code(self):
        if not self.pk or not self.invoice_number:
            return

        data = {
            "type": "sale",
            "id": self.id,
            "number": self.invoice_number,
            "client": self.client_name,
            "total": str(self.total),
            "status": self.status,
            "url": f"/ventes/{self.id}/",
        }

        qr_data, buffer = generate_qr_image(data)
        self.qr_code_data = qr_data

        self.qr_code.save(
            f"qr_sale_{self.invoice_number}.png",
            File(buffer),
            save=False
        )

    @transaction.atomic
    def deduct_stock(self):
        """Déduit le stock en consommant les lots FIFO."""
        if not self.warehouse:
            raise ValidationError("L'entrepôt de vente est obligatoire.")

        lines = list(self.lines.select_related("product").all())

        if not lines:
            raise ValidationError(
                "La vente doit contenir au moins un produit.")

        for line in lines:
            stock = Stock.objects.select_for_update().filter(
                product=line.product,
                warehouse=self.warehouse
            ).first()

            if not stock:
                raise ValidationError(
                    f"Aucun stock trouvé pour {line.product.name}."
                )

            if stock.available_quantity < line.quantity:
                raise ValidationError(
                    f"Stock insuffisant pour {line.product.name}. "
                    f"Disponible : {stock.available_quantity}, "
                    f"Demandé : {line.quantity}."
                )

        for line in lines:
            stock = Stock.objects.select_for_update().get(
                product=line.product,
                warehouse=self.warehouse
            )

            lots = Lot.objects.select_for_update().filter(
                product=line.product,
                warehouse=self.warehouse,
                current_quantity__gt=0,
                is_blocked=False
            ).exclude(status="expired").order_by("expiry_date", "id")

            remaining = line.quantity

            for lot in lots:
                if remaining <= 0:
                    break

                quantity = min(lot.available_quantity, remaining)

                if quantity <= 0:
                    continue

                lot.current_quantity -= quantity
                lot.reserved_quantity = max(
                    0, lot.reserved_quantity - quantity)
                lot.last_used_date = date.today()

                if lot.expiry_date:
                    today = date.today()
                    alert_days = lot.product.alert_days if lot.product else 30

                    if lot.expiry_date < today:
                        lot.status = 'expired'
                    elif lot.expiry_date <= today + timedelta(days=alert_days):
                        lot.status = 'expiring'
                    else:
                        lot.status = 'good'

                lot.save(update_fields=[
                    'current_quantity', 'reserved_quantity',
                    'last_used_date', 'status'
                ])

                StockMovement.objects.create(
                    product=line.product,
                    lot=lot,
                    from_warehouse=self.warehouse,
                    to_warehouse=None,
                    movement_type="sale_out",
                    quantity=quantity,
                    previous_quantity=lot.current_quantity + quantity,
                    new_quantity=lot.current_quantity,
                    reference_type="sale",
                    reference_id=self.id,
                    reference_number=self.invoice_number,
                    reason=f"Vente {self.invoice_number}",
                    notes=f"Ligne {line.id} - {line.quantity} unités",
                    created_by=self.created_by
                )

                remaining -= quantity

            if remaining > 0:
                raise ValidationError(
                    f"Stock insuffisant pour {line.product.name}. "
                    f"Reste à fournir : {remaining} unités."
                )

        for line in lines:
            stock = Stock.objects.filter(
                product=line.product,
                warehouse=self.warehouse
            ).first()

            if stock:
                stock.update_quantity()

                total_reserved = Lot.objects.filter(
                    product=line.product,
                    warehouse=self.warehouse,
                    is_blocked=False
                ).exclude(status='expired').aggregate(
                    total=models.Sum('reserved_quantity')
                )['total'] or 0

                stock.reserved_quantity = total_reserved
                stock.save(update_fields=['reserved_quantity', 'last_update'])

        for line in lines:
            line.product.update_status()

    @transaction.atomic
    def restore_stock(self):
        """Restaure le stock lors de l'annulation d'une vente."""
        if not self.warehouse:
            return

        movements = StockMovement.objects.filter(
            reference_type="sale",
            reference_id=self.id,
            movement_type="sale_out"
        ).select_related("product", "lot")

        if not movements.exists():
            return

        for movement in movements:
            if not movement.lot:
                continue

            lot = movement.lot
            lot.current_quantity += movement.quantity

            if lot.expiry_date:
                today = date.today()
                if lot.expiry_date < today:
                    lot.status = 'expired'
                elif lot.expiry_date <= today + timedelta(days=lot.product.alert_days):
                    lot.status = 'expiring'
                else:
                    lot.status = 'good'

            lot.save(update_fields=['current_quantity', 'status'])

            StockMovement.objects.create(
                product=movement.product,
                lot=lot,
                from_warehouse=None,
                to_warehouse=self.warehouse,
                movement_type="return_in",
                quantity=movement.quantity,
                previous_quantity=lot.current_quantity - movement.quantity,
                new_quantity=lot.current_quantity,
                reference_type="sale_cancel",
                reference_id=self.id,
                reference_number=self.invoice_number,
                reason=f"Annulation vente {self.invoice_number}",
                notes=f"Restauration du mouvement {movement.id}",
                created_by=self.created_by
            )

        product_ids = movements.values_list("product_id", flat=True).distinct()

        for product_id in product_ids:
            stock = Stock.objects.filter(
                product_id=product_id,
                warehouse=self.warehouse
            ).first()

            if stock:
                stock.update_quantity()

                total_reserved = Lot.objects.filter(
                    product_id=product_id,
                    warehouse=self.warehouse,
                    is_blocked=False
                ).exclude(status='expired').aggregate(
                    total=models.Sum('reserved_quantity')
                )['total'] or 0

                stock.reserved_quantity = total_reserved
                stock.save(update_fields=['reserved_quantity', 'last_update'])

        for product_id in product_ids:
            product = Product.objects.filter(id=product_id).first()
            if product:
                product.update_status()

    def get_stock_details(self):
        """Méthode de débogage pour afficher les détails du stock."""
        if not self.warehouse:
            return {"error": "Aucun entrepôt associé"}

        details = []
        for line in self.lines.select_related("product").all():
            stock = Stock.objects.filter(
                product=line.product,
                warehouse=self.warehouse
            ).first()

            lots = Lot.objects.filter(
                product=line.product,
                warehouse=self.warehouse,
                current_quantity__gt=0,
                is_blocked=False
            ).exclude(status="expired").order_by("expiry_date")

            lots_details = [
                {
                    "lot_number": lot.lot_number,
                    "current_quantity": lot.current_quantity,
                    "available_quantity": lot.available_quantity,
                    "expiry_date": lot.expiry_date,
                    "status": lot.status
                }
                for lot in lots
            ]

            details.append({
                "product": line.product.name,
                "product_code": line.product.code,
                "quantity_sold": line.quantity,
                "stock_quantity": stock.quantity if stock else 0,
                "stock_available": stock.available_quantity if stock else 0,
                "lots": lots_details
            })

        return details

    @transaction.atomic
    def generate_invoice(self):
        if self.invoices.exists():
            return self.invoices.first()

        client = self.client

        if not client:
            client = self.get_or_create_anonymous_client()
            self.client = client
            super().save(update_fields=["client", "updated_at"])

        facture = Facture.objects.create(
            invoice_number=generate_number(Facture, "invoice_number", "FAC"),
            sale=self,
            client=client,
            due_date=(
                self.payment_due_date
                or date.today() + timedelta(days=30)
            ),
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            total=self.total,
            status="sent",
            notes=(
                f"Facture générée automatiquement "
                f"depuis la vente {self.invoice_number}"
            )
        )

        facture.generate_qr_code()
        facture.save(update_fields=["qr_code", "qr_code_data", "updated_at"])

        return facture

    def save(self, *args, **kwargs):
        """Sauvegarde avec gestion du statut et des opérations associées."""
        is_new = self.pk is None
        old_status = None

        if self.pk:
            old_status = (
                Vente.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

        if not self.client_name:
            self.client_name = (
                self.client.name if self.client else "Client anonyme"
            )

        if not self.invoice_number:
            self.invoice_number = generate_number(
                Vente, "invoice_number", "INV"
            )

        is_confirming = (
            not is_new
            and old_status == "draft"
            and self.status == "confirmed"
        )

        is_cancelling = (
            not is_new
            and old_status in ["confirmed", "paid", "delivered"]
            and self.status == "cancelled"
        )

        super().save(*args, **kwargs)

        if not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=[
                "qr_code", "qr_code_data", "updated_at"])

        if is_confirming:
            try:
                self.deduct_stock()
                if not self.invoices.exists():
                    self.generate_invoice()
            except Exception as error:
                self.status = "draft"
                super().save(update_fields=["status", "updated_at"])
                raise ValidationError(
                    f"Erreur lors de la confirmation : {error}")

        if is_cancelling:
            try:
                self.restore_stock()
            except Exception as error:
                self.status = old_status
                super().save(update_fields=["status", "updated_at"])
                raise ValidationError(f"Erreur lors de l'annulation : {error}")


# ============================================================
# LIGNE VENTE
# ============================================================

class LigneVente(models.Model):
    """Ligne de vente avec gestion du type de prix (détail/gros)."""

    sale = models.ForeignKey(
        'Vente',
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Vente"
    )
    product = models.ForeignKey(
        'produits_stocks.Product',
        on_delete=models.PROTECT,
        verbose_name="Produit"
    )
    lot = models.ForeignKey(
        'produits_stocks.Lot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Lot"
    )

    quantity = models.PositiveIntegerField(verbose_name="Quantité")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix unitaire"
    )
    discount = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal("0.00"), verbose_name="Remise"
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal("0.00"), verbose_name="Taux de TVA (%)"
    )
    total = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal("0.00"), verbose_name="Total ligne"
    )

    PRICE_TYPE_CHOICES = (
        ('detail', 'Prix de détail'),
        ('gros', 'Prix de gros'),
    )
    price_type = models.CharField(
        max_length=20,
        choices=PRICE_TYPE_CHOICES,
        default='detail',
        verbose_name="Type de prix utilisé"
    )

    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de création"
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date de modification"
    )

    class Meta:
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
        ordering = ['id']
        indexes = [
            models.Index(fields=['sale'], name='lignevente_sale_idx'),
            models.Index(fields=['product'], name='lignevente_product_idx'),
            models.Index(fields=['lot'], name='lignevente_lot_idx'),
        ]

    def __str__(self):
        return (
            f"{self.sale.invoice_number} - "
            f"{self.product.name} "
            f"({self.quantity} x {self.unit_price})"
        )

    @property
    def subtotal(self):
        return Decimal(self.quantity) * self.unit_price

    @property
    def discount_amount(self):
        if self.discount > 0:
            return self.discount
        return Decimal("0.00")

    @property
    def tax_amount(self):
        if self.tax_rate > 0:
            return (self.subtotal - self.discount) * (self.tax_rate / Decimal("100"))
        return Decimal("0.00")

    @property
    def total_without_tax(self):
        return self.subtotal - self.discount

    @property
    def price_type_display(self):
        return dict(self.PRICE_TYPE_CHOICES).get(self.price_type, self.price_type)

    def calculate_total(self):
        subtotal = Decimal(self.quantity) * self.unit_price
        self.total = max(Decimal("0.00"), subtotal - self.discount)
        return self.total

    def save(self, *args, **kwargs):
        if self.quantity <= 0:
            raise ValidationError("La quantité doit être supérieure à zéro.")

        if self.unit_price <= 0:
            raise ValidationError(
                "Le prix unitaire doit être supérieur à zéro.")

        if self.price_type not in ['detail', 'gros']:
            raise ValidationError(
                "Le type de prix doit être 'detail' ou 'gros'."
            )

        self.calculate_total()
        super().save(*args, **kwargs)

        if self.sale:
            self.sale.calculate_totals()

    def get_product_price(self):
        if self.price_type == 'gros':
            return self.product.wholesale_price or self.product.selling_price
        return self.product.selling_price

    def get_price_type_display(self):
        return dict(self.PRICE_TYPE_CHOICES).get(
            self.price_type, 'Prix de détail'
        )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product.id,
            'product_name': self.product.name,
            'product_code': self.product.code,
            'lot_number': self.lot.lot_number if self.lot else None,
            'quantity': self.quantity,
            'unit_price': float(self.unit_price),
            'price_type': self.price_type,
            'price_type_display': self.get_price_type_display(),
            'discount': float(self.discount),
            'tax_rate': float(self.tax_rate),
            'subtotal': float(self.subtotal),
            'total': float(self.total),
            'notes': self.notes,
        }


# ============================================================
# FACTURE
# ============================================================

class Facture(models.Model):

    STATUS_CHOICES = (
        ("draft", "Brouillon"),
        ("sent", "Envoyée"),
        ("paid", "Payée"),
        ("overdue", "En retard"),
        ("cancelled", "Annulée"),
        ("partial", "Partiellement payée"),
    )

    invoice_number = models.CharField(max_length=50, unique=True)
    sale = models.ForeignKey(
        Vente,
        on_delete=models.CASCADE,
        related_name="invoices"
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="invoices"
    )

    invoice_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft"
    )

    pdf_file = models.FileField(
        upload_to="invoices/",
        null=True,
        blank=True
    )

    notes = models.TextField(blank=True)

    qr_code = models.ImageField(
        upload_to="qrcodes/invoices/",
        null=True,
        blank=True
    )
    qr_code_data = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-invoice_date"]
        indexes = [
            models.Index(fields=['-invoice_date'], name='facture_date_idx'),
            models.Index(fields=['status'], name='facture_status_idx'),
            models.Index(fields=['client', '-invoice_date'],
                         name='facture_client_date_idx'),
            models.Index(fields=['sale'], name='facture_sale_idx'),
            models.Index(fields=['invoice_number'], name='facture_number_idx'),
            models.Index(fields=['due_date'], name='facture_due_date_idx'),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.client.name}"

    @property
    def remaining_amount(self):
        return max(Decimal("0.00"), self.total - self.amount_paid)

    def update_payment_status(self):
        total_paid = (
            self.paiements.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        self.amount_paid = total_paid

        if self.amount_paid >= self.total:
            self.status = "paid"
        elif self.amount_paid > 0:
            self.status = "partial"
        else:
            self.status = "sent"

        super().save(update_fields=[
            "amount_paid", "status", "updated_at"
        ])

    def generate_qr_code(self):
        if not self.pk:
            return

        data = {
            "type": "invoice",
            "id": self.id,
            "number": self.invoice_number,
            "client": self.client.name,
            "total": str(self.total),
            "status": self.status,
            "url": f"/factures/{self.id}/",
        }

        qr_data, buffer = generate_qr_image(data)
        self.qr_code_data = qr_data

        self.qr_code.save(
            f"qr_invoice_{self.invoice_number}.png",
            File(buffer),
            save=False
        )

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_number(
                Facture, "invoice_number", "FAC"
            )
        super().save(*args, **kwargs)


# ============================================================
# PAIEMENT
# ============================================================

class Paiement(models.Model):
    METHOD_CHOICES = (
        ("cash", "Espèces"),
        ("card", "Carte bancaire"),
        ("check", "Chèque"),
        ("transfer", "Virement"),
        ("mobile_money", "Mobile Money"),
        ("credit", "Crédit"),
        ("wallet", "Porte-monnaie électronique"),
    )

    facture = models.ForeignKey(
        Facture,
        on_delete=models.CASCADE,
        related_name="paiements"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=100, blank=True)
    payment_date = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    notes = models.TextField(blank=True)

    qr_code = models.ImageField(
        upload_to="qrcodes/payments/",
        null=True,
        blank=True
    )
    qr_code_data = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    caisse_destination = models.ForeignKey(
        'tresorerie.Caisse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_entrants',
        verbose_name="Caisse de destination"
    )
    compte_destination = models.ForeignKey(
        'tresorerie.CompteBancaire',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_entrants',
        verbose_name="Compte bancaire de destination"
    )

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ["-payment_date"]
        indexes = [
            models.Index(fields=['-payment_date'], name='paiement_date_idx'),
            models.Index(fields=['facture', '-payment_date'],
                         name='paiement_facture_date_idx'),
            models.Index(fields=['method'], name='paiement_method_idx'),
        ]

    def __str__(self):
        return f"{self.facture.invoice_number} - {self.amount} FCFA"

    def clean(self):
        if self.amount <= 0:
            raise ValidationError(
                "Le montant du paiement doit être supérieur à zéro."
            )

        if self.facture_id:
            previous_paid = (
                self.facture.paiements
                .exclude(pk=self.pk)
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )

            if previous_paid + self.amount > self.facture.total:
                raise ValidationError(
                    "Le paiement dépasse le montant restant."
                )

        if self.caisse_destination and self.compte_destination:
            raise ValidationError(
                "Vous ne pouvez choisir qu'une seule destination : caisse OU compte bancaire."
            )

        if self.facture and self.facture.sale and self.facture.sale.warehouse:
            warehouse = self.facture.sale.warehouse
            if self.caisse_destination and self.caisse_destination.warehouse != warehouse:
                raise ValidationError(
                    "La caisse choisie n'appartient pas à l'entrepôt de la vente."
                )
            if self.compte_destination and self.compte_destination.warehouse != warehouse:
                raise ValidationError(
                    "Le compte bancaire choisi n'appartient pas à l'entrepôt de la vente."
                )

    def generate_qr_code(self):
        if not self.pk:
            return

        data = {
            "type": "payment",
            "id": self.id,
            "amount": str(self.amount),
            "method": self.method,
            "invoice": self.facture.invoice_number,
            "reference": self.reference,
            "url": f"/paiements/{self.id}/",
        }

        qr_data, buffer = generate_qr_image(data)
        self.qr_code_data = qr_data

        self.qr_code.save(
            f"qr_payment_{self.id}.png",
            File(buffer),
            save=False
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new:
            self.generate_qr_code()
            super().save(update_fields=[
                "qr_code", "qr_code_data", "updated_at"
            ])

        self.facture.update_payment_status()

        sale = self.facture.sale

        if sale:
            total_paid = (
                sale.invoices.aggregate(
                    total=Sum("amount_paid")
                )["total"]
                or Decimal("0.00")
            )

            sale.amount_paid = total_paid
            sale.amount_due = max(
                Decimal("0.00"),
                sale.total - sale.amount_paid
            )

            if sale.amount_due <= 0:
                sale.payment_status = "paid"
            elif sale.amount_paid > 0:
                sale.payment_status = "partial"
            else:
                sale.payment_status = "pending"

            super(Vente, sale).save(update_fields=[
                "amount_paid", "amount_due",
                "payment_status", "updated_at"
            ])


# ============================================================
# AVOIR (NOTE DE CRÉDIT)
# ============================================================

class Avoir(models.Model):
    """Avoir client (note de crédit)."""

    TYPE_CHOICES = (
        ("refund", "Remboursement"),
        ("return", "Retour de marchandise"),
        ("discount", "Remise / Geste commercial"),
        ("error", "Erreur de facturation"),
    )

    avoir_number = models.CharField(
        max_length=50, unique=True, verbose_name="Numéro d'avoir"
    )
    sale = models.ForeignKey(
        "Vente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avoirs",
        verbose_name="Vente associée"
    )
    client = models.ForeignKey(
        "Client",
        on_delete=models.PROTECT,
        related_name="avoirs",
        verbose_name="Client"
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="refund",
        verbose_name="Type d'avoir"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Montant total"
    )
    reason = models.TextField(
        verbose_name="Raison",
        help_text="Motif de l'avoir (retour, remboursement, etc.)"
    )
    date = models.DateField(auto_now_add=True, verbose_name="Date")
    notes = models.TextField(blank=True, verbose_name="Notes internes")

    restore_stock = models.BooleanField(
        default=False,
        verbose_name="Stock restauré",
        help_text="Indique si le stock a été restauré suite à cet avoir"
    )
    stock_restored_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Date de restauration du stock"
    )

    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="avoirs_created",
        verbose_name="Créé par"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Avoir"
        verbose_name_plural = "Avoirs"
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["avoir_number"], name='avoir_number_idx'),
            models.Index(fields=["client", "-date"],
                         name='avoir_client_date_idx'),
            models.Index(fields=["type"], name='avoir_type_idx'),
            models.Index(fields=["sale"], name='avoir_sale_idx'),
        ]

    def __str__(self):
        return (
            f"{self.avoir_number} - "
            f"{self.client.name if self.client else 'N/A'} - "
            f"{self.amount:,.0f} FCFA"
        )

    def save(self, *args, **kwargs):
        if not self.avoir_number:
            last_avoir = Avoir.objects.order_by("-id").first()
            if last_avoir and last_avoir.avoir_number:
                try:
                    num = int(last_avoir.avoir_number.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            self.avoir_number = f"AV-{date.today().year}-{num:04d}"
        super().save(*args, **kwargs)

    @property
    def type_display(self):
        return self.get_type_display()

    @property
    def is_refund(self):
        return self.type == "refund"

    @property
    def is_return(self):
        return self.type == "return"

    @property
    def can_restore_stock(self):
        return (
            self.sale is not None
            and self.type in ["refund", "return"]
            and not self.restore_stock
            and self.lignes.exists()
        )

    @property
    def nombre_produits(self):
        return self.lignes.count()

    @property
    def quantite_totale(self):
        return self.lignes.aggregate(
            total=models.Sum("quantity")
        )["total"] or 0

    def recalculate_amount(self):
        total = self.lignes.aggregate(
            total=models.Sum("total")
        )["total"] or 0
        self.amount = total
        self.save(update_fields=["amount", "updated_at"])
        return total

    def restore_partial_stock(self, user=None):
        """Restaure le stock UNIQUEMENT pour les produits retournés."""
        from produits_stocks.models import Stock, StockMovement

        if not self.sale:
            return {"success": False, "message": "Aucune vente associée", "details": []}

        if not self.sale.warehouse:
            return {"success": False, "message": "Aucun entrepôt défini", "details": []}

        if self.restore_stock:
            return {"success": False, "message": "Stock déjà restauré", "details": []}

        if not self.lignes.exists():
            return {"success": False, "message": "Aucune ligne à restaurer", "details": []}

        warehouse = self.sale.warehouse
        details = []

        for ligne in self.lignes.select_related("product", "ligne_vente").all():
            try:
                lot_origine = None
                if ligne.ligne_vente:
                    lot_origine = getattr(ligne.ligne_vente, "lot", None)

                quantite_retour = int(ligne.quantity)

                ancienne_qte_lot = None
                nouvelle_qte_lot = None

                if lot_origine:
                    ancienne_qte_lot = lot_origine.current_quantity
                    lot_origine.current_quantity += quantite_retour
                    lot_origine.save(update_fields=["current_quantity"])
                    nouvelle_qte_lot = lot_origine.current_quantity

                stock, _ = Stock.objects.get_or_create(
                    product=ligne.product,
                    warehouse=warehouse,
                    defaults={"quantity": 0, "reserved_quantity": 0},
                )

                ancienne_qte_stock = stock.quantity

                if lot_origine:
                    stock.update_quantity()
                else:
                    stock.quantity += quantite_retour
                    stock.save(update_fields=["quantity", "last_update"])

                nouvelle_qte_stock = stock.quantity

                movement = StockMovement.objects.create(
                    product=ligne.product,
                    lot=lot_origine,
                    from_warehouse=None,
                    to_warehouse=warehouse,
                    movement_type="return_in",
                    quantity=quantite_retour,
                    previous_quantity=ancienne_qte_lot or ancienne_qte_stock,
                    new_quantity=nouvelle_qte_lot or nouvelle_qte_stock,
                    reference_type="avoir",
                    reference_id=self.id,
                    reference_number=self.avoir_number,
                    reason=f"Retour avoir {self.avoir_number}",
                    notes=(
                        f"Retour partiel via avoir {self.avoir_number} - "
                        f"{self.reason[:200]}"
                    ),
                    created_by=user,
                )

                details.append({
                    "product_id": ligne.product.id,
                    "product_name": ligne.product.name,
                    "product_code": getattr(ligne.product, "code", ""),
                    "quantity": float(ligne.quantity),
                    "lot_id": lot_origine.id if lot_origine else None,
                    "lot_number": lot_origine.lot_number if lot_origine else None,
                    "stock_before": ancienne_qte_stock,
                    "stock_after": nouvelle_qte_stock,
                    "movement_id": movement.id,
                    "movement_type": movement.movement_type,
                    "movement_type_display": movement.get_movement_type_display(),
                })

            except Exception as e:
                logger.exception(
                    f"❌ Erreur restauration pour {ligne.product.name}"
                )
                details.append({
                    "product_id": ligne.product.id,
                    "product_name": ligne.product.name,
                    "quantity": float(ligne.quantity),
                    "error": str(e),
                })

        self.restore_stock = True
        self.stock_restored_at = timezone.now()
        self.save(update_fields=["restore_stock",
                  "stock_restored_at", "updated_at"])

        nb_ok = len([d for d in details if "error" not in d])
        nb_err = len([d for d in details if "error" in d])

        if nb_err > 0:
            return {
                "success": True,
                "message": f"Stock restauré pour {nb_ok} produit(s), {nb_err} erreur(s)",
                "details": details,
                "errors": nb_err,
            }

        return {
            "success": True,
            "message": f"Stock restauré pour {nb_ok} produit(s)",
            "details": details,
            "errors": 0,
        }


# ============================================================
# LIGNE AVOIR
# ============================================================

class LigneAvoir(models.Model):
    """Produit retourné dans un avoir."""

    avoir = models.ForeignKey(
        Avoir,
        on_delete=models.CASCADE,
        related_name="lignes",
    )
    product = models.ForeignKey(
        "produits_stocks.Product",
        on_delete=models.PROTECT,
        related_name="lignes_avoir",
    )
    ligne_vente = models.ForeignKey(
        "ventes_clients.LigneVente",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="lignes_avoir",
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Quantité retournée",
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name="Prix unitaire",
    )
    discount = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0, verbose_name="Remise",
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0, verbose_name="Total ligne",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ligne d'avoir"
        verbose_name_plural = "Lignes d'avoir"
        ordering = ["id"]
        indexes = [
            models.Index(fields=['avoir'], name='ligneavoir_avoir_idx'),
            models.Index(fields=['product'], name='ligneavoir_product_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity:g} - {self.total:,.0f} FCFA"

    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.unit_price) - (self.discount or 0)
        super().save(*args, **kwargs)


# ============================================================
# TAXE
# ============================================================

class Taxe(models.Model):
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Taxe"
        verbose_name_plural = "Taxes"
        indexes = [
            models.Index(fields=['is_active'], name='taxe_active_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


# ============================================================
# REMISE
# ============================================================

class Remise(models.Model):
    TYPE_CHOICES = (
        ("percentage", "Pourcentage"),
        ("amount", "Montant fixe"),
    )

    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_purchase = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    clients = models.ManyToManyField(Client, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Remise"
        verbose_name_plural = "Remises"
        indexes = [
            models.Index(fields=['is_active'], name='remise_active_idx'),
        ]

    def __str__(self):
        suffix = "%" if self.type == "percentage" else " FCFA"
        return f"{self.name} - {self.value}{suffix}"

    def is_valid(self):
        today = date.today()
        if not self.is_active:
            return False
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        return True


# ============================================================
# CLIENT WALLET
# ============================================================

class ClientWallet(models.Model):
    """Porte-monnaie électronique du client."""

    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name="Client"
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Solde disponible"
    )
    total_deposits = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total des dépôts"
    )
    total_used = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total utilisé"
    )
    is_active = models.BooleanField(default=True, verbose_name="Wallet actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Porte-monnaie client"
        verbose_name_plural = "Porte-monnaie clients"
        indexes = [
            models.Index(fields=['-created_at'], name='wallet_created_idx'),
            models.Index(fields=['is_active'], name='wallet_active_idx'),
        ]

    def __str__(self):
        return f"{self.client.name} - {self.balance:,.0f} FCFA"

    @transaction.atomic
    def credit(self, amount, source, reference, notes='', created_by=None):
        if amount <= 0:
            raise ValidationError("Le montant doit être supérieur à zéro")

        self.balance += amount
        self.total_deposits += amount
        self.save()

        WalletTransaction.objects.create(
            wallet=self,
            type='credit',
            amount=amount,
            source=source,
            reference=reference,
            notes=notes,
            balance_after=self.balance,
            created_by=created_by
        )

        return self.balance

    @transaction.atomic
    def debit(self, amount, source, reference, notes='', created_by=None):
        if amount <= 0:
            raise ValidationError("Le montant doit être supérieur à zéro")

        if amount > self.balance:
            raise ValidationError(
                f"Solde insuffisant. Disponible : {self.balance:,.0f} FCFA"
            )

        self.balance -= amount
        self.total_used += amount
        self.save()

        WalletTransaction.objects.create(
            wallet=self,
            type='debit',
            amount=amount,
            source=source,
            reference=reference,
            notes=notes,
            balance_after=self.balance,
            created_by=created_by
        )

        return self.balance


class WalletTransaction(models.Model):
    """Historique des transactions du wallet."""

    TRANSACTION_TYPES = (
        ('credit', 'Crédit'),
        ('debit', 'Débit'),
    )

    SOURCE_CHOICES = (
        ('deposit', 'Dépôt en espèces'),
        ('payment', 'Paiement facture'),
        ('avoir', 'Avoir commercial'),
        ('refund', 'Remboursement'),
        ('transfer', 'Transfert'),
        ('adjustment', 'Ajustement'),
    )

    wallet = models.ForeignKey(
        ClientWallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    balance_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name="Solde après transaction"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transactions'
    )

    class Meta:
        verbose_name = "Transaction wallet"
        verbose_name_plural = "Transactions wallet"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', '-created_at'],
                         name='wallettx_wallet_date_idx'),
            models.Index(fields=['type'], name='wallettx_type_idx'),
            models.Index(fields=['source'], name='wallettx_source_idx'),
        ]

    def __str__(self):
        return f"{self.get_type_display()} - {self.amount:,.0f} FCFA"


# ============================================================
# STOCK CLIENT (MARCHANDISES DÉPOSÉES CHEZ LE CLIENT)
# ============================================================

class ClientStock(models.Model):
    """
    Stock de marchandises déposées chez un client.
    ⚠️ DIFFÉRENT de Stock (produits_stocks).
    """
    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name='client_stock',
        verbose_name="Client"
    )
    is_active = models.BooleanField(default=True, verbose_name="Stock actif")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stock client"
        verbose_name_plural = "Stocks clients"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['-updated_at'],
                         name='clientstock_updated_idx'),
            models.Index(fields=['is_active'], name='clientstock_active_idx'),
        ]

    def __str__(self):
        return f"Stock de {self.client.name}"

    @property
    def total_quantity(self):
        return self.lignes.aggregate(
            total=models.Sum('quantity')
        )['total'] or Decimal('0')

    @property
    def total_value(self):
        return sum(
            (ligne.total_value for ligne in self.lignes.all()),
            Decimal('0')
        )

    @property
    def nombre_produits(self):
        return self.lignes.count()


class ClientStockLigne(models.Model):
    """Ligne de stock client : un produit avec sa quantité."""

    stock = models.ForeignKey(
        ClientStock,
        on_delete=models.CASCADE,
        related_name='lignes',
        verbose_name="Stock client"
    )
    product = models.ForeignKey(
        'produits_stocks.Product',
        on_delete=models.PROTECT,
        related_name='client_stock_lignes',
        verbose_name="Produit"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Quantité"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Prix unitaire de référence"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ligne de stock client"
        verbose_name_plural = "Lignes de stock client"
        unique_together = [['stock', 'product']]
        ordering = ['product__name']
        indexes = [
            models.Index(fields=['stock'], name='csl_stock_idx'),
            models.Index(fields=['product'], name='csl_product_idx'),
            models.Index(fields=['stock', 'product'],
                         name='csl_stock_product_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    @property
    def total_value(self):
        return self.quantity * self.unit_price


# ============================================================
# MOUVEMENT DE STOCK CLIENT
# ============================================================

class ClientStockMovement(models.Model):
    """
    Mouvement de stock client (entrée/sortie).
    """

    TYPE_CHOICES = (
        ('deposit', 'Dépôt'),
        ('withdrawal', 'Retrait'),
        ('adjustment', 'Ajustement'),
        ('sale', 'Vente au client'),
        ('return', 'Retour client'),
        ('delivery', 'Livraison vers destinataire'),
    )

    client_stock = models.ForeignKey(
        ClientStock,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name="Stock client"
    )
    product = models.ForeignKey(
        'produits_stocks.Product',
        on_delete=models.PROTECT,
        related_name='client_stock_movements',
        verbose_name="Produit"
    )
    movement_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        verbose_name="Type de mouvement"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name="Quantité"
    )
    previous_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Quantité précédente"
    )
    new_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Nouvelle quantité"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Prix unitaire"
    )
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='client_stock_movements_created',
        verbose_name="Créé par"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mouvement de stock client"
        verbose_name_plural = "Mouvements de stock client"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client_stock', '-created_at'],
                         name='csm_stock_date_idx'),
            models.Index(fields=['product', '-created_at'],
                         name='csm_product_date_idx'),
            models.Index(fields=['movement_type'], name='csm_type_idx'),
        ]

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} - "
            f"{self.product.name} x {self.quantity}"
        )

    @property
    def is_incoming(self):
        return self.movement_type in ['deposit', 'return', 'adjustment']

    @property
    def is_outgoing(self):
        return self.movement_type in ['withdrawal', 'sale', 'delivery']

    @property
    def quantity_signed(self):
        if self.is_incoming:
            return self.quantity
        elif self.is_outgoing:
            return -self.quantity
        return self.quantity

    @property
    def type_display(self):
        return self.get_movement_type_display()


# ============================================================
# LIVRAISON CLIENT
# ============================================================

class ClientDelivery(models.Model):
    """
    Livraison des produits stockés chez le client vers un destinataire.
    """

    STATUS_CHOICES = (
        ('pending', 'En attente de validation'),
        ('confirmed', 'Validée'),
        ('in_transit', 'En cours de livraison'),
        ('delivered', 'Livré'),
        ('cancelled', 'Annulé'),
        ('rejected', 'Rejetée'),
    )

    delivery_number = models.CharField(
        max_length=50, unique=True,
        verbose_name="Numéro de livraison"
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name='client_deliveries',
        verbose_name="Client (source du stock)"
    )
    client_stock = models.ForeignKey(
        ClientStock,
        on_delete=models.CASCADE,
        related_name='deliveries',
        verbose_name="Stock client concerné"
    )

    recipient_name = models.CharField(
        max_length=200, verbose_name="Nom du destinataire"
    )
    recipient_phone = models.CharField(
        max_length=20, verbose_name="Téléphone du destinataire"
    )
    recipient_address = models.TextField(
        blank=True, verbose_name="Adresse de livraison"
    )
    recipient_email = models.EmailField(
        blank=True, verbose_name="Email du destinataire"
    )
    recipient_notes = models.TextField(
        blank=True, verbose_name="Notes sur le destinataire"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Statut"
    )

    request_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Date de la demande"
    )
    confirmed_date = models.DateTimeField(
        null=True, blank=True, verbose_name="Date de validation"
    )
    shipped_date = models.DateTimeField(
        null=True, blank=True, verbose_name="Date d'expédition"
    )
    delivered_date = models.DateTimeField(
        null=True, blank=True, verbose_name="Date de livraison"
    )

    created_by_client = models.BooleanField(
        default=False,
        verbose_name="Créée par le client",
        help_text="True si la demande a été créée par le client lui-même"
    )

    delivery_method = models.CharField(
        max_length=50, blank=True, verbose_name="Mode de livraison"
    )
    carrier = models.CharField(
        max_length=100, blank=True, verbose_name="Transporteur"
    )
    tracking_number = models.CharField(
        max_length=100, blank=True, verbose_name="Numéro de suivi"
    )
    vehicle_plate = models.CharField(
        max_length=50, blank=True, verbose_name="Immatriculation véhicule"
    )
    driver_name = models.CharField(
        max_length=100, blank=True, verbose_name="Nom du chauffeur"
    )
    driver_phone = models.CharField(
        max_length=20, blank=True, verbose_name="Téléphone du chauffeur"
    )

    total_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Quantité totale"
    )
    total_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Valeur totale"
    )

    notes = models.TextField(blank=True, verbose_name="Notes internes")
    client_notes = models.TextField(
        blank=True, verbose_name="Message au client")

    rejection_reason = models.TextField(
        blank=True,
        verbose_name="Raison du rejet",
        help_text="Raison pour laquelle la demande a été rejetée (admin)"
    )

    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='client_deliveries_created',
        verbose_name="Créé par"
    )
    validated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='client_deliveries_validated',
        verbose_name="Validé par"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Livraison client"
        verbose_name_plural = "Livraisons client"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['client', '-created_at'],
                         name='cd_client_date_idx'),
            models.Index(fields=['status', '-created_at'],
                         name='cd_status_date_idx'),
            models.Index(fields=['delivery_number'], name='cd_number_idx'),
            models.Index(fields=['created_by_client'],
                         name='cd_by_client_idx'),
        ]

    def __str__(self):
        return (
            f"{self.delivery_number} - {self.client.name} "
            f"→ {self.recipient_name} ({self.get_status_display()})"
        )

    def save(self, *args, **kwargs):
        if not self.delivery_number:
            last = ClientDelivery.objects.order_by('-id').first()
            if last and last.delivery_number:
                try:
                    num = int(last.delivery_number.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            self.delivery_number = f"LIV-{date.today().year}-{num:04d}"
        super().save(*args, **kwargs)

    @property
    def status_display(self):
        return self.get_status_display()

    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_confirmed(self):
        return self.status == 'confirmed'

    @property
    def is_in_transit(self):
        return self.status == 'in_transit'

    @property
    def is_delivered(self):
        return self.status == 'delivered'

    @property
    def is_cancelled(self):
        return self.status == 'cancelled'

    @property
    def is_rejected(self):
        return self.status == 'rejected'

    @property
    def can_be_edited_by_client(self):
        return self.created_by_client and self.status == 'pending'

    @property
    def can_be_cancelled_by_client(self):
        return self.created_by_client and self.status in ['pending', 'confirmed']

    @property
    def can_be_validated(self):
        return self.status == 'pending'

    @property
    def can_be_rejected(self):
        return self.status == 'pending'

    @property
    def can_be_started(self):
        return self.status == 'confirmed'

    @property
    def can_be_confirmed(self):
        return self.status in ['confirmed', 'in_transit']

    def recalculate_totals(self):
        total_qty = self.lignes.aggregate(
            total=models.Sum('quantity')
        )['total'] or Decimal('0')

        total_val = self.lignes.aggregate(
            total=models.Sum('total_value')
        )['total'] or Decimal('0')

        self.total_quantity = total_qty
        self.total_value = total_val
        self.save(update_fields=['total_quantity',
                  'total_value', 'updated_at'])

    def mark_as_confirmed(self, user=None):
        self.status = 'confirmed'
        self.confirmed_date = timezone.now()
        if user:
            self.validated_by = user
        self.save(update_fields=[
                  'status', 'confirmed_date', 'validated_by', 'updated_at'])

    def mark_as_rejected(self, user=None, reason=''):
        self.status = 'rejected'
        self.rejection_reason = reason
        if user:
            self.validated_by = user
        self.save(update_fields=[
                  'status', 'rejection_reason', 'validated_by', 'updated_at'])

    def mark_as_in_transit(self, user=None):
        self.status = 'in_transit'
        self.shipped_date = timezone.now()
        self.save(update_fields=['status', 'shipped_date', 'updated_at'])

    def mark_as_delivered(self, user=None):
        self.status = 'delivered'
        self.delivered_date = timezone.now()
        if user:
            self.validated_by = user
        self.save(update_fields=[
                  'status', 'delivered_date', 'validated_by', 'updated_at'])

    def mark_as_cancelled(self, reason=''):
        self.status = 'cancelled'
        if reason:
            self.notes = (self.notes or '') + f"\n[ANNULÉE] {reason}"
        self.save(update_fields=['status', 'notes', 'updated_at'])


# ============================================================
# LIGNE DE LIVRAISON CLIENT
# ============================================================

class ClientDeliveryLigne(models.Model):
    """Ligne de livraison (produit + quantité retirés du stock client)."""

    delivery = models.ForeignKey(
        ClientDelivery,
        on_delete=models.CASCADE,
        related_name='lignes',
        verbose_name="Livraison"
    )
    product = models.ForeignKey(
        'produits_stocks.Product',
        on_delete=models.PROTECT,
        related_name='client_delivery_lignes',
        verbose_name="Produit"
    )
    client_stock_ligne = models.ForeignKey(
        ClientStockLigne,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delivery_lignes',
        verbose_name="Ligne de stock client"
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name="Quantité"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Prix unitaire"
    )
    total_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Valeur totale"
    )
    quantity_before = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Quantité avant livraison"
    )
    quantity_after = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="Quantité après livraison"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ligne de livraison client"
        verbose_name_plural = "Lignes de livraison client"
        ordering = ['id']
        indexes = [
            models.Index(fields=['delivery'], name='cdl_delivery_idx'),
            models.Index(fields=['product'], name='cdl_product_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total_value = self.quantity * self.unit_price
        super().save(*args, **kwargs)
