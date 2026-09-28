# apps/produits_stocks/serializers.py
from .models import Product, Warehouse, Stock
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone  # <-- IMPORTANT
from datetime import date, timedelta
from .models import (
    Category, UnitMeasure, Product, Warehouse, Lot,
    Stock, StockMovement, ExpiryAlert, Inventory, InventoryLine
)
from users.models import CustomUser

# ==================== CATEGORY ====================


class CategorySerializer(serializers.ModelSerializer):
    full_path = serializers.ReadOnlyField()
    children_count = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'code', 'description', 'parent', 'full_path',
            'image', 'is_active', 'children_count', 'products_count',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_children_count(self, obj):
        return obj.children.filter(is_active=True).count()

    def get_products_count(self, obj):
        return obj.products.filter(status='active').count()

    def validate_code(self, value):
        if Category.objects.exclude(id=self.instance.id if self.instance else None).filter(code=value).exists():
            raise serializers.ValidationError("Ce code existe déjà")
        return value


# ==================== UNIT MEASURE ====================
class UnitMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitMeasure
        fields = [
            'id', 'name', 'symbol', 'type', 'conversion_factor',
            'is_base_unit', 'is_active'
        ]
        read_only_fields = ['id']


# ==================== PRODUCT ====================
# apps/produits_stocks/serializers.py
# ============================================================
# PRODUCT LIST SERIALIZER - VERSION CORRIGÉE
# ============================================================

class ProductListSerializer(serializers.ModelSerializer):
    """Serializer pour la liste des produits (léger)"""
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    current_stock = serializers.ReadOnlyField()
    current_stock_value = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name', 'category', 'category_name',
            'unit', 'unit_symbol',
            'selling_price',      # ✅ Prix de vente (détail)
            'wholesale_price',    # ✅ PRIX DE GROS - AJOUTÉ
            'purchase_price',     # Prix d'achat
            'current_stock', 'current_stock_value', 'min_stock', 'status',
            'status_display', 'has_expiry', 'image', 'is_featured'
        ]


# ============================================================
# PRODUCT DETAIL SERIALIZER - DÉJÀ CORRECT
# ============================================================

class ProductDetailSerializer(serializers.ModelSerializer):
    """Serializer pour le détail d'un produit"""
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    current_stock = serializers.ReadOnlyField()
    current_stock_value = serializers.ReadOnlyField()
    expired_lots_count = serializers.ReadOnlyField()
    expiring_lots_count = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name', 'description', 'category', 'category_name',
            'unit', 'unit_symbol', 'type', 'type_display',
            'purchase_price',      # ✅ Prix d'achat
            'selling_price',       # ✅ Prix de vente (détail)
            'wholesale_price',     # ✅ Prix de gros
            'promo_price', 'tax_rate',
            'has_expiry', 'shelf_life_days', 'alert_days', 'min_stock', 'max_stock',
            'reorder_point', 'reorder_quantity', 'image', 'gallery', 'status',
            'status_display', 'is_featured', 'current_stock', 'current_stock_value',
            'expired_lots_count', 'expiring_lots_count', 'created_at', 'updated_at',
            'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ============================================================
# PRODUCT WRITE SERIALIZER - DÉJÀ CORRECT
# ============================================================

class ProductWriteSerializer(serializers.ModelSerializer):
    """Serializer pour l'écriture (création/modification)"""
    class Meta:
        model = Product
        fields = [
            'code', 'barcode', 'name', 'description', 'category', 'unit',
            'type',
            'purchase_price',     # ✅ Prix d'achat
            'selling_price',      # ✅ Prix de vente (détail)
            'wholesale_price',    # ✅ Prix de gros
            'promo_price', 'tax_rate', 'has_expiry', 'shelf_life_days',
            'alert_days', 'min_stock', 'max_stock', 'reorder_point',
            'reorder_quantity', 'image', 'gallery', 'status', 'is_featured'
        ]

# ==================== WAREHOUSE ====================


