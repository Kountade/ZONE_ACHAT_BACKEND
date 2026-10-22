# apps/produits_stocks/serializers.py
# ============================================================
# SERIALIZERS OPTIMISÉS - Compatible annotations SQL
# ============================================================

from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from .models import (
    Category, UnitMeasure, Product, Warehouse, Lot,
    Stock, StockMovement, ExpiryAlert, Inventory, InventoryLine,
    Transfer, TransferItem
)
from users.models import CustomUser


# ============================================================
# CATEGORY
# ============================================================

class CategorySerializer(serializers.ModelSerializer):
    """
    ✅ Category optimisé - utilise annotations SQL si disponibles.
    """
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
        # ✅ Utilise l'annotation SQL si disponible
        if hasattr(obj, 'children_count_annotated'):
            return obj.children_count_annotated
        return obj.children.filter(is_active=True).count()

    def get_products_count(self, obj):
        if hasattr(obj, 'products_count_annotated'):
            return obj.products_count_annotated
        return obj.products.filter(status='active').count()

    def validate_code(self, value):
        if Category.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(code=value).exists():
            raise serializers.ValidationError("Ce code existe déjà")
        return value


class CategoryListSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes de catégories."""
    class Meta:
        model = Category
        fields = ['id', 'name', 'code', 'is_active']


# ============================================================
# UNIT MEASURE
# ============================================================

class UnitMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitMeasure
        fields = [
            'id', 'name', 'symbol', 'type', 'conversion_factor',
            'is_base_unit', 'is_active'
        ]
        read_only_fields = ['id']


# ============================================================
# PRODUCT
# ============================================================

class ProductLiteSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer ULTRA-LÉGER pour le POS, listes rapides.
    Utilise current_stock_annotated (annotation SQL).
    """
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    current_stock = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name',
            'category_id', 'category_name',
            'unit_id', 'unit_symbol',
            'type', 'type_display',
            'purchase_price', 'selling_price', 'wholesale_price',
            'tax_rate', 'has_expiry', 'alert_days',
            'min_stock', 'max_stock',
            'status', 'status_display',
            'is_featured',
            'image', 'image_url',
            'current_stock',
        ]

    def get_current_stock(self, obj):
        # ✅ Utilise l'annotation si disponible
        if hasattr(obj, 'current_stock_annotated'):
            return obj.current_stock_annotated or 0
        return obj.current_stock

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        except Exception:
            return None


class ProductListSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer OPTIMISÉ pour les listes standards.
    Utilise current_stock_annotated (annotation SQL).
    """
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    current_stock = serializers.SerializerMethodField()
    current_stock_value = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name',
            'category', 'category_name',
            'unit', 'unit_symbol',
            'selling_price',
            'wholesale_price',
            'purchase_price',
            'current_stock', 'current_stock_value',
            'min_stock',
            'status', 'status_display',
            'has_expiry',
            'image',
            'is_featured'
        ]

    def get_current_stock(self, obj):
        # ✅ Utilise l'annotation SQL si disponible
        if hasattr(obj, 'current_stock_annotated'):
            return obj.current_stock_annotated or 0
        return obj.current_stock

    def get_current_stock_value(self, obj):
        stock = self.get_current_stock(obj)
        return float(stock) * float(obj.purchase_price or 0)


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer détaillé - utilise annotations SQL.
    """
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    current_stock = serializers.SerializerMethodField()
    current_stock_value = serializers.SerializerMethodField()
    expired_lots_count = serializers.SerializerMethodField()
    expiring_lots_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name', 'description',
            'category', 'category_name',
            'unit', 'unit_symbol',
            'type', 'type_display',
            'purchase_price', 'selling_price', 'wholesale_price',
            'promo_price', 'tax_rate',
            'has_expiry', 'shelf_life_days', 'alert_days',
            'min_stock', 'max_stock',
            'reorder_point', 'reorder_quantity',
            'image', 'gallery',
            'status', 'status_display', 'is_featured',
            'current_stock', 'current_stock_value',
            'expired_lots_count', 'expiring_lots_count',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_current_stock(self, obj):
        if hasattr(obj, 'current_stock_annotated'):
            return obj.current_stock_annotated or 0
        return obj.current_stock

    def get_current_stock_value(self, obj):
        stock = self.get_current_stock(obj)
        return float(stock) * float(obj.purchase_price or 0)

    def get_expired_lots_count(self, obj):
        if hasattr(obj, 'expired_lots_annotated'):
            return obj.expired_lots_annotated or 0
        return obj.expired_lots_count

    def get_expiring_lots_count(self, obj):
        if hasattr(obj, 'expiring_lots_annotated'):
            return obj.expiring_lots_annotated or 0
        return obj.expiring_lots_count


