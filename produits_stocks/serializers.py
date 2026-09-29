# apps/produits_stocks/serializers.py
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
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
        qs = Category.objects.filter(code=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
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
            'selling_price', 'wholesale_price', 'purchase_price',
            'current_stock', 'current_stock_value', 'min_stock', 'status',
            'status_display', 'has_expiry', 'image', 'is_featured'
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    """Serializer pour le détail d'un produit"""
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    current_stock = serializers.ReadOnlyField()
    current_stock_value = serializers.ReadOnlyField()
    expired_lots_count = serializers.ReadOnlyField()
    expiring_lots_count = serializers.ReadOnlyField()
    profit_margin = serializers.ReadOnlyField()
    profit_per_unit = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name', 'description',
            'category', 'category_name', 'unit', 'unit_symbol',
            'type', 'type_display',
            'purchase_price', 'selling_price', 'wholesale_price',
            'promo_price', 'tax_rate',
            'has_expiry', 'shelf_life_days', 'alert_days',
            'min_stock', 'max_stock', 'reorder_point', 'reorder_quantity',
            'image', 'gallery', 'status', 'status_display', 'is_featured',
            'current_stock', 'current_stock_value',
            'expired_lots_count', 'expiring_lots_count',
            'profit_margin', 'profit_per_unit',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProductWriteSerializer(serializers.ModelSerializer):
    """
    Serializer pour la création/modification d'un produit.
    - Code-barres : OPTIONNEL (null si vide)
    - Category / Unit : optionnels (null si vide)
    - Champs numériques optionnels : null si vide
    """
    # Code-barres : OPTIONNEL
    barcode = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None
    )

    # Relations optionnelles
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        required=False,
        allow_null=True
    )
    unit = serializers.PrimaryKeyRelatedField(
        queryset=UnitMeasure.objects.all(),
        required=False,
        allow_null=True
    )

    # Champs numériques optionnels
    wholesale_price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True
    )
    promo_price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True
    )
    shelf_life_days = serializers.IntegerField(
        required=False, allow_null=True
    )
    gallery = serializers.JSONField(required=False)

    class Meta:
        model = Product
        fields = [
            'code', 'barcode', 'name', 'description', 'category', 'unit',
            'type',
            'purchase_price', 'selling_price', 'wholesale_price',
            'promo_price', 'tax_rate',
            'has_expiry', 'shelf_life_days', 'alert_days',
            'min_stock', 'max_stock', 'reorder_point', 'reorder_quantity',
            'image', 'gallery', 'status', 'is_featured'
        ]
        extra_kwargs = {
            'code': {'required': True},
            'name': {'required': True},
            'purchase_price': {'required': True},
            'selling_price': {'required': True},
        }

    # ============ VALIDATIONS ============

    def validate_barcode(self, value):
        """Chaîne vide → None ; vérifie l'unicité si valeur fournie"""
        if not value or (isinstance(value, str) and value.strip() == ''):
            return None

        qs = Product.objects.filter(barcode=value.strip())
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError(
                "Ce code-barres est déjà utilisé par un autre produit."
            )
        return value.strip()

    def validate_code(self, value):
        """Vérifie l'unicité du code produit"""
        if not value or value.strip() == '':
            raise serializers.ValidationError(
                "Le code produit est obligatoire."
            )
        qs = Product.objects.filter(code=value.strip())
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError(
                "Ce code produit existe déjà."
            )
        return value.strip()

    def validate_purchase_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "Le prix d'achat ne peut pas être négatif."
            )
        return value

    def validate_selling_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "Le prix de vente ne peut pas être négatif."
            )
        return value

    def validate(self, data):
        """
        - Chaînes vides → None pour les champs optionnels
        - shelf_life_days → None si has_expiry=False
        """
        for field in ['barcode', 'wholesale_price', 'promo_price', 'shelf_life_days']:
            if field in data and data[field] == '':
                data[field] = None

        has_expiry = data.get(
            'has_expiry',
            getattr(self.instance, 'has_expiry', False)
        )
        if not has_expiry:
            data['shelf_life_days'] = None

        return data

    # ============ CRÉATION / MISE À JOUR ============

    @transaction.atomic
    def create(self, validated_data):
        validated_data.setdefault('barcode', None)
        validated_data.setdefault('category', None)
        validated_data.setdefault('unit', None)
        validated_data.setdefault('wholesale_price', None)
        validated_data.setdefault('promo_price', None)
        validated_data.setdefault('gallery', [])
        validated_data.setdefault('description', '')
        return Product.objects.create(**validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


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
        qs = Warehouse.objects.filter(code=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("Ce code d'entrepôt existe déjà")
        return value


# ==================== LOT ====================
class LotListSerializer(serializers.ModelSerializer):
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
    class Meta:
        model = Lot
        fields = [
            'lot_number', 'batch_number', 'barcode', 'product', 'warehouse',
            'unit', 'initial_quantity', 'current_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date', 'purchase_price', 'selling_price',
            'notes'
        ]

    def validate_lot_number(self, value):
        qs = Lot.objects.filter(lot_number=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("Ce numéro de lot existe déjà")
        return value

    def validate(self, data):
        if data.get('expiry_date') and data.get('expiry_date') < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"}
            )
        if data.get('manufacturing_date') and data.get('expiry_date'):
            if data['manufacturing_date'] >= data['expiry_date']:
                raise serializers.ValidationError(
                    "La date de fabrication doit être antérieure à la date d'expiration"
                )
        return data


# ==================== STOCK ====================
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
    created_by_name = serializers.SerializerMethodField()

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

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.email
        return None


class StockMovementCreateSerializer(serializers.ModelSerializer):
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
                {"quantity": "La quantité doit être supérieure à 0"}
            )

        if movement_type in [
            'sale_out', 'transfer_out', 'adjustment_minus',
            'expired_out', 'damaged_out'
        ]:
            lot = data.get('lot')
            if lot and quantity > lot.available_quantity:
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
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Inventory
        fields = [
            'id', 'warehouse', 'warehouse_name', 'name', 'description',
            'start_date', 'end_date', 'status', 'status_display',
            'total_expected_value', 'total_actual_value', 'total_difference',
            'lines', 'notes', 'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.email
        return None


class InventoryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inventory
        fields = ['warehouse', 'name', 'description', 'start_date', 'notes']

    def validate(self, data):
        if data.get('start_date') and data['start_date'] < timezone.now():
            raise serializers.ValidationError(
                {"start_date": "La date de début ne peut pas être dans le passé"}
            )
        return data


class InventoryLineUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLine
        fields = ['actual_quantity', 'notes']

    def validate_actual_quantity(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "La quantité réelle ne peut pas être négative"
            )
        return value


# ==================== DASHBOARD / STATS ====================
class LowStockSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    current_stock = serializers.IntegerField()
    min_stock = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    warehouse_name = serializers.CharField()
    difference = serializers.IntegerField()


class ExpiringProductsSerializer(serializers.Serializer):
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


# ==================== TRANSFER ====================
class TransferItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)

    def validate_product_id(self, value):
        try:
            Product.objects.get(id=value, status='active')
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                "Produit introuvable ou inactif."
            )
        return value


