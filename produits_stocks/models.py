# apps/produits_stocks/models.py
# ============================================================
# MODELS OPTIMISÉS - Index ajoutés pour performances
# ============================================================

from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from users.models import CustomUser


# ============================================================
# CATEGORY
# ============================================================
class Category(models.Model):
    """
    Catégorie de produits pour organisation hiérarchique
    """
    name = models.CharField(max_length=100, verbose_name="Nom")
    code = models.CharField(max_length=50, unique=True, verbose_name="Code")
    description = models.TextField(blank=True, verbose_name="Description")
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="Catégorie parente"
    )
    image = models.ImageField(upload_to='categories/',
                              null=True, blank=True, verbose_name="Image")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date modification")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
    """
    Unité de mesure pour les produits
    """
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
        max_digits=10,
        decimal_places=4,
        default=1.0000,
        verbose_name="Facteur de conversion"
    )
    is_base_unit = models.BooleanField(
        default=False, verbose_name="Unité de base")
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
    """
    Produit avec gestion des dates d'expiration
    """
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

    # Identifiants
    code = models.CharField(max_length=50, unique=True,
                            verbose_name="Code produit")
    barcode = models.CharField(
        max_length=100, unique=True, null=True, blank=True, verbose_name="Code-barres")
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")

    # Classification
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name="Catégorie"
    )
    unit = models.ForeignKey(
        UnitMeasure,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Unité de mesure"
    )
    type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='standard', verbose_name="Type")

    # Prix
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix d'achat")
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Prix de vente")
    wholesale_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name="Prix de gros"
    )
    promo_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name="Prix promotionnel"
    )

    # Taxes
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Taux de TVA (%)")

    # Gestion des dates d'expiration
    has_expiry = models.BooleanField(
        default=False, verbose_name="A une date d'expiration")
    shelf_life_days = models.IntegerField(
        null=True, blank=True,
        help_text="Durée de conservation en jours",
        verbose_name="Durée de conservation"
    )
    alert_days = models.IntegerField(
        default=30,
        help_text="Jours avant expiration pour déclencher une alerte",
        verbose_name="Jours d'alerte"
    )

    # Seuils de stock
    min_stock = models.IntegerField(default=0, verbose_name="Stock minimum")
    max_stock = models.IntegerField(default=0, verbose_name="Stock maximum")
    reorder_point = models.IntegerField(
        default=0, verbose_name="Point de commande")
    reorder_quantity = models.IntegerField(
        default=0, verbose_name="Quantité de réapprovisionnement")

    # Images
    image = models.ImageField(
        upload_to='products/', null=True, blank=True, verbose_name="Image principale")
    gallery = models.JSONField(
        default=list, blank=True, verbose_name="Galerie d'images")

    # Statut
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="Statut")
    is_featured = models.BooleanField(
        default=False, verbose_name="Produit vedette")

    # Métadonnées
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date modification")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Produit"
        verbose_name_plural = "Produits"
        ordering = ['name']
        indexes = [
            # ✅ Index simples
            models.Index(fields=['code'], name='product_code_idx'),
            models.Index(fields=['barcode'], name='product_barcode_idx'),
            models.Index(fields=['name'], name='product_name_idx'),
            models.Index(fields=['status'], name='product_status_idx'),
            models.Index(fields=['is_featured'], name='product_featured_idx'),
            models.Index(fields=['has_expiry'], name='product_has_expiry_idx'),

            # ✅ Index composites pour filtres fréquents
            models.Index(fields=['category', 'status'],
                         name='product_cat_status_idx'),
            models.Index(fields=['status', 'name'],
                         name='product_status_name_idx'),
            models.Index(fields=['is_featured', 'status'],
                         name='product_feat_status_idx'),
            models.Index(fields=['-created_at'], name='product_created_idx'),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def current_stock(self):
        return self.stocks.aggregate(total=models.Sum('quantity'))['total'] or 0

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
# WAREHOUSE
# ============================================================
class Warehouse(models.Model):
    """
    Entrepôt / Magasin
    """
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

    # Adresse
    address = models.TextField(verbose_name="Adresse")
    city = models.CharField(max_length=100, blank=True, verbose_name="Ville")
    country = models.CharField(
        max_length=100, default='Sénégal', verbose_name="Pays")

    # Contact
    phone = models.CharField(max_length=20, blank=True,
                             verbose_name="Téléphone")
    email = models.EmailField(blank=True, verbose_name="Email")
    manager = models.CharField(
        max_length=100, blank=True, verbose_name="Responsable")

    # Capacité
    capacity = models.IntegerField(
        null=True, blank=True, verbose_name="Capacité maximale")
    current_occupancy = models.IntegerField(
        default=0, verbose_name="Occupation actuelle")

    # Statut
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Date modification")

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
    """
    Lot de produits avec date d'expiration
    Gestion FIFO (First Expired First Out)
    """
    STATUS_CHOICES = (
        ('good', 'Bon'),
        ('expiring', 'Expire bientôt'),
        ('expired', 'Expiré'),
        ('blocked', 'Bloqué'),
        ('quarantine', 'En quarantaine'),
    )

    # Références
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='lots',
        verbose_name="Produit"
    )
    warehouse = models.ForeignKey(
        'Warehouse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lots',
        verbose_name="Entrepôt"
    )

    # Identification
    lot_number = models.CharField(
        max_length=100, unique=True, verbose_name="Numéro de lot")
    batch_number = models.CharField(
        max_length=100, blank=True, verbose_name="Numéro de batch")
    barcode = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Code-barres")

    # Quantités
    initial_quantity = models.IntegerField(verbose_name="Quantité initiale")
    current_quantity = models.IntegerField(verbose_name="Quantité actuelle")
    reserved_quantity = models.IntegerField(
        default=0, verbose_name="Quantité réservée")
    min_quantity_alert = models.IntegerField(
        default=0, verbose_name="Alerte quantité minimale")

    # Unités
    unit = models.ForeignKey(
        'UnitMeasure',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Unité"
    )

    # Dates
    manufacturing_date = models.DateField(
        null=True, blank=True, verbose_name="Date de fabrication")
    expiry_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'expiration")
    reception_date = models.DateField(
        auto_now_add=True, verbose_name="Date de réception")
    last_used_date = models.DateField(
        null=True, blank=True, verbose_name="Dernière utilisation")
    blocked_date = models.DateField(
        null=True, blank=True, verbose_name="Date de blocage")

    # Prix
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Prix d'achat unitaire"
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Prix de vente unitaire"
    )

    # Statut
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='good', verbose_name="Statut")
    is_blocked = models.BooleanField(default=False, verbose_name="Bloqué")
    block_reason = models.TextField(
        blank=True, verbose_name="Raison du blocage")

    # Métadonnées
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ['expiry_date', 'created_at']
        indexes = [
            # ✅ Index existants
            models.Index(fields=['product', 'expiry_date'],
                         name='lot_prod_expiry_idx'),
            models.Index(fields=['status', 'expiry_date'],
                         name='lot_status_expiry_idx'),
            models.Index(fields=['lot_number'], name='lot_number_idx'),

            # ✅ Nouveaux index pour filtres fréquents
            models.Index(fields=['product', 'warehouse'],
                         name='lot_prod_wh_idx'),
            models.Index(fields=['product', 'warehouse',
                         'status'], name='lot_prod_wh_status_idx'),
            models.Index(fields=['warehouse', 'expiry_date'],
                         name='lot_wh_expiry_idx'),
            models.Index(fields=['expiry_date'], name='lot_expiry_idx'),
            models.Index(fields=['current_quantity'], name='lot_qty_idx'),
            models.Index(fields=['is_blocked'], name='lot_blocked_idx'),
            models.Index(fields=['-created_at'], name='lot_created_idx'),
        ]

    def __str__(self):
        expiry_info = f"Exp: {self.expiry_date}" if self.expiry_date else "Pas d'expiration"
        return f"{self.product.name} - Lot {self.lot_number} ({expiry_info})"

    def save(self, *args, **kwargs):
        """
        Sauvegarde avec mise à jour automatique du statut
        NE MET PAS À JOUR LE STOCK AUTOMATIQUEMENT pour éviter les doublons
        """
        today = date.today()

        # Récupérer les jours d'alerte du produit
        alert_days = 30
        if self.product and self.product.alert_days:
            alert_days = self.product.alert_days

        # Mise à jour du statut UNIQUEMENT si une date d'expiration existe
        if self.expiry_date:
            alert_date = today + timedelta(days=alert_days)

            if self.expiry_date < today:
                self.status = 'expired'
            elif self.expiry_date <= alert_date:
                self.status = 'expiring'
            else:
                self.status = 'good'
        else:
            # Pas de date d'expiration, le lot est considéré comme bon
            self.status = 'good'

        # Appel du save parent SANS mettre à jour le stock automatiquement
        super().save(*args, **kwargs)

    @property
    def days_until_expiry(self):
        """Jours restants avant expiration"""
        if self.expiry_date:
            delta = self.expiry_date - date.today()
            return delta.days
        return None

    @property
    def is_expired(self):
        """Vérifie si le lot est expiré"""
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    @property
    def is_expiring_soon(self):
        """Vérifie si le lot expire bientôt"""
        if not self.expiry_date:
            return False

        alert_days = 30
        if self.product and self.product.alert_days:
            alert_days = self.product.alert_days

        return not self.is_expired and self.days_until_expiry <= alert_days

    @property
    def available_quantity(self):
        """Quantité disponible (non réservée)"""
        return self.current_quantity - self.reserved_quantity

    @property
    def stock_value(self):
        """Valeur du stock de ce lot"""
        return self.current_quantity * self.purchase_price

    @property
    def usage_rate(self):
        """Taux d'utilisation (pourcentage)"""
        if self.initial_quantity > 0:
            return ((self.initial_quantity - self.current_quantity) / self.initial_quantity) * 100
        return 0

    def reserve(self, quantity):
        """Réserve une quantité du lot"""
        if quantity <= self.available_quantity:
            self.reserved_quantity += quantity
            self.save()
            self._update_stock()
            return True
        return False

    def unreserve(self, quantity):
        """Libère une réservation"""
        self.reserved_quantity = max(0, self.reserved_quantity - quantity)
        self.save()
        self._update_stock()

    def consume(self, quantity):
        """Consomme une quantité du lot (sortie définitive)"""
        if quantity <= self.available_quantity:
            self.current_quantity -= quantity
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.last_used_date = date.today()
            self.save()
            self._update_stock()
            return True
        return False

    def block(self, reason=None):
        """Bloque le lot"""
        self.is_blocked = True
        self.status = 'blocked'
        self.block_reason = reason or ''
        self.blocked_date = date.today()
        self.save()
        self._update_stock()

    def unblock(self):
        """Débloque le lot"""
        self.is_blocked = False
        self.block_reason = ''
        self.blocked_date = None
        self.save()
        self._update_stock()

    def _update_stock(self):
        """
        Méthode privée pour mettre à jour le stock
        Utilisée uniquement pour les opérations manuelles
        """
        if self.warehouse:
            try:
                from .models import Stock
                stock, created = Stock.objects.get_or_create(
                    product=self.product,
                    warehouse=self.warehouse
                )
                stock.update_quantity()
            except Exception:
                pass