class ProductWriteSerializer(serializers.ModelSerializer):
    """Serializer pour l'écriture (création/modification)."""
    class Meta:
        model = Product
        fields = [
            'code', 'barcode', 'name', 'description', 'category', 'unit',
            'type',
            'purchase_price',
            'selling_price',
            'wholesale_price',
            'promo_price', 'tax_rate',
            'has_expiry', 'shelf_life_days', 'alert_days',
            'min_stock', 'max_stock',
            'reorder_point', 'reorder_quantity',
            'image', 'gallery', 'status', 'is_featured'
        ]

    def validate_code(self, value):
        if Product.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(code=value).exists():
            raise serializers.ValidationError("Ce code produit existe déjà")
        return value

    def validate_barcode(self, value):
        if value and Product.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(barcode=value).exists():
            raise serializers.ValidationError("Ce code-barres existe déjà")
        return value

    def validate_purchase_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Le prix d'achat ne peut pas être négatif")
        return value

    def validate_selling_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Le prix de vente ne peut pas être négatif")
        return value


# ============================================================
# WAREHOUSE
# ============================================================

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
        if Warehouse.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(code=value).exists():
            raise serializers.ValidationError("Ce code d'entrepôt existe déjà")
        return value


class WarehouseListSerializer(serializers.ModelSerializer):
    """Serializer léger pour les listes."""
    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'code', 'type', 'is_active']


# ============================================================
# LOT
# ============================================================

class LotListSerializer(serializers.ModelSerializer):
    """Serializer OPTIMISÉ pour la liste des lots."""
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
            'id', 'lot_number', 'batch_number',
            'product', 'product_name', 'product_code',
            'warehouse', 'warehouse_name',
            'initial_quantity', 'current_quantity',
            'available_quantity', 'reserved_quantity',
            'expiry_date', 'days_until_expiry',
            'status', 'status_display',
            'is_blocked',
            'purchase_price', 'selling_price',
            'created_at'
        ]


class LotDetailSerializer(serializers.ModelSerializer):
    """Serializer détaillé d'un lot."""
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
            'id', 'lot_number', 'batch_number', 'barcode',
            'product', 'product_name', 'product_code', 'product_has_expiry',
            'warehouse', 'warehouse_name',
            'unit', 'unit_symbol',
            'initial_quantity', 'current_quantity',
            'available_quantity', 'reserved_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date',
            'reception_date', 'last_used_date',
            'days_until_expiry', 'is_expired', 'is_expiring_soon',
            'purchase_price', 'selling_price',
            'stock_value', 'usage_rate',
            'status', 'status_display',
            'is_blocked', 'block_reason', 'blocked_date',
            'notes', 'created_at', 'created_by'
        ]
        read_only_fields = ['id', 'reception_date', 'created_at']


class LotWriteSerializer(serializers.ModelSerializer):
    """Serializer pour créer/modifier un lot."""
    class Meta:
        model = Lot
        fields = [
            'lot_number', 'batch_number', 'barcode', 'product', 'warehouse',
            'unit', 'initial_quantity', 'current_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date', 'purchase_price', 'selling_price',
            'notes'
        ]

    def validate_lot_number(self, value):
        if Lot.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(lot_number=value).exists():
            raise serializers.ValidationError("Ce numéro de lot existe déjà")
        return value

    def validate(self, data):
        if data.get('expiry_date') and data.get('manufacturing_date'):
            if data['manufacturing_date'] >= data['expiry_date']:
                raise serializers.ValidationError(
                    "La date de fabrication doit être antérieure à la date d'expiration"
                )

        if data.get('current_quantity', 0) < 0:
            raise serializers.ValidationError(
                {"current_quantity": "La quantité ne peut pas être négative"}
            )

        return data


