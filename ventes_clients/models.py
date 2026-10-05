# apps/ventes_clients/models.py

import logging
from datetime import date
from django.db import models
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
    """
    Génère une image QR Code.
    """

    qr_data = json.dumps(
        data,
        ensure_ascii=False,
        default=str
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )

    qr.add_data(qr_data)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return qr_data, buffer


# ============================================================
# CLIENT
# ============================================================

class Client(models.Model):
    """
    Modèle Client ultra-simplifié avec seulement 7 champs essentiels
    """

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

    # 1. Code client (unique, obligatoire)
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Code client"
    )

    # 2. Nom / Raison sociale (obligatoire)
    name = models.CharField(
        max_length=200,
        verbose_name="Nom / Raison sociale"
    )

    # 3. Type de client (optionnel, défaut "particulier")
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="particulier",
        verbose_name="Type"
    )

    # 4. Téléphone (obligatoire)
    phone = models.CharField(
        max_length=20,
        verbose_name="Téléphone"
    )

    # 5. Adresse (optionnel)
    address = models.TextField(
        blank=True,
        verbose_name="Adresse"
    )

    # 6. Statut (optionnel, défaut "actif")
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default="actif",
        verbose_name="Statut"
    )

    # 7. Notes (optionnel)
    notes = models.TextField(
        blank=True,
        verbose_name="Notes"
    )

    # Champs automatiques (non comptés dans les 7)
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

    def __str__(self):
        return f"{self.code} - {self.name}"

    @classmethod
    def create_anonymous(cls, created_by=None):
        """
        Crée un client anonyme de manière sécurisée
        """
        # Vérifier si un client anonyme existe déjà
        client = cls.objects.filter(
            name="Client anonyme",
            statut="actif"
        ).first()

        if client:
            return client

        count = cls.objects.count()
        return cls.objects.create(
            code=f"ANON-{date.today().year()}-{count + 1:04d}",
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
    """
    Devis / Proforma
    """
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

    def __str__(self):
        return f"{self.devis_number} - {self.client_name}"

    def calculate_totals(self):
        """
        Calcule les totaux du devis
        """
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
        """
        Génère un QR Code pour le devis
        """
        if not self.devis_number:
            return

        import json
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
        """
        Sauvegarde avec génération automatique du QR Code
        """
        if not self.pk:
            super().save(*args, **kwargs)

        if not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=['qr_code', 'qr_code_data'])
        else:
            super().save(*args, **kwargs)

    def convert_to_sale(self, user=None):
        """
        Convertit le devis en vente
        """
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
            raise ValueError(
                "Ce devis a déjà été converti en vente"
            )

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

    notes = models.TextField(
        blank=True
    )

    class Meta:
        verbose_name = "Ligne de devis"
        verbose_name_plural = "Lignes de devis"

    def __str__(self):
        return f"{self.devis.devis_number} - {self.product.name}"

    def save(self, *args, **kwargs):

        if self.quantity <= 0:
            raise ValidationError(
                "La quantité doit être supérieure à zéro."
            )

        gross_total = (
            Decimal(self.quantity)
            * self.unit_price
        )

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

    invoice_number = models.CharField(
        max_length=50,
        unique=True
    )

    order_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True
    )

    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales"
    )

    client_name = models.CharField(
        max_length=200,
        blank=True
    )

    client_phone = models.CharField(
        max_length=20,
        blank=True
    )

    client_email = models.EmailField(
        blank=True
    )

    client_address = models.TextField(
        blank=True
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventes"
    )

    sale_date = models.DateTimeField(
        auto_now_add=True
    )

    delivery_date = models.DateTimeField(
        null=True,
        blank=True
    )

    payment_due_date = models.DateField(
        null=True,
        blank=True
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
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
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )

    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )

    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00")
    )

    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )

    shipping_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    payment_method = models.CharField(
        max_length=50,
        blank=True
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="pending"
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    amount_due = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    delivery_method = models.CharField(
        max_length=50,
        blank=True
    )

    delivery_address = models.TextField(
        blank=True,
        null=True
    )

    delivery_status = models.CharField(
        max_length=50,
        default="pending"
    )

    tracking_number = models.CharField(
        max_length=100,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft"
    )

    notes = models.TextField(
        blank=True
    )

    internal_notes = models.TextField(
        blank=True
    )

    qr_code = models.ImageField(
        upload_to="qrcodes/sales/",
        null=True,
        blank=True
    )

    qr_code_data = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

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

    def __str__(self):
        return f"{self.invoice_number} - {self.client_name}"

    def get_or_create_anonymous_client(self):
        """Récupère ou crée un client anonyme"""
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
            (
                line.total
                for line in self.lines.all()
            ),
            Decimal("0.00")
        )

        if self.discount_type == "percentage":

            self.discount_amount = (
                self.subtotal
                * self.discount_value
                / Decimal("100")
            )

        else:

            self.discount_amount = self.discount_value

        self.discount_amount = min(
            self.discount_amount,
            self.subtotal
        )

        after_discount = (
            self.subtotal
            - self.discount_amount
        )

        self.tax_amount = (
            after_discount
            * self.tax_rate
            / Decimal("100")
        )

        self.total = (
            after_discount
            + self.tax_amount
            + self.shipping_fee
        )

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

            super().save(
                update_fields=[
                    "subtotal",
                    "discount_amount",
                    "tax_amount",
                    "total",
                    "amount_due",
                    "payment_status",
                    "updated_at"
                ]
            )

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

    # ================================================================
    # MÉTHODE DEDUCT_STOCK CORRIGÉE
    # ================================================================

    @transaction.atomic
    def deduct_stock(self):
        """
        Déduit le stock en consommant les lots FIFO
        La méthode est atomique : tout ou rien
        """
        if not self.warehouse:
            raise ValidationError("L'entrepôt de vente est obligatoire.")

        # Récupérer toutes les lignes de vente
        lines = list(self.lines.select_related("product").all())

        if not lines:
            raise ValidationError(
                "La vente doit contenir au moins un produit.")

        # ============================================================
        # ÉTAPE 1 : VÉRIFICATION GLOBALE AVANT DE MODIFIER LE STOCK
        # ============================================================
        for line in lines:
            # Vérifier que le produit existe dans le stock
            stock = Stock.objects.select_for_update().filter(
                product=line.product,
                warehouse=self.warehouse
            ).first()

            if not stock:
                raise ValidationError(
                    f"Aucun stock trouvé pour {line.product.name}."
                )

            # Vérifier la disponibilité
            if stock.available_quantity < line.quantity:
                raise ValidationError(
                    f"Stock insuffisant pour {line.product.name}. "
                    f"Disponible : {stock.available_quantity}, "
                    f"Demandé : {line.quantity}."
                )

        # ============================================================
        # ÉTAPE 2 : CONSOMMATION FIFO DES LOTS
        # ============================================================
        for line in lines:
            # Récupérer le stock du produit
            stock = Stock.objects.select_for_update().get(
                product=line.product,
                warehouse=self.warehouse
            )

            # Récupérer les lots disponibles (FIFO = par date d'expiration)
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

                # Quantité à prélever sur ce lot
                quantity = min(lot.available_quantity, remaining)

                if quantity <= 0:
                    continue

                # ============================================================
                # ÉTAPE 2.1 : CONSOMMER LE LOT (MODIFICATION DIRECTE)
                # ============================================================

                # Mettre à jour la quantité du lot
                lot.current_quantity -= quantity
                lot.reserved_quantity = max(
                    0, lot.reserved_quantity - quantity)
                lot.last_used_date = date.today()

                # Mettre à jour le statut du lot si nécessaire
                if lot.expiry_date:
                    today = date.today()
                    alert_days = lot.product.alert_days if lot.product else 30

                    if lot.expiry_date < today:
                        lot.status = 'expired'
                    elif lot.expiry_date <= today + timedelta(days=alert_days):
                        lot.status = 'expiring'
                    else:
                        lot.status = 'good'

                # Sauvegarder le lot modifié
                lot.save(update_fields=[
                    'current_quantity',
                    'reserved_quantity',
                    'last_used_date',
                    'status'
                ])

                # ============================================================
                # ÉTAPE 2.2 : CRÉER LE MOUVEMENT DE STOCK
                # ============================================================

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

            # Vérifier que tout a été consommé
            if remaining > 0:
                raise ValidationError(
                    f"Stock insuffisant pour {line.product.name}. "
                    f"Reste à fournir : {remaining} unités."
                )

        # ============================================================
        # ÉTAPE 3 : MISE À JOUR DU STOCK GLOBAL
        # ============================================================
        for line in lines:
            stock = Stock.objects.filter(
                product=line.product,
                warehouse=self.warehouse
            ).first()

            if stock:
                # Recalculer la quantité totale à partir des lots
                stock.update_quantity()

                # Mettre à jour la quantité réservée
                total_reserved = Lot.objects.filter(
                    product=line.product,
                    warehouse=self.warehouse,
                    is_blocked=False
                ).exclude(status='expired').aggregate(
                    total=models.Sum('reserved_quantity')
                )['total'] or 0

                stock.reserved_quantity = total_reserved
                stock.save(update_fields=['reserved_quantity', 'last_update'])

        # ============================================================
        # ÉTAPE 4 : METTRE À JOUR LE STATUT DU PRODUIT
        # ============================================================
        for line in lines:
            line.product.update_status()

    # ================================================================
    # MÉTHODE RESTORE_STOCK CORRIGÉE
    # ================================================================

    @transaction.atomic
    def restore_stock(self):
        """
        Restaure le stock lors de l'annulation d'une vente
        """
        if not self.warehouse:
            return

        # Récupérer tous les mouvements de sortie de cette vente
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

            # RESTAURER LE LOT
            lot = movement.lot

            # Augmenter la quantité du lot
            lot.current_quantity += movement.quantity

            # Mettre à jour le statut du lot
            if lot.expiry_date:
                today = date.today()
                if lot.expiry_date < today:
                    lot.status = 'expired'
                elif lot.expiry_date <= today + timedelta(days=lot.product.alert_days):
                    lot.status = 'expiring'
                else:
                    lot.status = 'good'

            lot.save(update_fields=['current_quantity', 'status'])

            # CRÉER LE MOUVEMENT DE RETOUR
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

        # METTRE À JOUR LE STOCK
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

        # METTRE À JOUR LE STATUT DES PRODUITS
        for product_id in product_ids:
            product = Product.objects.filter(id=product_id).first()
            if product:
                product.update_status()

    # ================================================================
    # MÉTHODE DE DÉBOGAGE
    # ================================================================

    def get_stock_details(self):
        """
        Méthode de débogage pour afficher les détails du stock
        """
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

    # ================================================================
    # AUTRES MÉTHODES EXISTANTES
    # ================================================================

    @transaction.atomic
    def generate_invoice(self):

        if self.invoices.exists():
            return self.invoices.first()

        client = self.client

        if not client:
            client = self.get_or_create_anonymous_client()
            self.client = client
            super().save(
                update_fields=[
                    "client",
                    "updated_at"
                ]
            )

        facture = Facture.objects.create(
            invoice_number=generate_number(
                Facture,
                "invoice_number",
                "FAC"
            ),
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
        facture.save(
            update_fields=[
                "qr_code",
                "qr_code_data",
                "updated_at"
            ]
        )

        return facture

    # ================================================================
    # MÉTHODE SAVE CORRIGÉE
    # ================================================================

    def save(self, *args, **kwargs):
        """
        Sauvegarde avec gestion du statut et des opérations associées
        """
        is_new = self.pk is None
        old_status = None

        # Récupérer l'ancien statut si mise à jour
        if self.pk:
            old_status = (
                Vente.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

        # Définir le nom du client si absent
        if not self.client_name:
            self.client_name = (
                self.client.name
                if self.client
                else "Client anonyme"
            )

        # Générer le numéro de facture si nouveau
        if not self.invoice_number:
            self.invoice_number = generate_number(
                Vente,
                "invoice_number",
                "INV"
            )

        # Déterminer si c'est une confirmation
        is_confirming = (
            not is_new
            and old_status == "draft"
            and self.status == "confirmed"
        )

        # Déterminer si c'est une annulation
        is_cancelling = (
            not is_new
            and old_status in ["confirmed", "paid", "delivered"]
            and self.status == "cancelled"
        )

        # ============================================================
        # SAUVEGARDE INITIALE
        # ============================================================

        # Appeler save() parent pour enregistrer les modifications
        super().save(*args, **kwargs)

        # ============================================================
        # GÉNÉRATION DU QR CODE (après création)
        # ============================================================

        if not self.qr_code or not self.qr_code_data:
            self.generate_qr_code()
            super().save(update_fields=[
                "qr_code", "qr_code_data", "updated_at"])

        # ============================================================
        # CONFIRMATION : DÉDUCTION DU STOCK
        # ============================================================

        if is_confirming:
            try:
                # Appel à deduct_stock() dans une transaction
                self.deduct_stock()

                # Générer la facture
                if not self.invoices.exists():
                    self.generate_invoice()

            except Exception as error:
                # En cas d'erreur, on revient en brouillon
                self.status = "draft"
                super().save(update_fields=["status", "updated_at"])
                raise ValidationError(
                    f"Erreur lors de la confirmation : {error}")

        # ============================================================
        # ANNULATION : RESTAURATION DU STOCK
        # ============================================================

        if is_cancelling:
            try:
                self.restore_stock()
            except Exception as error:
                # En cas d'erreur, on ne laisse pas la vente annulée
                self.status = old_status
                super().save(update_fields=["status", "updated_at"])
                raise ValidationError(f"Erreur lors de l'annulation : {error}")


# ============================================================
# LIGNE VENTE
# ============================================================

class LigneVente(models.Model):
    """
    Ligne de vente avec gestion du type de prix (détail/gros)
    """

    # ============================================================
    # RELATIONS
    # ============================================================

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

    # ============================================================
    # QUANTITÉS ET PRIX
    # ============================================================

    quantity = models.PositiveIntegerField(
        verbose_name="Quantité"
    )

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Prix unitaire"
    )

    # ============================================================
    # REMISES ET TAXES
    # ============================================================

    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Remise"
    )

    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Taux de TVA (%)"
    )

    # ============================================================
    # TOTAUX
    # ============================================================

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total ligne"
    )

    # ============================================================
    # 🆕 TYPE DE PRIX (DÉTAIL / GROS)
    # ============================================================

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

    # ============================================================
    # NOTES
    # ============================================================

    notes = models.TextField(
        blank=True,
        verbose_name="Notes"
    )

    # ============================================================
    # MÉTADONNÉES
    # ============================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de création"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Date de modification"
    )

    class Meta:
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
        ordering = ['id']

    def __str__(self):
        return (
            f"{self.sale.invoice_number} - "
            f"{self.product.name} "
            f"({self.quantity} x {self.unit_price})"
        )

    # ============================================================
    # PROPRIÉTÉS
    # ============================================================

    @property
    def subtotal(self):
        """Sous-total avant remise"""
        return Decimal(self.quantity) * self.unit_price

    @property
    def discount_amount(self):
        """Montant de la remise"""
        if self.discount > 0:
            return self.discount
        return Decimal("0.00")

    @property
    def tax_amount(self):
        """Montant de la TVA"""
        if self.tax_rate > 0:
            return (self.subtotal - self.discount) * (self.tax_rate / Decimal("100"))
        return Decimal("0.00")

    @property
    def total_without_tax(self):
        """Total hors taxe"""
        return self.subtotal - self.discount

    @property
    def price_type_display(self):
        """Affichage du type de prix"""
        return dict(self.PRICE_TYPE_CHOICES).get(self.price_type, self.price_type)

    # ============================================================
    # MÉTHODES
    # ============================================================

    def calculate_total(self):
        """
        Calcule le total de la ligne
        """
        # Calcul du sous-total
        subtotal = Decimal(self.quantity) * self.unit_price

        # Application de la remise
        self.total = max(
            Decimal("0.00"),
            subtotal - self.discount
        )

        return self.total

    def save(self, *args, **kwargs):
        """
        Sauvegarde avec calcul automatique du total
        """
        # Validation de la quantité
        if self.quantity <= 0:
            raise ValidationError(
                "La quantité doit être supérieure à zéro."
            )

        # Validation du prix
        if self.unit_price <= 0:
            raise ValidationError(
                "Le prix unitaire doit être supérieur à zéro."
            )

        # Validation du type de prix
        if self.price_type not in ['detail', 'gros']:
            raise ValidationError(
                "Le type de prix doit être 'detail' ou 'gros'."
            )

        # Calcul du total
        self.calculate_total()

        # Sauvegarde
        super().save(*args, **kwargs)

        # Mise à jour des totaux de la vente parente
        if self.sale:
            self.sale.calculate_totals()

    def get_product_price(self):
        """
        Retourne le prix du produit selon le type sélectionné
        """
        if self.price_type == 'gros':
            return self.product.wholesale_price or self.product.selling_price
        return self.product.selling_price

    def get_price_type_display(self):
        """
        Retourne le libellé du type de prix
        """
        return dict(self.PRICE_TYPE_CHOICES).get(self.price_type, 'Prix de détail')

    def to_dict(self):
        """
        Convertit la ligne en dictionnaire pour l'export
        """
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

    invoice_number = models.CharField(
        max_length=50,
        unique=True
    )

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

    invoice_date = models.DateField(
        auto_now_add=True
    )

    due_date = models.DateField()

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00")
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
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

    notes = models.TextField(
        blank=True
    )

    qr_code = models.ImageField(
        upload_to="qrcodes/invoices/",
        null=True,
        blank=True
    )

    qr_code_data = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-invoice_date"]

    def __str__(self):

        return (
            f"{self.invoice_number} - "
            f"{self.client.name}"
        )

    @property
    def remaining_amount(self):

        return max(
            Decimal("0.00"),
            self.total - self.amount_paid
        )

    def update_payment_status(self):

        total_paid = (
            self.paiements.aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )

        self.amount_paid = total_paid

        if self.amount_paid >= self.total:

            self.status = "paid"

        elif self.amount_paid > 0:

            self.status = "partial"

        else:

            self.status = "sent"

        super().save(
            update_fields=[
                "amount_paid",
                "status",
                "updated_at"
            ]
        )

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
                Facture,
                "invoice_number",
                "FAC"
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

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES
    )

    reference = models.CharField(
        max_length=100,
        blank=True
    )

    payment_date = models.DateTimeField(
        auto_now_add=True
    )

    received_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    notes = models.TextField(
        blank=True
    )

    qr_code = models.ImageField(
        upload_to="qrcodes/payments/",
        null=True,
        blank=True
    )

    qr_code_data = models.TextField(
        blank=True
    )

    updated_at = models.DateTimeField(auto_now=True)

    # ============================================================
    # NOUVEAUX CHAMPS : DESTINATION DE L'ENCAISSEMENT
    # ============================================================
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

    def __str__(self):
        return (
            f"{self.facture.invoice_number} - "
            f"{self.amount} FCFA"
        )

    def clean(self):
        # Validation du montant
        if self.amount <= 0:
            raise ValidationError(
                "Le montant du paiement doit être supérieur à zéro."
            )

        if self.facture_id:
            previous_paid = (
                self.facture.paiements
                .exclude(pk=self.pk)
                .aggregate(
                    total=Sum("amount")
                )["total"]
                or Decimal("0.00")
            )

            if (
                previous_paid + self.amount
                > self.facture.total
            ):
                raise ValidationError(
                    "Le paiement dépasse le montant restant."
                )

        # ============================================================
        # NOUVELLE VALIDATION : DESTINATION UNIQUE
        # ============================================================
        if self.caisse_destination and self.compte_destination:
            raise ValidationError(
                "Vous ne pouvez choisir qu'une seule destination : caisse OU compte bancaire."
            )

        # Vérifier que la destination appartient au même entrepôt que la vente
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
            super().save(
                update_fields=[
                    "qr_code",
                    "qr_code_data",
                    "updated_at"
                ]
            )

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

            super(
                Vente,
                sale
            ).save(
                update_fields=[
                    "amount_paid",
                    "amount_due",
                    "payment_status",
                    "updated_at"
                ]
            )


