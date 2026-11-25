# apps/produits_stocks/models.py
# ============================================================
# MODELS - Support des variantes de produits
# ✅ ProductOption / ProductOptionValue / ProductVariant
# ✅ Stock & Lot référencent optionnellement une variante
# ============================================================

from django.db import models
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from users.models import CustomUser


# ============================================================
# CATEGORY
# ============================================================
class Category(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nom")
    code = models.CharField(max_length=50, unique=True, verbose_name="Code")
    description = models.TextField(blank=True, verbose_name="Description")
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children', verbose_name="Catégorie parente"
    )
    image = models.ImageField(upload_to='categories/',
                              null=True, blank=True, verbose_name="Image")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Date modification")
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ['name']
        indexes = [
            models.Index(fields=['code'], name='category_code_idx'),
            models.Index(fields=['name'], name='category_name_idx'),
            models.Index(fields=['is_active'], name='category_active_idx'),
            models.Index(fields=['parent'], name='category_parent_idx'),
            models.Index(fields=['parent', 'is_active'],
                         name='category_parent_active_idx'),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} > {self.name}"
        return self.name


# ============================================================
# UNIT MEASURE
# ============================================================
class UnitMeasure(models.Model):
    TYPE_CHOICES = (
        ('unit', 'Unité'),
        ('weight', 'Poids'),
        ('volume', 'Volume'),
        ('length', 'Longueur'),
    )
    name = models.CharField(max_length=50, verbose_name="Nom")
    symbol = models.CharField(max_length=10, verbose_name="Symbole")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='unit', verbose_name="Type")
    conversion_factor = models.DecimalField(
        max_digits=10, decimal_places=4, default=1.0000,
        verbose_name="Facteur de conversion")
    is_base_unit = models.BooleanField(default=False, verbose_name="Unité de base")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Unité de mesure"
        verbose_name_plural = "Unités de mesure"
        ordering = ['name']
        indexes = [
            models.Index(fields=['name'], name='unit_name_idx'),
            models.Index(fields=['is_active'], name='unit_active_idx'),
            models.Index(fields=['type'], name='unit_type_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.symbol})"


# ============================================================
# PRODUCT
# ============================================================
class Product(models.Model):
    STATUS_CHOICES = (
        ('active', 'Actif'),
        ('inactive', 'Inactif'),
        ('out_of_stock', 'Rupture de stock'),
        ('discontinued', 'Abandonné'),
    )
    TYPE_CHOICES = (
        ('standard', 'Standard'),
        ('consignable', 'Consignable'),
        ('expirable', 'À durée limitée'),
        ('service', 'Service'),
    )

    code = models.CharField(max_length=50, unique=True, verbose_name="Code produit")
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True,
                               verbose_name="Code-barres")
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")

    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products', verbose_name="Catégorie")
    unit = models.ForeignKey(
        UnitMeasure, on_delete=models.SET_NULL, null=True, verbose_name="Unité de mesure")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='standard', verbose_name="Type")

    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix d'achat")
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix de vente")
    wholesale_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix de gros")
    promo_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix promotionnel")

    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Taux de TVA (%)")

    has_expiry = models.BooleanField(default=False, verbose_name="A une date d'expiration")
    shelf_life_days = models.IntegerField(
        null=True, blank=True, help_text="Durée de conservation en jours",
        verbose_name="Durée de conservation")
    alert_days = models.IntegerField(
        default=30,
        help_text="Jours avant expiration pour déclencher une alerte",
        verbose_name="Jours d'alerte")

    min_stock = models.IntegerField(default=0, verbose_name="Stock minimum")
    max_stock = models.IntegerField(default=0, verbose_name="Stock maximum")
    reorder_point = models.IntegerField(default=0, verbose_name="Point de commande")
    reorder_quantity = models.IntegerField(default=0, verbose_name="Quantité de réapprovisionnement")

    image = models.ImageField(
        upload_to='products/', null=True, blank=True, verbose_name="Image principale")
    gallery = models.JSONField(default=list, blank=True, verbose_name="Galerie d'images")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="Statut")
    is_featured = models.BooleanField(default=False, verbose_name="Produit vedette")

    # ✅ NOUVEAU : flag de gestion des variantes
    has_variants = models.BooleanField(
        default=False, verbose_name="A des variantes")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Date modification")
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Créé par")

    class Meta:
        verbose_name = "Produit"
        verbose_name_plural = "Produits"
        ordering = ['name']
        indexes = [
            models.Index(fields=['code'], name='product_code_idx'),
            models.Index(fields=['barcode'], name='product_barcode_idx'),
            models.Index(fields=['name'], name='product_name_idx'),
            models.Index(fields=['status'], name='product_status_idx'),
            models.Index(fields=['is_featured'], name='product_featured_idx'),
            models.Index(fields=['has_expiry'], name='product_has_expiry_idx'),
            models.Index(fields=['has_variants'], name='product_has_var_idx'),  # ✅ NOUVEAU
            models.Index(fields=['category', 'status'], name='product_cat_status_idx'),
            models.Index(fields=['status', 'name'], name='product_status_name_idx'),
            models.Index(fields=['is_featured', 'status'], name='product_feat_status_idx'),
            models.Index(fields=['-created_at'], name='product_created_idx'),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def current_stock(self):
        """Somme du stock total (inclut les variantes)."""
        return self.stocks.aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def current_stock_value(self):
        return self.current_stock * self.purchase_price

    @property
    def low_stock(self):
        return self.current_stock <= self.min_stock

    @property
    def out_of_stock(self):
        return self.current_stock == 0

    @property
    def total_lots(self):
        return self.lots.count()

    @property
    def expired_lots_count(self):
        return self.lots.filter(status='expired').count()

    @property
    def expiring_lots_count(self):
        return self.lots.filter(status='expiring').count()

    @property
    def available_lots(self):
        return self.lots.filter(status__in=['good', 'expiring'], current_quantity__gt=0)

    def update_status(self):
        if self.current_stock <= 0:
            self.status = 'out_of_stock'
        elif self.status == 'out_of_stock' and self.current_stock > 0:
            self.status = 'active'
        self.save(update_fields=['status'])


# ============================================================
# ✅ NOUVEAU : PRODUCT OPTIONS & VARIANTS
# ============================================================
class ProductOption(models.Model):
    """
    Option de produit (ex: Taille, Couleur, Modèle).
    Chaque option appartient à un produit parent.
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='options', verbose_name="Produit")
    name = models.CharField(max_length=50, verbose_name="Nom de l'option")
    position = models.IntegerField(default=0, verbose_name="Ordre")

    class Meta:
        verbose_name = "Option produit"
        verbose_name_plural = "Options produit"
        unique_together = ['product', 'name']
        ordering = ['position', 'id']

    def __str__(self):
        return f"{self.product.name} - {self.name}"


class ProductOptionValue(models.Model):
    """
    Valeur d'une option (ex: S, M, L, Rouge, Bleu).
    """
    option = models.ForeignKey(
        ProductOption, on_delete=models.CASCADE,
        related_name='values', verbose_name="Option")
    value = models.CharField(max_length=50, verbose_name="Valeur")
    position = models.IntegerField(default=0, verbose_name="Ordre")

    class Meta:
        verbose_name = "Valeur d'option"
        verbose_name_plural = "Valeurs d'option"
        unique_together = ['option', 'value']
        ordering = ['position', 'id']

    def __str__(self):
        return f"{self.option.name}: {self.value}"


class ProductVariant(models.Model):
    """
    Variante d'un produit = combinaison de valeurs d'options.
    Chaque variante possède son propre stock (via Lot/Stock.variant).
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='variants', verbose_name="Produit parent")
    sku = models.CharField(
        max_length=100, unique=True, verbose_name="SKU / Code variante")
    barcode = models.CharField(
        max_length=100, unique=True, null=True, blank=True,
        verbose_name="Code-barres")

    option_values = models.ManyToManyField(
        ProductOptionValue, related_name='variants',
        verbose_name="Valeurs d'options")

    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix d'achat (override)")
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix de vente (override)")
    wholesale_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix de gros (override)")
    promo_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Prix promo (override)")

    image = models.ImageField(
        upload_to='products/variants/', null=True, blank=True,
        verbose_name="Image")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    is_default = models.BooleanField(default=False, verbose_name="Variante par défaut")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Variante de produit"
        verbose_name_plural = "Variantes de produit"
        ordering = ['product', 'sku']
        indexes = [
            models.Index(fields=['sku'], name='variant_sku_idx'),
            models.Index(fields=['product', 'is_active'],
                         name='variant_prod_active_idx'),
            models.Index(fields=['barcode'], name='variant_barcode_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} [{self.sku}]"

    # Helpers ---------------------------------------------------
    @property
    def effective_purchase_price(self):
        return self.purchase_price if self.purchase_price is not None \
            else self.product.purchase_price

    @property
    def effective_selling_price(self):
        return self.selling_price if self.selling_price is not None \
            else self.product.selling_price

    @property
    def effective_wholesale_price(self):
        return self.wholesale_price if self.wholesale_price is not None \
            else self.product.wholesale_price

    @property
    def effective_promo_price(self):
        return self.promo_price if self.promo_price is not None \
            else self.product.promo_price

    @property
    def current_stock(self):
        return self.stocks.aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def label(self):
        return " / ".join(
            f"{v.option.name}={v.value}"
            for v in self.option_values.all()
        )


# ============================================================
# WAREHOUSE
# ============================================================
class Warehouse(models.Model):
    TYPE_CHOICES = (
        ('main', 'Principal'),
        ('secondary', 'Secondaire'),
        ('store', 'Magasin'),
        ('warehouse', 'Entrepôt'),
    )
    name = models.CharField(max_length=100, verbose_name="Nom")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='warehouse', verbose_name="Type")

    address = models.TextField(verbose_name="Adresse")
    city = models.CharField(max_length=100, blank=True, verbose_name="Ville")
    country = models.CharField(max_length=100, default='Sénégal', verbose_name="Pays")

    phone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, verbose_name="Email")
    manager = models.CharField(max_length=100, blank=True, verbose_name="Responsable")

    capacity = models.IntegerField(null=True, blank=True, verbose_name="Capacité maximale")
    current_occupancy = models.IntegerField(default=0, verbose_name="Occupation actuelle")

    is_active = models.BooleanField(default=True, verbose_name="Actif")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Date modification")

    class Meta:
        verbose_name = "Entrepôt"
        verbose_name_plural = "Entrepôts"
        ordering = ['name']
        indexes = [
            models.Index(fields=['code'], name='warehouse_code_idx'),
            models.Index(fields=['is_active'], name='warehouse_active_idx'),
            models.Index(fields=['type'], name='warehouse_type_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def occupancy_rate(self):
        if self.capacity and self.capacity > 0:
            return (self.current_occupancy / self.capacity) * 100
        return 0


# ============================================================
# LOT
# ============================================================
class Lot(models.Model):
    STATUS_CHOICES = (
        ('good', 'Bon'),
        ('expiring', 'Expire bientôt'),
        ('expired', 'Expiré'),
        ('blocked', 'Bloqué'),
        ('quarantine', 'En quarantaine'),
    )

    product = models.ForeignKey(
        'Product', on_delete=models.CASCADE,
        related_name='lots', verbose_name="Produit")
    warehouse = models.ForeignKey(
        'Warehouse', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lots', verbose_name="Entrepôt")

    # ✅ NOUVEAU : référence optionnelle à une variante
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.CASCADE,
        null=True, blank=True, related_name='lots',
        verbose_name="Variante")

    lot_number = models.CharField(max_length=100, unique=True, verbose_name="Numéro de lot")
    batch_number = models.CharField(max_length=100, blank=True, verbose_name="Numéro de batch")
    barcode = models.CharField(max_length=100, blank=True, null=True, verbose_name="Code-barres")

    initial_quantity = models.IntegerField(verbose_name="Quantité initiale")
    current_quantity = models.IntegerField(verbose_name="Quantité actuelle")
    reserved_quantity = models.IntegerField(default=0, verbose_name="Quantité réservée")
    min_quantity_alert = models.IntegerField(default=0, verbose_name="Alerte quantité minimale")

    unit = models.ForeignKey(
        'UnitMeasure', on_delete=models.SET_NULL, null=True, verbose_name="Unité")

    manufacturing_date = models.DateField(null=True, blank=True, verbose_name="Date de fabrication")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="Date d'expiration")
    reception_date = models.DateField(auto_now_add=True, verbose_name="Date de réception")
    last_used_date = models.DateField(null=True, blank=True, verbose_name="Dernière utilisation")
    blocked_date = models.DateField(null=True, blank=True, verbose_name="Date de blocage")

    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix d'achat unitaire")
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix de vente unitaire")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='good', verbose_name="Statut")
    is_blocked = models.BooleanField(default=False, verbose_name="Bloqué")
    block_reason = models.TextField(blank=True, verbose_name="Raison du blocage")

    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date création")
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Créé par")

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ['expiry_date', 'created_at']
        indexes = [
            models.Index(fields=['product', 'expiry_date'], name='lot_prod_expiry_idx'),
            models.Index(fields=['status', 'expiry_date'], name='lot_status_expiry_idx'),
            models.Index(fields=['lot_number'], name='lot_number_idx'),
            models.Index(fields=['product', 'warehouse'], name='lot_prod_wh_idx'),
            models.Index(fields=['product', 'warehouse', 'status'],
                         name='lot_prod_wh_status_idx'),
            models.Index(fields=['warehouse', 'expiry_date'], name='lot_wh_expiry_idx'),
            models.Index(fields=['expiry_date'], name='lot_expiry_idx'),
            models.Index(fields=['current_quantity'], name='lot_qty_idx'),
            models.Index(fields=['is_blocked'], name='lot_blocked_idx'),
            models.Index(fields=['-created_at'], name='lot_created_idx'),
            models.Index(fields=['variant'], name='lot_variant_idx'),  # ✅ NOUVEAU
        ]

    def __str__(self):
        expiry_info = f"Exp: {self.expiry_date}" if self.expiry_date else "Pas d'expiration"
        return f"{self.product.name} - Lot {self.lot_number} ({expiry_info})"

    def save(self, *args, **kwargs):
        today = date.today()
        alert_days = 30
        if self.product and self.product.alert_days:
            alert_days = self.product.alert_days

        if self.expiry_date:
            alert_date = today + timedelta(days=alert_days)
            if self.expiry_date < today:
                self.status = 'expired'
            elif self.expiry_date <= alert_date:
                self.status = 'expiring'
            else:
                self.status = 'good'
        else:
            self.status = 'good'

        super().save(*args, **kwargs)

    @property
    def days_until_expiry(self):
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None

    @property
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    @property
    def is_expiring_soon(self):
        if not self.expiry_date:
            return False
        alert_days = 30
        if self.product and self.product.alert_days:
            alert_days = self.product.alert_days
        return not self.is_expired and self.days_until_expiry <= alert_days

    @property
    def available_quantity(self):
        return self.current_quantity - self.reserved_quantity

    @property
    def stock_value(self):
        return self.current_quantity * self.purchase_price

    @property
    def usage_rate(self):
        if self.initial_quantity > 0:
            return ((self.initial_quantity - self.current_quantity) / self.initial_quantity) * 100
        return 0

    def reserve(self, quantity):
        if quantity <= self.available_quantity:
            self.reserved_quantity += quantity
            self.save()
            self._update_stock()
            return True
        return False

    def unreserve(self, quantity):
        self.reserved_quantity = max(0, self.reserved_quantity - quantity)
        self.save()
        self._update_stock()

    def consume(self, quantity):
        if quantity <= self.available_quantity:
            self.current_quantity -= quantity
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.last_used_date = date.today()
            self.save()
            self._update_stock()
            return True
        return False

    def block(self, reason=None):
        self.is_blocked = True
        self.status = 'blocked'
        self.block_reason = reason or ''
        self.blocked_date = date.today()
        self.save()
        self._update_stock()

    def unblock(self):
        self.is_blocked = False
        self.block_reason = ''
        self.blocked_date = None
        self.save()
        self._update_stock()

    def _update_stock(self):
        """Met à jour le stock correspondant (avec prise en compte de la variante)."""
        if self.warehouse:
            try:
                stock, _ = Stock.objects.get_or_create(
                    product=self.product,
                    warehouse=self.warehouse,
                    variant=self.variant,  # ✅ NOUVEAU
                )
                stock.update_quantity()
            except Exception:
                pass


# ============================================================
# STOCK
# ============================================================
class Stock(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='stocks', verbose_name="Produit")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE,
        related_name='stocks', verbose_name="Entrepôt")

    # ✅ NOUVEAU : référence optionnelle à une variante
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.CASCADE,
        null=True, blank=True, related_name='stocks',
        verbose_name="Variante")

    quantity = models.IntegerField(default=0, verbose_name="Quantité totale")
    reserved_quantity = models.IntegerField(default=0, verbose_name="Quantité réservée")
    min_stock_override = models.IntegerField(
        null=True, blank=True, verbose_name="Stock minimum (surcharge)")
    max_stock_override = models.IntegerField(
        null=True, blank=True, verbose_name="Stock maximum (surcharge)")
    last_update = models.DateTimeField(auto_now=True, verbose_name="Dernière mise à jour")

    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"
        # ✅ MODIFIÉ : contraintes conditionnelles pour gérer variant NULL
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'warehouse'],
                condition=Q(variant__isnull=True),
                name='uniq_stock_no_variant',
            ),
            models.UniqueConstraint(
                fields=['product', 'variant', 'warehouse'],
                condition=Q(variant__isnull=False),
                name='uniq_stock_with_variant',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'warehouse'], name='stock_prod_wh_idx'),
            models.Index(fields=['quantity'], name='stock_qty_idx'),
            models.Index(fields=['warehouse', 'quantity'], name='stock_wh_qty_idx'),
            models.Index(fields=['product'], name='stock_product_idx'),
            models.Index(fields=['warehouse'], name='stock_warehouse_idx'),
            models.Index(fields=['variant'], name='stock_variant_idx'),  # ✅ NOUVEAU
        ]

    def __str__(self):
        v = f" [{self.variant.sku}]" if self.variant_id else ""
        return f"{self.product.name}{v} - {self.warehouse.name}: {self.quantity}"

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    @property
    def min_stock(self):
        return self.min_stock_override or self.product.min_stock

    @property
    def max_stock(self):
        return self.max_stock_override or self.product.max_stock

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock

    @property
    def is_over_stock(self):
        return self.max_stock > 0 and self.quantity >= self.max_stock

    def _lots_queryset(self):
        """Helper : retourne les lots correspondant à ce stock (produit+entrepôt+variante)."""
        qs = self.product.lots.filter(
            warehouse=self.warehouse,
            is_blocked=False
        )
        if self.variant_id:
            qs = qs.filter(variant_id=self.variant_id)
        else:
            qs = qs.filter(variant__isnull=True)
        return qs

    def update_quantity(self):
        """Met à jour la quantité totale à partir des lots (respecte la variante)."""
        total = self._lots_queryset().exclude(status='expired').aggregate(
            total=Sum('current_quantity'))['total'] or 0

        self.quantity = total
        self.save(update_fields=['quantity', 'last_update'])
        self.product.update_status()
        return total

    def get_lots_fifo(self, quantity_needed=None):
        lots = self._lots_queryset().filter(
            current_quantity__gt=0
        ).exclude(status='expired').order_by('expiry_date')

        if quantity_needed:
            selected = []
            remaining = quantity_needed
            for lot in lots:
                if remaining <= 0:
                    break
                available = lot.available_quantity
                if available > 0:
                    take = min(available, remaining)
                    selected.append({
                        'lot': lot,
                        'quantity': take,
                        'expiry_date': lot.expiry_date
                    })
                    remaining -= take
            return selected, remaining == 0

        return lots

    def reserve_stock(self, quantity):
        if quantity > self.available_quantity:
            return False, "Stock insuffisant"
        lots, success = self.get_lots_fifo(quantity)
        if success:
            for item in lots:
                item['lot'].reserve(item['quantity'])
            self.reserved_quantity += quantity
            self.save(update_fields=['reserved_quantity'])
            return True, lots
        return False, "Impossible de réserver"

    def consume_stock(self, quantity):
        if quantity > self.available_quantity:
            return False, "Stock insuffisant"
        lots, success = self.get_lots_fifo(quantity)
        if success:
            for item in lots:
                item['lot'].consume(item['quantity'])
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.update_quantity()
            return True, lots
        return False, "Impossible de consommer"