# ============================================================
# STOCK
class StockSerializer(serializers.ModelSerializer):
    """
    ✅ Serializer OPTIMISÉ - Utilise les annotations SQL
    pour éviter les N+1 sur min_stock/max_stock.
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)

    # ✅ Ces champs utilisent les annotations SQL si disponibles
    available_quantity = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    is_over_stock = serializers.SerializerMethodField()
    min_stock = serializers.SerializerMethodField()
    max_stock = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'warehouse', 'warehouse_name',
            'quantity', 'available_quantity', 'reserved_quantity',
            'min_stock', 'max_stock',
            'min_stock_override', 'max_stock_override',
            'is_low_stock', 'is_over_stock',
            'last_update'
        ]
        read_only_fields = ['id', 'last_update']

    def _get_min_stock(self, obj):
        """✅ Utilise l'annotation SQL si dispo, sinon fallback sur product__min_stock."""
        if hasattr(obj, 'min_stock_annotated'):
            return obj.min_stock_annotated
        # Fallback : accède à product.min_stock (peut causer N+1 si pas de select_related)
        return obj.min_stock_override or obj.product.min_stock

    def _get_max_stock(self, obj):
        if hasattr(obj, 'max_stock_annotated'):
            return obj.max_stock_annotated
        return obj.max_stock_override or obj.product.max_stock

    def get_available_quantity(self, obj):
        return (obj.quantity or 0) - (obj.reserved_quantity or 0)

    def get_min_stock(self, obj):
        return self._get_min_stock(obj)

    def get_max_stock(self, obj):
        return self._get_max_stock(obj)

    def get_is_low_stock(self, obj):
        min_s = self._get_min_stock(obj)
        return (obj.quantity or 0) <= min_s

    def get_is_over_stock(self, obj):
        max_s = self._get_max_stock(obj)
        return max_s > 0 and (obj.quantity or 0) >= max_s


class StockDetailSerializer(serializers.ModelSerializer):
    """Serializer détaillé avec lots FIFO."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    available_quantity = serializers.ReadOnlyField()
    lots_fifo = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name',
            'warehouse', 'warehouse_name',
            'quantity', 'available_quantity', 'reserved_quantity',
            'min_stock', 'max_stock',
            'lots_fifo',
            'last_update'
        ]

    def get_lots_fifo(self, obj):
        lots = obj.get_lots_fifo()
        return LotListSerializer(lots[:10], many=True).data


# ============================================================
# STOCK MOVEMENT
# ============================================================

class StockMovementSerializer(serializers.ModelSerializer):
    """Serializer OPTIMISÉ pour les mouvements."""
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
            'id', 'product', 'product_name',
            'lot', 'lot_number',
            'from_warehouse', 'from_warehouse_name',
            'to_warehouse', 'to_warehouse_name',
            'movement_type', 'movement_type_display',
            'quantity', 'previous_quantity', 'new_quantity',
            'reference_type', 'reference_id', 'reference_number',
            'reason', 'notes',
            'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']


class StockMovementCreateSerializer(serializers.ModelSerializer):
    """Serializer pour créer un mouvement."""
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

        if movement_type in ['sale_out', 'transfer_out', 'adjustment_minus',
                             'expired_out', 'damaged_out', 'return_out']:
            lot = data.get('lot')
            if lot and quantity > lot.available_quantity:
                raise serializers.ValidationError({
                    "quantity": f"Stock insuffisant. Disponible: {lot.available_quantity}"
                })

        return data


# ============================================================
# EXPIRY ALERT
# ============================================================

class ExpiryAlertSerializer(serializers.ModelSerializer):
    """Serializer OPTIMISÉ pour les alertes."""
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
            'id', 'lot', 'lot_number',
            'product', 'product_name', 'product_code',
            'warehouse', 'warehouse_name',
            'severity', 'severity_display',
            'days_left', 'message',
            'is_read', 'is_processed', 'processed_at',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================
# INVENTORY
# ============================================================

class InventoryLineSerializer(serializers.ModelSerializer):
    """Serializer pour les lignes d'inventaire."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)

    class Meta:
        model = InventoryLine
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'lot', 'lot_number',
            'expected_quantity', 'actual_quantity', 'difference',
            'expected_value', 'actual_value', 'value_difference',
            'is_verified', 'notes'
        ]


class InventorySerializer(serializers.ModelSerializer):
    """Serializer OPTIMISÉ pour les inventaires."""
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
            'id', 'warehouse', 'warehouse_name',
            'name', 'description',
            'start_date', 'end_date',
            'status', 'status_display',
            'total_expected_value', 'total_actual_value', 'total_difference',
            'lines',
            'notes', 'created_at',
            'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']


class InventoryListSerializer(serializers.ModelSerializer):
    """Serializer léger pour la liste des inventaires."""
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    lines_count = serializers.SerializerMethodField()

    class Meta:
        model = Inventory
        fields = [
            'id', 'warehouse', 'warehouse_name',
            'name', 'status', 'status_display',
            'start_date', 'end_date',
            'total_expected_value', 'total_actual_value', 'total_difference',
            'lines_count', 'created_at'
        ]

    def get_lines_count(self, obj):
        if hasattr(obj, 'lines_count_annotated'):
            return obj.lines_count_annotated
        return obj.lines.count()