# ============================================================
# AVOIR
# ============================================================

# apps/ventes_clients/models.py


# apps/ventes_clients/models.py


# ============================================================
# AVOIR (NOTE DE CRÉDIT)
# ============================================================

# apps/ventes_clients/models.py


logger = logging.getLogger(__name__)


# ============================================================
# AVOIR (NOTE DE CRÉDIT)
# ============================================================

# apps/ventes_clients/models.py


logger = logging.getLogger(__name__)


# ============================================================
# AVOIR
# ============================================================
# ============================================================
# AVOIR
# ============================================================
class Avoir(models.Model):
    """
    Avoir client (note de crédit).
    
    Représente une créance de l'entreprise envers le client.
    
    Types :
    - refund   : Remboursement
    - return   : Retour de marchandise (restaure le stock)
    - discount : Remise / Geste commercial
    - error    : Erreur de facturation
    
    Un avoir contient PLUSIEURS lignes (LigneAvoir) permettant
    de gérer les retours PARTIELS (ex: 5 produits sur 10).
    """

    # ============================================================
    # TYPES D'AVOIR
    # ============================================================
    TYPE_CHOICES = (
        ("refund", "Remboursement"),
        ("return", "Retour de marchandise"),
        ("discount", "Remise / Geste commercial"),
        ("error", "Erreur de facturation"),
    )

    # ============================================================
    # IDENTIFICATION
    # ============================================================
    avoir_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Numéro d'avoir",
    )

    # ============================================================
    # RELATIONS
    # ============================================================
    sale = models.ForeignKey(
        "Vente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avoirs",
        verbose_name="Vente associée",
    )

    client = models.ForeignKey(
        "Client",
        on_delete=models.PROTECT,
        related_name="avoirs",
        verbose_name="Client",
    )

    # ============================================================
    # TYPE
    # ============================================================
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="refund",
        verbose_name="Type d'avoir",
    )

    # ============================================================
    # MONTANT
    # ============================================================
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Montant total",
    )

    # ============================================================
    # DÉTAILS
    # ============================================================
    reason = models.TextField(
        verbose_name="Raison",
        help_text="Motif de l'avoir (retour, remboursement, etc.)",
    )

    date = models.DateField(
        auto_now_add=True,
        verbose_name="Date",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Notes internes",
    )

    # ============================================================
    # RESTAURATION DU STOCK
    # ============================================================
    restore_stock = models.BooleanField(
        default=False,
        verbose_name="Stock restauré",
        help_text="Indique si le stock a été restauré suite à cet avoir",
    )

    stock_restored_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de restauration du stock",
    )

    # ============================================================
    # MÉTADONNÉES
    # ============================================================
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avoirs_created",
        verbose_name="Créé par",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Créé le",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Modifié le",
    )

    # ============================================================
    # MÉTA
    # ============================================================
    class Meta:
        verbose_name = "Avoir"
        verbose_name_plural = "Avoirs"
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["avoir_number"]),
            models.Index(fields=["client", "-date"]),
            models.Index(fields=["type"]),
            models.Index(fields=["sale"]),
        ]

    # ============================================================
    # REPRÉSENTATION
    # ============================================================
    def __str__(self):
        return (
            f"{self.avoir_number} - "
            f"{self.client.name if self.client else 'N/A'} - "
            f"{self.amount:,.0f} FCFA"
        )

    # ============================================================
    # SAUVEGARDE
    # ============================================================
    def save(self, *args, **kwargs):
        """Génère automatiquement le numéro d'avoir si absent."""
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

    # ============================================================
    # PROPRIÉTÉS
    # ============================================================
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
        """
        Indique si cet avoir peut déclencher une restauration de stock.
        
        Conditions :
        - Une vente doit être associée
        - Le type doit être 'refund' ou 'return'
        - Le stock ne doit pas déjà avoir été restauré
        - Il doit y avoir au moins une ligne
        """
        return (
            self.sale is not None
            and self.type in ["refund", "return"]
            and not self.restore_stock
            and self.lignes.exists()
        )

    @property
    def nombre_produits(self):
        """Nombre de produits retournés"""
        return self.lignes.count()

    @property
    def quantite_totale(self):
        """Quantité totale retournée"""
        return self.lignes.aggregate(
            total=models.Sum("quantity")
        )["total"] or 0

    # ============================================================
    # ACTIONS
    # ============================================================
    def recalculate_amount(self):
        """Recalcule le montant total à partir des lignes."""
        total = self.lignes.aggregate(
            total=models.Sum("total")
        )["total"] or 0
        self.amount = total
        self.save(update_fields=["amount", "updated_at"])
        return total

    def restore_partial_stock(self, user=None):
        """
        Restaure le stock UNIQUEMENT pour les produits retournés
        (lignes de l'avoir).
        
        Pour chaque ligne :
        - Restaure la quantité dans le lot d'origine (si traçable)
        - Met à jour le stock (recalcul depuis les lots ou ajout manuel)
        - Crée un StockMovement avec le type 'return_in'
        
        Retourne un dict :
        {
            'success': bool,
            'message': str,
            'details': list
        }
        """
        from produits_stocks.models import Stock, StockMovement

        # ------------------------------------------------------------
        # VÉRIFICATIONS PRÉALABLES
        # ------------------------------------------------------------
        if not self.sale:
            return {
                "success": False,
                "message": "Aucune vente associée à cet avoir",
                "details": [],
            }

        if not self.sale.warehouse:
            return {
                "success": False,
                "message": "Aucun entrepôt défini pour la vente",
                "details": [],
            }

        if self.restore_stock:
            return {
                "success": False,
                "message": "Le stock a déjà été restauré pour cet avoir",
                "details": [],
            }

        if not self.lignes.exists():
            return {
                "success": False,
                "message": "Aucune ligne dans cet avoir à restaurer",
                "details": [],
            }

        warehouse = self.sale.warehouse
        details = []

        # ------------------------------------------------------------
        # RESTAURATION LIGNE PAR LIGNE
        # ------------------------------------------------------------
        for ligne in self.lignes.select_related("product", "ligne_vente").all():
            try:
                # ============================================================
                # 1. RÉCUPÉRER LE LOT D'ORIGINE (si traçable)
                # ============================================================
                lot_origine = None
                if ligne.ligne_vente:
                    lot_origine = getattr(ligne.ligne_vente, "lot", None)

                quantite_retour = int(ligne.quantity)

                # ============================================================
                # 2. RESTAURER LA QUANTITÉ DANS LE LOT (si présent)
                # ============================================================
                ancienne_qte_lot = None
                nouvelle_qte_lot = None

                if lot_origine:
                    ancienne_qte_lot = lot_origine.current_quantity
                    lot_origine.current_quantity += quantite_retour
                    lot_origine.save(update_fields=["current_quantity"])
                    nouvelle_qte_lot = lot_origine.current_quantity

                    logger.info(
                        f"📦 Lot {lot_origine.lot_number} restauré : "
                        f"{ancienne_qte_lot} → {nouvelle_qte_lot} "
                        f"(+{quantite_retour})"
                    )

                # ============================================================
                # 3. RÉCUPÉRER OU CRÉER LE STOCK
                # ============================================================
                stock, _ = Stock.objects.get_or_create(
                    product=ligne.product,
                    warehouse=warehouse,
                    defaults={"quantity": 0, "reserved_quantity": 0},
                )

                ancienne_qte_stock = stock.quantity

                # ============================================================
                # 4. METTRE À JOUR LE STOCK
                # ============================================================
                if lot_origine:
                    # Cas avec lot : recalcul depuis les lots
                    stock.update_quantity()
                else:
                    # Cas sans lot : ajout manuel
                    stock.quantity += quantite_retour
                    stock.save(update_fields=["quantity", "last_update"])

                nouvelle_qte_stock = stock.quantity

                logger.info(
                    f"📊 Stock {ligne.product.name} : "
                    f"{ancienne_qte_stock} → {nouvelle_qte_stock} "
                    f"(+{quantite_retour})"
                )

                # ============================================================
                # 5. CRÉER LE STOCKMOVEMENT (avec les BONS champs)
                # ============================================================
                movement = StockMovement.objects.create(
                    product=ligne.product,
                    lot=lot_origine,                     # Lier au lot si dispo
                    from_warehouse=None,                 # Rien ne sort
                    to_warehouse=warehouse,              # Entrée dans cet entrepôt
                    movement_type="return_in",           # CHOIX VALIDE
                    quantity=quantite_retour,            # Integer
                    previous_quantity=ancienne_qte_lot or ancienne_qte_stock,
                    new_quantity=nouvelle_qte_lot or nouvelle_qte_stock,
                    reference_type="avoir",              # Type de référence
                    reference_id=self.id,                # ID de l'avoir
                    reference_number=self.avoir_number,  # Numéro de l'avoir
                    reason=f"Retour avoir {self.avoir_number}",
                    notes=(
                        f"Retour partiel via avoir {self.avoir_number} - "
                        f"{self.reason[:200]}"
                    ),
                    created_by=user,
                )

                logger.info(
                    f"✅ StockMovement #{movement.id} créé : "
                    f"{movement.get_movement_type_display()} - "
                    f"{ligne.product.name} +{quantite_retour}"
                )

                # ============================================================
                # 6. AJOUTER AU DÉTAIL
                # ============================================================
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

        # ------------------------------------------------------------
        # MARQUER L'AVOIR COMME RESTAURÉ
        # ------------------------------------------------------------
        self.restore_stock = True
        self.stock_restored_at = timezone.now()
        self.save(update_fields=["restore_stock", "stock_restored_at", "updated_at"])

        # ------------------------------------------------------------
        # RÉSULTAT FINAL
        # ------------------------------------------------------------
        nb_ok = len([d for d in details if "error" not in d])
        nb_err = len([d for d in details if "error" in d])

        if nb_err > 0:
            return {
                "success": True,
                "message": (
                    f"Stock restauré pour {nb_ok} produit(s), "
                    f"{nb_err} erreur(s)"
                ),
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
        null=True,
        blank=True,
        related_name="lignes_avoir",
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Quantité retournée",
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Prix unitaire",
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Remise",
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Total ligne",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ligne d'avoir"
        verbose_name_plural = "Lignes d'avoir"
        ordering = ["id"]

    def __str__(self):
        return f"{self.product.name} x {self.quantity:g} - {self.total:,.0f} FCFA"

    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.unit_price) - (self.discount or 0)
        super().save(*args, **kwargs)