class WarehouseSerializer(serializers.ModelSerializer):
    occupancy_rate = serializers.ReadOnlyField()

    class Meta:
        model = Warehouse
        fields = [
            'id', 'name', 'code', 'type', 'address', 'city', 'country',
            'phone', 'email', 'manager', 'capacity', 'current_occupancy',
            'occupancy_rate', 'is_active', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        if Warehouse.objects.exclude(id=self.instance.id if self.instance else None).filter(code=value).exists():
            raise serializers.ValidationError("Ce code d'entrepôt existe déjà")
        return value


# ==================== LOT ====================
class LotListSerializer(serializers.ModelSerializer):
    """Serializer pour la liste des lots"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    days_until_expiry = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    available_quantity = serializers.ReadOnlyField()

    class Meta:
        model = Lot
        fields = [
            'id', 'lot_number', 'batch_number', 'product', 'product_name',
            'product_code', 'warehouse', 'warehouse_name', 'initial_quantity',
            'current_quantity', 'available_quantity', 'reserved_quantity',
            'expiry_date', 'days_until_expiry', 'status', 'status_display',
            'is_blocked', 'purchase_price', 'selling_price', 'created_at'
        ]


class LotDetailSerializer(serializers.ModelSerializer):
    """Serializer pour le détail d'un lot"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_has_expiry = serializers.BooleanField(
        source='product.has_expiry', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    days_until_expiry = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()
    is_expiring_soon = serializers.ReadOnlyField()
    available_quantity = serializers.ReadOnlyField()
    stock_value = serializers.ReadOnlyField()
    usage_rate = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Lot
        fields = [
            'id', 'lot_number', 'batch_number', 'barcode', 'product', 'product_name',
            'product_code', 'product_has_expiry', 'warehouse', 'warehouse_name',
            'unit', 'unit_symbol', 'initial_quantity', 'current_quantity',
            'available_quantity', 'reserved_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date', 'reception_date', 'last_used_date',
            'days_until_expiry', 'is_expired', 'is_expiring_soon', 'purchase_price',
            'selling_price', 'stock_value', 'usage_rate', 'status', 'status_display',
            'is_blocked', 'block_reason', 'blocked_date', 'notes', 'created_at',
            'created_by'
        ]
        read_only_fields = ['id', 'reception_date', 'created_at']


class LotWriteSerializer(serializers.ModelSerializer):
    """Serializer pour la création/modification de lot"""
    class Meta:
        model = Lot
        fields = [
            'lot_number', 'batch_number', 'barcode', 'product', 'warehouse',
            'unit', 'initial_quantity', 'current_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date', 'purchase_price', 'selling_price',
            'notes'
        ]

    def validate_lot_number(self, value):
        if Lot.objects.exclude(id=self.instance.id if self.instance else None).filter(lot_number=value).exists():
            raise serializers.ValidationError("Ce numéro de lot existe déjà")
        return value

    def validate(self, data):
        if data.get('expiry_date') and data.get('expiry_date') < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"})

        if data.get('manufacturing_date') and data.get('expiry_date'):
            if data['manufacturing_date'] >= data['expiry_date']:
                raise serializers.ValidationError(
                    "La date de fabrication doit être antérieure à la date d'expiration")

        return data


# ==================== STOCK ====================
# apps/produits_stocks/serializers.py

class StockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    available_quantity = serializers.ReadOnlyField()
    is_low_stock = serializers.ReadOnlyField()
    is_over_stock = serializers.ReadOnlyField()
    min_stock = serializers.ReadOnlyField()
    max_stock = serializers.ReadOnlyField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name', 'product_code', 'warehouse',
            'warehouse_name', 'quantity', 'available_quantity', 'reserved_quantity',
            'min_stock', 'max_stock', 'min_stock_override', 'max_stock_override',
            'is_low_stock', 'is_over_stock', 'last_update'
        ]
        read_only_fields = ['id', 'last_update']