# ============================================================
# STOCK
# ============================================================
class Stock(models.Model):
    """
    Stock par produit et entrepôt
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name="Produit"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name="Entrepôt"
    )
    quantity = models.IntegerField(default=0, verbose_name="Quantité totale")
    reserved_quantity = models.IntegerField(
        default=0, verbose_name="Quantité réservée")
    min_stock_override = models.IntegerField(
        null=True, blank=True, verbose_name="Stock minimum (surcharge)")
    max_stock_override = models.IntegerField(
        null=True, blank=True, verbose_name="Stock maximum (surcharge)")
    last_update = models.DateTimeField(
        auto_now=True, verbose_name="Dernière mise à jour")

    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"
        unique_together = ['product', 'warehouse']
        indexes = [
            models.Index(fields=['product', 'warehouse'],
                         name='stock_prod_wh_idx'),
            models.Index(fields=['quantity'], name='stock_qty_idx'),
            models.Index(fields=['warehouse', 'quantity'],
                         name='stock_wh_qty_idx'),
            models.Index(fields=['product'], name='stock_product_idx'),
            models.Index(fields=['warehouse'], name='stock_warehouse_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.warehouse.name}: {self.quantity}"

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

    def update_quantity(self):
        """
        Met à jour la quantité TOTALE à partir des lots
        C'est la SEULE source de vérité pour la quantité
        """
        from django.db.models import Sum

        total = self.product.lots.filter(
            warehouse=self.warehouse,
            is_blocked=False
        ).exclude(status='expired').aggregate(
            total=Sum('current_quantity')
        )['total'] or 0

        self.quantity = total
        self.save(update_fields=['quantity', 'last_update'])
        self.product.update_status()
        return total

    def get_lots_fifo(self, quantity_needed=None):
        lots = self.product.lots.filter(
            warehouse=self.warehouse,
            current_quantity__gt=0,
            is_blocked=False
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
        """
        Consomme du stock (sortie définitive) en utilisant FIFO
        """
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
    """
    Historique des mouvements de stock
    """
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
        Product,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name="Produit"
    )
    lot = models.ForeignKey(
        Lot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements',
        verbose_name="Lot"
    )
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements_out',
        verbose_name="Entrepôt source"
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements_in',
        verbose_name="Entrepôt destination"
    )

    movement_type = models.CharField(
        max_length=30, choices=TYPE_CHOICES, verbose_name="Type de mouvement")
    quantity = models.IntegerField(verbose_name="Quantité")
    previous_quantity = models.IntegerField(
        default=0, verbose_name="Quantité précédente")
    new_quantity = models.IntegerField(
        default=0, verbose_name="Nouvelle quantité")

    reference_type = models.CharField(
        max_length=50, blank=True, verbose_name="Type de référence")
    reference_id = models.IntegerField(
        null=True, blank=True, verbose_name="ID de référence")
    reference_number = models.CharField(
        max_length=100, blank=True, verbose_name="Numéro de référence")

    reason = models.CharField(
        max_length=200, blank=True, verbose_name="Raison")
    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Créé par"
    )

    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at'],
                         name='movement_prod_date_idx'),
            models.Index(fields=['movement_type'], name='movement_type_idx'),
            models.Index(fields=['reference_type',
                         'reference_id'], name='movement_ref_idx'),
            models.Index(fields=['-created_at'], name='movement_date_idx'),
            models.Index(fields=['lot'], name='movement_lot_idx'),
            models.Index(fields=['from_warehouse'],
                         name='movement_from_wh_idx'),
            models.Index(fields=['to_warehouse'], name='movement_to_wh_idx'),
        ]

    def __str__(self):
        return f"{self.movement_type} - {self.product.name}: {self.quantity} ({self.created_at})"

    def save(self, *args, **kwargs):
        """
        Sauvegarde du mouvement :
        - Calcule previous_quantity et new_quantity à partir du lot (si présent)
        - NE MODIFIE PAS le lot
        - Met à jour le stock (recalcul à partir des lots) après la sauvegarde
        """
        if self.lot:
            self.previous_quantity = self.lot.current_quantity
            if self.movement_type in ['sale_out', 'transfer_out', 'adjustment_minus',
                                      'expired_out', 'damaged_out', 'return_out']:
                self.new_quantity = self.previous_quantity - self.quantity
            else:
                self.new_quantity = self.previous_quantity + self.quantity
        else:
            self.previous_quantity = 0
            self.new_quantity = 0

        super().save(*args, **kwargs)

        if self.lot and self.lot.warehouse:
            stock, _ = Stock.objects.get_or_create(
                product=self.product,
                warehouse=self.lot.warehouse
            )
            stock.update_quantity()


# ============================================================
# EXPIRY ALERT
# ============================================================
class ExpiryAlert(models.Model):
    """
    Alertes pour les produits qui expirent bientôt
    """
    SEVERITY_CHOICES = (
        ('info', 'Information'),
        ('warning', 'Attention'),
        ('critical', 'Critique'),
        ('emergency', 'Urgence'),
    )

    lot = models.ForeignKey(
        Lot,
        on_delete=models.CASCADE,
        related_name='alerts',
        verbose_name="Lot"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='expiry_alerts',
        verbose_name="Produit"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Entrepôt"
    )

    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default='warning', verbose_name="Sévérité")
    days_left = models.IntegerField(verbose_name="Jours restants")
    message = models.TextField(verbose_name="Message")

    is_read = models.BooleanField(default=False, verbose_name="Lu")
    is_processed = models.BooleanField(default=False, verbose_name="Traité")
    processed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Date traitement")
    processed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_alerts',
        verbose_name="Traité par"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")

    class Meta:
        verbose_name = "Alerte d'expiration"
        verbose_name_plural = "Alertes d'expiration"
        ordering = ['days_left', 'created_at']
        indexes = [
            models.Index(fields=['product', 'is_processed'],
                         name='alert_prod_proc_idx'),
            models.Index(fields=['severity', 'is_read'],
                         name='alert_sev_read_idx'),
            models.Index(fields=['is_processed'], name='alert_processed_idx'),
            models.Index(fields=['is_read'], name='alert_read_idx'),
            models.Index(fields=['-created_at'], name='alert_created_idx'),
        ]

    def __str__(self):
        return f"Alerte {self.severity} - {self.product.name} - J-{self.days_left}"

    def mark_as_read(self):
        self.is_read = True
        self.save()

    def mark_as_processed(self, user):
        self.is_processed = True
        self.processed_at = timezone.now()
        self.processed_by = user
        self.save()


# ============================================================
# INVENTORY
# ============================================================
class Inventory(models.Model):
    """
    Inventaire physique
    """
    STATUS_CHOICES = (
        ('planned', 'Planifié'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
        ('verified', 'Vérifié'),
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='inventories',
        verbose_name="Entrepôt"
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")

    start_date = models.DateTimeField(verbose_name="Date début")
    end_date = models.DateTimeField(
        null=True, blank=True, verbose_name="Date fin")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='planned', verbose_name="Statut")

    total_expected_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Valeur théorique")
    total_actual_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Valeur réelle")
    total_difference = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Différence totale")

    notes = models.TextField(blank=True, verbose_name="Notes")

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Date création")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventories',
        verbose_name="Créé par"
    )
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_inventories',
        verbose_name="Vérifié par"
    )

    class Meta:
        verbose_name = "Inventaire"
        verbose_name_plural = "Inventaires"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['warehouse', '-created_at'],
                         name='inv_wh_date_idx'),
            models.Index(fields=['status'], name='inv_status_idx'),
        ]

    def __str__(self):
        return f"{self.name} - {self.warehouse.name} ({self.status})"

    def start(self):
        self.status = 'in_progress'
        self.start_date = timezone.now()
        self.save()

    def complete(self):
        self.status = 'completed'
        self.end_date = timezone.now()

        self.total_expected_value = self.lines.aggregate(
            total=models.Sum('expected_value')
        )['total'] or 0

        self.total_actual_value = self.lines.aggregate(
            total=models.Sum('actual_value')
        )['total'] or 0

        self.total_difference = self.total_actual_value - self.total_expected_value
        self.save()

    def calculate_differences(self):
        for line in self.lines.all():
            line.calculate_difference()
        self.complete()


# ============================================================
# INVENTORY LINE
# ============================================================
class InventoryLine(models.Model):
    """
    Ligne d'inventaire
    """
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name="Inventaire"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name="Produit"
    )
    lot = models.ForeignKey(
        Lot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Lot"
    )

    expected_quantity = models.IntegerField(verbose_name="Quantité théorique")
    actual_quantity = models.IntegerField(
        null=True, blank=True, verbose_name="Quantité réelle")
    difference = models.IntegerField(default=0, verbose_name="Différence")

    expected_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Valeur théorique")
    actual_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Valeur réelle")
    value_difference = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Différence valeur")

    is_verified = models.BooleanField(default=False, verbose_name="Vérifié")
    verified_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Date vérification")
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Vérifié par"
    )

    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Ligne d'inventaire"
        verbose_name_plural = "Lignes d'inventaire"
        unique_together = ['inventory', 'product', 'lot']
        indexes = [
            models.Index(fields=['inventory', 'product'],
                         name='invline_inv_prod_idx'),
            models.Index(fields=['is_verified'], name='invline_verified_idx'),
            models.Index(fields=['inventory'], name='invline_inv_idx'),
        ]

    def __str__(self):
        lot_info = f" - Lot {self.lot.lot_number}" if self.lot else ""
        return f"{self.product.name}{lot_info} - Expected: {self.expected_quantity}"

    def save(self, *args, **kwargs):
        if self.actual_quantity is not None:
            self.difference = self.actual_quantity - self.expected_quantity
            self.expected_value = self.expected_quantity * self.product.purchase_price
            self.actual_value = self.actual_quantity * self.product.purchase_price
            self.value_difference = self.actual_value - self.expected_value
        super().save(*args, **kwargs)

    def calculate_difference(self):
        if self.actual_quantity is not None:
            self.difference = self.actual_quantity - self.expected_quantity
            self.expected_value = self.expected_quantity * self.product.purchase_price
            self.actual_value = self.actual_quantity * self.product.purchase_price
            self.value_difference = self.actual_value - self.expected_value
            self.save()

    def verify(self, user):
        self.is_verified = True
        self.verified_at = timezone.now()
        self.verified_by = user
        self.save()

    def apply_adjustment(self, user):
        if self.difference != 0:
            movement_type = 'adjustment_plus' if self.difference > 0 else 'adjustment_minus'

            if self.lot:
                self.lot.current_quantity += self.difference
                self.lot.save()

                StockMovement.objects.create(
                    product=self.product,
                    lot=self.lot,
                    from_warehouse=self.lot.warehouse,
                    movement_type=movement_type,
                    quantity=abs(self.difference),
                    reason=f"Ajustement inventaire {self.inventory.name}",
                    reference_type='inventory',
                    reference_id=self.inventory.id,
                    created_by=user,
                    notes=self.notes
                )
            else:
                stock, _ = Stock.objects.get_or_create(
                    product=self.product,
                    warehouse=self.inventory.warehouse
                )
                stock.quantity += self.difference
                stock.save()

            self.verify(user)


# ============================================================
# TRANSFER
# ============================================================
class Transfer(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
    )
    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='transfers_in')
    reference_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='validated_transfers')

    class Meta:
        verbose_name = "Transfert"
        verbose_name_plural = "Transferts"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reference_number'], name='transfer_ref_idx'),
            models.Index(fields=['status'], name='transfer_status_idx'),
            models.Index(fields=['from_warehouse'],
                         name='transfer_from_wh_idx'),
            models.Index(fields=['to_warehouse'], name='transfer_to_wh_idx'),
            models.Index(fields=['-created_at'], name='transfer_date_idx'),
        ]

    def __str__(self):
        return f"{self.reference_number} ({self.status})"


# ============================================================
# TRANSFER ITEM
# ============================================================
class TransferItem(models.Model):
    transfer = models.ForeignKey(
        Transfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    source_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    destination_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = "Ligne de transfert"
        verbose_name_plural = "Lignes de transfert"
        indexes = [
            models.Index(fields=['transfer'],
                         name='transferitem_transfer_idx'),
            models.Index(fields=['product'], name='transferitem_product_idx'),
        ]

    def __str__(self):
        return f"{self.transfer.reference_number} - {self.product.name} x{self.quantity}"