# ============================================================
# TAXE
# ============================================================


class Taxe(models.Model):

    name = models.CharField(
        max_length=100
    )

    rate = models.DecimalField(
        max_digits=5,
        decimal_places=2
    )

    is_default = models.BooleanField(
        default=False
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Taxe"
        verbose_name_plural = "Taxes"

    def __str__(self):

        return (
            f"{self.name} "
            f"({self.rate}%)"
        )


# ============================================================
# REMISE
# ============================================================

class Remise(models.Model):

    TYPE_CHOICES = (
        ("percentage", "Pourcentage"),
        ("amount", "Montant fixe"),
    )

    name = models.CharField(
        max_length=100
    )

    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES
    )

    value = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    min_purchase = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    start_date = models.DateField(
        null=True,
        blank=True
    )

    end_date = models.DateField(
        null=True,
        blank=True
    )

    is_active = models.BooleanField(
        default=True
    )

    clients = models.ManyToManyField(
        Client,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        verbose_name = "Remise"
        verbose_name_plural = "Remises"

    def __str__(self):

        suffix = (
            "%"
            if self.type == "percentage"
            else " FCFA"
        )

        return (
            f"{self.name} - "
            f"{self.value}{suffix}"
        )

    def is_valid(self):

        today = date.today()

        if not self.is_active:
            return False

        if (
            self.start_date
            and today < self.start_date
        ):
            return False

        if (
            self.end_date
            and today > self.end_date
        ):
            return False

        return True


# apps/ventes_clients/models.py
# apps/ventes_clients/models.py - ClientWallet et WalletTransaction mis à jour

class ClientWallet(models.Model):
    """
    Porte-monnaie électronique du client
    """
    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name="Client"
    )

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Solde disponible"
    )

    total_deposits = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total des dépôts"
    )

    total_used = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total utilisé"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Wallet actif"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Porte-monnaie client"
        verbose_name_plural = "Porte-monnaie clients"

    def __str__(self):
        return f"{self.client.name} - {self.balance:,.0f} FCFA"

    @transaction.atomic
    def credit(self, amount, source, reference, notes='', created_by=None):
        """
        Ajoute de l'argent au wallet du client

        Args:
            amount (Decimal): Montant à créditer
            source (str): Source de la transaction (deposit, payment, etc.)
            reference (str): Référence de la transaction
            notes (str): Notes optionnelles
            created_by (User): Utilisateur qui crée la transaction
        """
        if amount <= 0:
            raise ValidationError("Le montant doit être supérieur à zéro")

        self.balance += amount
        self.total_deposits += amount
        self.save()

        # Créer l'historique de transaction
        WalletTransaction.objects.create(
            wallet=self,
            type='credit',
            amount=amount,
            source=source,
            reference=reference,
            notes=notes,
            balance_after=self.balance,
            created_by=created_by  # ✅ Ajout du paramètre created_by
        )

        return self.balance

    @transaction.atomic
    def debit(self, amount, source, reference, notes='', created_by=None):
        """
        Débite le wallet du client (utilisé pour payer)

        Args:
            amount (Decimal): Montant à débiter
            source (str): Source de la transaction (payment, etc.)
            reference (str): Référence de la transaction
            notes (str): Notes optionnelles
            created_by (User): Utilisateur qui crée la transaction
        """
        if amount <= 0:
            raise ValidationError("Le montant doit être supérieur à zéro")

        if amount > self.balance:
            raise ValidationError(
                f"Solde insuffisant. Disponible : {self.balance:,.0f} FCFA"
            )

        self.balance -= amount
        self.total_used += amount
        self.save()

        # Créer l'historique de transaction
        WalletTransaction.objects.create(
            wallet=self,
            type='debit',
            amount=amount,
            source=source,
            reference=reference,
            notes=notes,
            balance_after=self.balance,
            created_by=created_by  # ✅ Ajout du paramètre created_by
        )

        return self.balance


class WalletTransaction(models.Model):
    """
    Historique des transactions du wallet
    """
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

    type = models.CharField(
        max_length=10,
        choices=TRANSACTION_TYPES
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES
    )

    reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Référence"
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Notes"
    )

    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Solde après transaction"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transactions'  # ✅ Ajout du related_name
    )

    class Meta:
        verbose_name = "Transaction wallet"
        verbose_name_plural = "Transactions wallet"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_type_display()} - {self.amount:,.0f} FCFA"