# ============================================================
# STOCK MOVEMENT
# ============================================================
class StockMovement(models.Model):
    TYPE_CHOICES = (
        ('purchase_in', 'Entrée par achat'),
        ('sale_out', 'Sortie par vente'),
        ('transfer_in', 'Entrée par transfert'),
        ('transfer_out', 'Sortie par transfert'),
        ('adjustment_plus', 'Ajustement (+)'),
        ('adjustment_minus', 'Ajustement (-)'),
        ('return_in', 'Entrée par retour'),
        ('return_out', 'Sortie par retour'),
        ('expired_out', 'Sortie par expiration'),
        ('damaged_out', 'Sortie par perte/dommage'),
        ('inventory_adjustment', 'Ajustement inventaire'),
    )

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='movements', verbose_name="Produit")
    lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements', verbose_name="Lot")

    # ✅ NOUVEAU : mouvement attaché à une variante
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movements',
        verbose_name="Variante")

    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements_from', verbose_name="Entrepôt source")
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements_to', verbose_name="Entrepôt destination")

    movement_type = models.CharField(
        max_length=30, choices=TYPE_CHOICES, verbose_name="Type de mouvement")
    quantity = models.IntegerField(verbose_name="Quantité")
    previous_quantity = models.IntegerField(null=True, blank=True, verbose_name="Quantité avant")
    new_quantity = models.IntegerField(null=True, blank=True, verbose_name="Quantité après")

    reference_type = models.CharField(max_length=50, blank=True, verbose_name="Type référence")
    reference_id = models.IntegerField(null=True, blank=True, verbose_name="ID référence")
    reference_number = models.CharField(max_length=100, blank=True, verbose_name="N° référence")

    reason = models.TextField(blank=True, verbose_name="Raison")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Créé par")

    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at'], name='mov_prod_date_idx'),
            models.Index(fields=['lot'], name='mov_lot_idx'),
            models.Index(fields=['movement_type'], name='mov_type_idx'),
            models.Index(fields=['-created_at'], name='mov_date_idx'),
            models.Index(fields=['variant'], name='mov_variant_idx'),  # ✅ NOUVEAU
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} - {self.product.name} ({self.quantity})"