class StockDetailSerializer(serializers.ModelSerializer):
    """Serializer détaillé avec lots disponibles"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    available_quantity = serializers.ReadOnlyField()
    lots_fifo = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name', 'warehouse', 'warehouse_name',
            'quantity', 'available_quantity', 'reserved_quantity', 'min_stock',
            'max_stock', 'lots_fifo', 'last_update'
        ]

    def get_lots_fifo(self, obj):
        lots = obj.get_lots_fifo()
        return LotListSerializer(lots[:10], many=True).data


# ==================== STOCK MOVEMENT ====================
class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    from_warehouse_name = serializers.CharField(
        source='from_warehouse.name', read_only=True)
    to_warehouse_name = serializers.CharField(
        source='to_warehouse.name', read_only=True)
    movement_type_display = serializers.CharField(
        source='get_movement_type_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            'id', 'product', 'product_name', 'lot', 'lot_number',
            'from_warehouse', 'from_warehouse_name', 'to_warehouse',
            'to_warehouse_name', 'movement_type', 'movement_type_display',
            'quantity', 'previous_quantity', 'new_quantity', 'reference_type',
            'reference_id', 'reference_number', 'reason', 'notes',
            'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']


class StockMovementCreateSerializer(serializers.ModelSerializer):
    """Serializer pour créer un mouvement de stock"""
    class Meta:
        model = StockMovement
        fields = [
            'product', 'lot', 'from_warehouse', 'to_warehouse',
            'movement_type', 'quantity', 'reference_type',
            'reference_id', 'reference_number', 'reason', 'notes'
        ]

    def validate(self, data):
        movement_type = data.get('movement_type')
        quantity = data.get('quantity', 0)

        if quantity <= 0:
            raise serializers.ValidationError(
                {"quantity": "La quantité doit être supérieure à 0"})

        # Vérifications pour les sorties
        if movement_type in ['sale_out', 'transfer_out', 'adjustment_minus', 'expired_out', 'damaged_out']:
            lot = data.get('lot')
            if lot:
                if quantity > lot.available_quantity:
                    raise serializers.ValidationError(
                        {"quantity": f"Stock insuffisant. Disponible: {lot.available_quantity}"}
                    )

        return data


# ==================== EXPIRY ALERT ====================
class ExpiryAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    severity_display = serializers.CharField(
        source='get_severity_display', read_only=True)

    class Meta:
        model = ExpiryAlert
        fields = [
            'id', 'lot', 'lot_number', 'product', 'product_name', 'product_code',
            'warehouse', 'warehouse_name', 'severity', 'severity_display',
            'days_left', 'message', 'is_read', 'is_processed', 'processed_at',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


# ==================== INVENTORY ====================
class InventoryLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)

    class Meta:
        model = InventoryLine
        fields = [
            'id', 'product', 'product_name', 'product_code', 'lot', 'lot_number',
            'expected_quantity', 'actual_quantity', 'difference', 'expected_value',
            'actual_value', 'value_difference', 'is_verified', 'notes'
        ]


class InventorySerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    lines = InventoryLineSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

    class Meta:
        model = Inventory
        fields = [
            'id', 'warehouse', 'warehouse_name', 'name', 'description',
            'start_date', 'end_date', 'status', 'status_display',
            'total_expected_value', 'total_actual_value', 'total_difference',
            'lines', 'notes', 'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']


class InventoryCreateSerializer(serializers.ModelSerializer):
    """Serializer pour créer un inventaire"""
    class Meta:
        model = Inventory
        fields = ['warehouse', 'name', 'description', 'start_date', 'notes']

    def validate(self, data):
        if data.get('start_date'):
            from django.utils import timezone
            if data['start_date'] < timezone.now():
                raise serializers.ValidationError(
                    {"start_date": "La date de début ne peut pas être dans le passé"})
        return data


class InventoryLineUpdateSerializer(serializers.ModelSerializer):
    """Serializer pour mettre à jour une ligne d'inventaire"""
    class Meta:
        model = InventoryLine
        fields = ['actual_quantity', 'notes']

    def validate_actual_quantity(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "La quantité réelle ne peut pas être négative")
        return value


# ==================== DASHBOARD / STATS ====================
class LowStockSerializer(serializers.Serializer):
    """Serializer pour les produits en stock faible"""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    current_stock = serializers.IntegerField()
    min_stock = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    warehouse_name = serializers.CharField()
    difference = serializers.IntegerField()