class InventoryCreateSerializer(serializers.ModelSerializer):
    """Serializer pour créer un inventaire."""
    class Meta:
        model = Inventory
        fields = ['warehouse', 'name', 'description', 'start_date', 'notes']

    def validate_start_date(self, value):
        if value < timezone.now():
            raise serializers.ValidationError(
                "La date de début ne peut pas être dans le passé")
        return value


class InventoryLineUpdateSerializer(serializers.ModelSerializer):
    """Serializer pour mettre à jour une ligne d'inventaire."""
    class Meta:
        model = InventoryLine
        fields = ['actual_quantity', 'notes']

    def validate_actual_quantity(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "La quantité réelle ne peut pas être négative")
        return value


# ============================================================
# TRANSFER
# ============================================================

class TransferItemSerializer(serializers.Serializer):
    """Serializer pour un article à transférer."""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)

    def validate_product_id(self, value):
        try:
            Product.objects.get(id=value, status='active')
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                "Produit introuvable ou inactif.")
        return value


class TransferRequestSerializer(serializers.Serializer):
    """Serializer pour la requête de transfert."""
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

        from_warehouse_id = data['from_warehouse_id']
        for item in data['items']:
            product_id = item['product_id']
            quantity = item['quantity']

            try:
                stock = Stock.objects.get(
                    product_id=product_id,
                    warehouse_id=from_warehouse_id
                )
            except Stock.DoesNotExist:
                raise serializers.ValidationError(
                    f"Le produit {product_id} n'a pas de stock dans l'entrepôt source."
                )

            if stock.available_quantity < quantity:
                raise serializers.ValidationError(
                    f"Stock insuffisant pour le produit {product_id}. "
                    f"Disponible : {stock.available_quantity}"
                )

        return data


class TransferSerializer(serializers.ModelSerializer):
    """Serializer pour un transfert complet."""
    from_warehouse_name = serializers.CharField(
        source='from_warehouse.name', read_only=True)
    to_warehouse_name = serializers.CharField(
        source='to_warehouse.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    items = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

    class Meta:
        model = Transfer
        fields = [
            'id', 'reference_number',
            'from_warehouse', 'from_warehouse_name',
            'to_warehouse', 'to_warehouse_name',
            'status', 'status_display',
            'reason', 'notes',
            'items',
            'created_at', 'updated_at',
            'created_by', 'created_by_name',
            'validated_at', 'validated_by'
        ]
        read_only_fields = ['id', 'reference_number',
                            'created_at', 'updated_at']

    def get_items(self, obj):
        items = obj.items.select_related(
            'product', 'source_lot', 'destination_lot').all()
        return [{
            'id': item.id,
            'product': item.product.id,
            'product_name': item.product.name,
            'product_code': item.product.code,
            'quantity': item.quantity,
            'source_lot': item.source_lot.lot_number if item.source_lot else None,
            'destination_lot': item.destination_lot.lot_number if item.destination_lot else None,
        } for item in items]


class TransferItemResponseSerializer(serializers.Serializer):
    """Serializer pour un article dans la réponse de transfert."""
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    from_warehouse = serializers.CharField()
    to_warehouse = serializers.CharField()
    lots_used = serializers.ListField(child=serializers.DictField())


class TransferResponseSerializer(serializers.Serializer):
    """Serializer pour la réponse de transfert."""
    message = serializers.CharField()
    movements = TransferItemResponseSerializer(many=True)


# ============================================================
# MANUAL STOCK ADD
# ============================================================

class ManualStockAddSerializer(serializers.Serializer):
    """Serializer pour l'ajout manuel de stock."""
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
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                {"product_id": "Produit non trouvé"})

        try:
            Warehouse.objects.get(id=data['warehouse_id'])
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                {"warehouse_id": "Entrepôt non trouvé"})

        if data.get('expiry_date') and data['expiry_date'] < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"})

        if product.has_expiry and not data.get('expiry_date'):
            raise serializers.ValidationError(
                {"expiry_date": "Ce produit a une date d'expiration obligatoire"})

        if not data.get('lot_number'):
            data['lot_number'] = (
                f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{data['product_id']}"
            )

        return data


# ============================================================
# DASHBOARD / STATS
# ============================================================

class LowStockSerializer(serializers.Serializer):
    """Serializer pour les produits en stock faible."""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    current_stock = serializers.IntegerField()
    min_stock = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    warehouse_name = serializers.CharField()
    difference = serializers.IntegerField()


class ExpiringProductsSerializer(serializers.Serializer):
    """Serializer pour les produits qui expirent bientôt."""
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