# ============================================================
# EXPIRY ALERT
# ============================================================
class ExpiryAlert(models.Model):
    SEVERITY_CHOICES = (
        ('danger', 'Critique'),
        ('warning', 'Avertissement'),
        ('info', 'Information'),
    )

    lot = models.ForeignKey(
        Lot, on_delete=models.CASCADE, related_name='alerts', verbose_name="Lot")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='alerts', verbose_name="Produit")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alerts', verbose_name="Entrepôt")

    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default='info', verbose_name="Sévérité")
    days_left = models.IntegerField(verbose_name="Jours restants")
    message = models.TextField(verbose_name="Message")

    is_read = models.BooleanField(default=False, verbose_name="Lue")
    is_processed = models.BooleanField(default=False, verbose_name="Traitée")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="Traitée le")
    processed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='processed_alerts', verbose_name="Traitée par")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date création")

    class Meta:
        verbose_name = "Alerte d'expiration"
        verbose_name_plural = "Alertes d'expiration"
        ordering = ['days_left', 'created_at']
        indexes = [
            models.Index(fields=['is_processed', 'days_left'], name='alert_proc_days_idx'),
            models.Index(fields=['is_read'], name='alert_read_idx'),
        ]

    def __str__(self):
        return f"Alerte {self.product.name} - {self.days_left}j"

    def mark_as_read(self):
        self.is_read = True
        self.save(update_fields=['is_read'])

    def mark_as_processed(self, user):
        self.is_processed = True
        self.processed_at = timezone.now()
        self.processed_by = user
        self.save(update_fields=['is_processed', 'processed_at', 'processed_by'])