class ExpiringProductsSerializer(serializers.Serializer):
    """Serializer pour les produits qui expirent bientôt"""
    lot_id = serializers.IntegerField()
    lot_number = serializers.CharField()
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    warehouse_name = serializers.CharField()
    current_quantity = serializers.IntegerField()
    expiry_date = serializers.DateField()
    days_left = serializers.IntegerField()
    severity = serializers.CharField()


# produits_stocks/serializers.py

# ... (autres sérialiseurs existants) ...

# ==================== TRANSFER ====================


class TransferItemSerializer(serializers.Serializer):
    """
    Sérialiseur pour un article à transférer.
    """
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)

    def validate_product_id(self, value):
        # Vérifier que le produit existe et est actif
        try:
            product = Product.objects.get(id=value, status='active')
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                "Produit introuvable ou inactif.")
        return value

    def validate(self, data):
        # On pourrait vérifier le stock disponible ici, mais on le fera dans la vue
        # car on a besoin de l'entrepôt source
        return data


class TransferRequestSerializer(serializers.Serializer):
    """
    Sérialiseur pour la requête de transfert.
    """
    from_warehouse_id = serializers.IntegerField()
    to_warehouse_id = serializers.IntegerField()
    items = TransferItemSerializer(many=True, allow_empty=False)
    reason = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_from_warehouse_id(self, value):
        try:
            Warehouse.objects.get(id=value, is_active=True)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                "Entrepôt source introuvable ou inactif.")
        return value

    def validate_to_warehouse_id(self, value):
        try:
            Warehouse.objects.get(id=value, is_active=True)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                "Entrepôt destination introuvable ou inactif.")
        return value

    def validate(self, data):
        if data.get('from_warehouse_id') == data.get('to_warehouse_id'):
            raise serializers.ValidationError(
                "Les entrepôts source et destination doivent être différents.")

        # Vérification du stock disponible pour chaque produit
        from_warehouse_id = data['from_warehouse_id']
        for item in data['items']:
            product_id = item['product_id']
            quantity = item['quantity']
            try:
                stock = Stock.objects.get(
                    product_id=product_id, warehouse_id=from_warehouse_id)
            except Stock.DoesNotExist:
                raise serializers.ValidationError(
                    f"Le produit {product_id} n'a pas de stock dans l'entrepôt source."
                )
            if stock.available_quantity < quantity:
                raise serializers.ValidationError(
                    f"Stock insuffisant pour le produit {product_id}. Disponible : {stock.available_quantity}"
                )
        return data


class TransferItemResponseSerializer(serializers.Serializer):
    """
    Sérialiseur pour un article dans la réponse.
    """
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    from_warehouse = serializers.CharField()
    to_warehouse = serializers.CharField()
    lots_used = serializers.ListField(child=serializers.DictField())


class TransferResponseSerializer(serializers.Serializer):
    """
    Sérialiseur pour la réponse de transfert.
    """
    message = serializers.CharField()
    movements = TransferItemResponseSerializer(many=True)


# apps/produits_stocks/serializers.py

class ManualStockAddSerializer(serializers.Serializer):
    """
    Sérialiseur pour l'ajout manuel de stock (sans commande)
    """
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    lot_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True)
    batch_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    manufacturing_date = serializers.DateField(required=False, allow_null=True)
    purchase_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False)
    selling_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(
        required=False, allow_blank=True, default="Ajout manuel")

    def validate(self, data):
        # Vérifier que le produit existe
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                {"product_id": "Produit non trouvé"})

        # Vérifier que l'entrepôt existe
        try:
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                {"warehouse_id": "Entrepôt non trouvé"})

        # Si une date d'expiration est fournie, vérifier qu'elle n'est pas dans le passé
        if data.get('expiry_date') and data['expiry_date'] < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"})

        # Si le produit a une expiration, la date est obligatoire
        if product.has_expiry and not data.get('expiry_date'):
            raise serializers.ValidationError(
                {"expiry_date": "Ce produit a une date d'expiration obligatoire"})

        # Générer un numéro de lot automatique si non fourni
        if not data.get('lot_number'):
            data['lot_number'] = f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{data['product_id']}"

        return data