class TransferRequestSerializer(serializers.Serializer):
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
                "Entrepôt source introuvable ou inactif."
            )
        return value

    def validate_to_warehouse_id(self, value):
        try:
            Warehouse.objects.get(id=value, is_active=True)
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                "Entrepôt destination introuvable ou inactif."
            )
        return value

    def validate(self, data):
        if data.get('from_warehouse_id') == data.get('to_warehouse_id'):
            raise serializers.ValidationError(
                "Les entrepôts source et destination doivent être différents."
            )

        from_warehouse_id = data['from_warehouse_id']
        for item in data['items']:
            product_id = item['product_id']
            quantity = item['quantity']
            try:
                stock = Stock.objects.get(
                    product_id=product_id, warehouse_id=from_warehouse_id
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


class TransferItemResponseSerializer(serializers.Serializer):
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    from_warehouse = serializers.CharField()
    to_warehouse = serializers.CharField()
    lots_used = serializers.ListField(child=serializers.DictField())


class TransferResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    movements = TransferItemResponseSerializer(many=True)


# ==================== MANUAL STOCK ADD ====================
class ManualStockAddSerializer(serializers.Serializer):
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
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    selling_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(
        required=False, allow_blank=True, default="Ajout manuel"
    )

    def validate(self, data):
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                {"product_id": "Produit non trouvé"}
            )

        try:
            Warehouse.objects.get(id=data['warehouse_id'])
        except Warehouse.DoesNotExist:
            raise serializers.ValidationError(
                {"warehouse_id": "Entrepôt non trouvé"}
            )

        if data.get('expiry_date') and data['expiry_date'] < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"}
            )

        if product.has_expiry and not data.get('expiry_date'):
            raise serializers.ValidationError(
                {"expiry_date": "Ce produit a une date d'expiration obligatoire"}
            )

        if not data.get('lot_number'):
            data['lot_number'] = (
                f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{data['product_id']}"
            )
        return data
