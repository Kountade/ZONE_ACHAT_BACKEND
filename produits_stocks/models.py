from django.db import models

# Create your models here.
# apps/produits_stocks/models.py
from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from datetime import date, timedelta

from users.models import CustomUser


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

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} > {self.name}"
        return self.name


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

    def __str__(self):
        return f"{self.name} ({self.symbol})"


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

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def occupancy_rate(self):
        if self.capacity and self.capacity > 0:
            return (self.current_occupancy / self.capacity) * 100
        return 0


# apps/produits_stocks/models.py

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
            models.Index(fields=['product', 'expiry_date']),
            models.Index(fields=['status', 'expiry_date']),
            models.Index(fields=['lot_number']),
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

        # NOTE: La mise à jour du stock est maintenant gérée MANUELLEMENT
        # dans les vues/sérialiseurs pour éviter les doublons
        # Ne pas appeler stock.update_quantity() ici !

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
            # Mettre à jour le stock après réservation
            self._update_stock()
            return True
        return False

    def unreserve(self, quantity):
        """Libère une réservation"""
        self.reserved_quantity = max(0, self.reserved_quantity - quantity)
        self.save()
        # Mettre à jour le stock après libération
        self._update_stock()

    def consume(self, quantity):
        """Consomme une quantité du lot (sortie définitive)"""
        if quantity <= self.available_quantity:
            self.current_quantity -= quantity
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.last_used_date = date.today()
            self.save()
            # Mettre à jour le stock après consommation
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
        # Mettre à jour le stock après blocage
        self._update_stock()

    def unblock(self):
        """Débloque le lot"""
        self.is_blocked = False
        self.block_reason = ''
        self.blocked_date = None
        self.save()
        # Mettre à jour le stock après déblocage
        self._update_stock()

    def _update_stock(self):
        """
        Méthode privée pour mettre à jour le stock
        Utilisée uniquement pour les opérations manuelles (réservation, consommation, etc.)
        """
        if self.warehouse:
            try:
                from .models import Stock
                stock, created = Stock.objects.get_or_create(
                    product=self.product,
                    warehouse=self.warehouse
                )
                stock.update_quantity()
            except Exception as e:
                # Ignorer les erreurs
                pass

# apps/produits_stocks/models.py


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
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['quantity']),
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

        # Mettre à jour UNIQUEMENT le champ quantity
        # Ne pas modifier reserved_quantity ici
        self.quantity = total
        self.save(update_fields=['quantity', 'last_update'])

        # Mettre à jour le statut du produit
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

            # IMPORTANT: Ne pas modifier quantity manuellement !
            # On recalcule à partir des lots après consommation
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.update_quantity()  # Recalcul automatique depuis les lots

            return True, lots
        return False, "Impossible de consommer"


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
            models.Index(fields=['product', 'created_at']),
            models.Index(fields=['movement_type']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f"{self.movement_type} - {self.product.name}: {self.quantity} ({self.created_at})"

    def save(self, *args, **kwargs):
        """
        Sauvegarde du mouvement :
        - Calcule previous_quantity et new_quantity à partir du lot (si présent)
        - NE MODIFIE PAS le lot (la modification est déjà faite dans les vues)
        - Met à jour le stock (recalcul à partir des lots) après la sauvegarde
        """
        # Calcul des quantités historiques (sans modifier le lot)
        if self.lot:
            self.previous_quantity = self.lot.current_quantity
            # On calcule la nouvelle quantité théorique (pour l'historique)
            if self.movement_type in ['sale_out', 'transfer_out', 'adjustment_minus',
                                      'expired_out', 'damaged_out', 'return_out']:
                self.new_quantity = self.previous_quantity - self.quantity
            else:
                self.new_quantity = self.previous_quantity + self.quantity
        else:
            self.previous_quantity = 0
            self.new_quantity = 0

        # Sauvegarde du mouvement (ne modifie pas le lot)
        super().save(*args, **kwargs)

        # Mise à jour du stock (recalcul à partir des lots)
        if self.lot and self.lot.warehouse:
            stock, _ = Stock.objects.get_or_create(
                product=self.product,
                warehouse=self.lot.warehouse
            )
            stock.update_quantity()


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
            models.Index(fields=['product', 'is_processed']),
            models.Index(fields=['severity', 'is_read']),
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


class TransferItem(models.Model):
    transfer = models.ForeignKey(
        Transfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    # On peut stocker les lots source et destination si besoin
    source_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    destination_lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