# ============================================================
# INVENTORY
# ============================================================
class Inventory(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
    )

    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE,
        related_name='inventories', verbose_name="Entrepôt")
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")

    start_date = models.DateTimeField(null=True, blank=True, verbose_name="Date début")
    end_date = models.DateTimeField(null=True, blank=True, verbose_name="Date fin")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="Statut")

    total_expected_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    total_actual_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    total_difference = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_inventories', verbose_name="Créé par")
    verified_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_inventories', verbose_name="Vérifié par")

    class Meta:
        verbose_name = "Inventaire"
        verbose_name_plural = "Inventaires"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['warehouse', 'status'], name='inv_wh_status_idx'),
            models.Index(fields=['-created_at'], name='inv_created_idx'),
        ]

    def __str__(self):
        return f"{self.name} - {self.warehouse.name}"

    def start(self):
        self.status = 'in_progress'
        if not self.start_date:
            self.start_date = timezone.now()
        self.save(update_fields=['status', 'start_date'])

    def complete(self):
        self.status = 'completed'
        self.end_date = timezone.now()
        self.save(update_fields=['status', 'end_date'])


class InventoryLine(models.Model):
    inventory = models.ForeignKey(
        Inventory, on_delete=models.CASCADE,
        related_name='lines', verbose_name="Inventaire")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='inventory_lines', verbose_name="Produit")

    # ✅ NOUVEAU : variante optionnelle
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inventory_lines',
        verbose_name="Variante")

    lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_lines', verbose_name="Lot")

    expected_quantity = models.IntegerField(default=0, verbose_name="Quantité attendue")
    actual_quantity = models.IntegerField(null=True, blank=True, verbose_name="Quantité réelle")

    expected_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    actual_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    value_difference = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)

    is_verified = models.BooleanField(default=False, verbose_name="Vérifiée")
    verified_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Vérifiée par")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne d'inventaire"
        verbose_name_plural = "Lignes d'inventaire"
        indexes = [
            models.Index(fields=['inventory', 'is_verified'],
                         name='invline_inv_verif_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.inventory.name}"

    @property
    def difference(self):
        if self.actual_quantity is None:
            return None
        return self.actual_quantity - self.expected_quantity

    def save(self, *args, **kwargs):
        price = self.product.purchase_price or Decimal('0')
        self.expected_value = price * self.expected_quantity
        if self.actual_quantity is not None:
            self.actual_value = price * self.actual_quantity
            self.value_difference = self.actual_value - self.expected_value
        else:
            self.actual_value = Decimal('0')
            self.value_difference = Decimal('0')
        super().save(*args, **kwargs)

    def apply_adjustment(self, user):
        """Applique l'ajustement de stock en fonction de la différence."""
        if self.is_verified:
            raise ValueError("Cette ligne a déjà été ajustée")
        if self.actual_quantity is None:
            raise ValueError("Quantité réelle non saisie")

        diff = self.actual_quantity - self.expected_quantity
        if diff == 0:
            self.is_verified = True
            self.verified_by = user
            self.save()
            return

        stock, _ = Stock.objects.get_or_create(
            product=self.product,
            warehouse=self.inventory.warehouse,
            variant=self.variant,
        )

        if diff > 0:
            # Surplus : créer un lot
            lot_number = (
                f"INV-{self.inventory_id}-{self.product_id}-"
                f"{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
            )
            lot = Lot.objects.create(
                product=self.product,
                warehouse=self.inventory.warehouse,
                variant=self.variant,
                lot_number=lot_number,
                initial_quantity=diff,
                current_quantity=diff,
                unit=self.product.unit,
                purchase_price=self.product.purchase_price,
                selling_price=self.product.selling_price,
                status='good',
                created_by=user,
                notes=f"Ajustement inventaire {self.inventory.name}",
            )
            StockMovement.objects.create(
                product=self.product,
                lot=lot,
                variant=self.variant,
                to_warehouse=self.inventory.warehouse,
                movement_type='adjustment_plus',
                quantity=diff,
                reason=f"Ajustement inventaire {self.inventory.name}",
                created_by=user,
                reference_type='inventory',
                reference_id=self.inventory_id,
            )
        else:
            # Manque : consommer
            qty = abs(diff)
            ok, _ = stock.consume_stock(qty)
            if not ok:
                raise ValueError(
                    f"Impossible de consommer {qty} unités pour {self.product.name}")
            StockMovement.objects.create(
                product=self.product,
                variant=self.variant,
                from_warehouse=self.inventory.warehouse,
                movement_type='adjustment_minus',
                quantity=qty,
                reason=f"Ajustement inventaire {self.inventory.name}",
                created_by=user,
                reference_type='inventory',
                reference_id=self.inventory_id,
            )

        stock.update_quantity()
        self.is_verified = True
        self.verified_by = user
        self.save()


# ============================================================
# TRANSFER
# ============================================================
class Transfer(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('in_transit', 'En transit'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
    )

    reference_number = models.CharField(max_length=100, unique=True)
    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='transfers_out')
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='transfers_in')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_transfers')
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_transfers')
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transfert"
        verbose_name_plural = "Transferts"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference_number} ({self.from_warehouse} → {self.to_warehouse})"


class TransferItem(models.Model):
    transfer = models.ForeignKey(
        Transfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    # ✅ NOUVEAU : variante optionnelle
    variant = models.ForeignKey(
        'ProductVariant', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='transfer_items')
    quantity = models.IntegerField()
    source_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transferred_out')
    destination_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transferred_in')

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"