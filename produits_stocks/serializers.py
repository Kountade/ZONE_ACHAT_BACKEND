# apps/produits_stocks/serializers.py
# ============================================================
# SERIALIZERS - Support complet des variantes
# ============================================================

from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from django.core.files.storage import default_storage
from datetime import date
from decimal import Decimal

from .models import (
    Category, UnitMeasure, Product, Warehouse, Lot, Stock,
    StockMovement, ExpiryAlert, Inventory, InventoryLine,
    Transfer, TransferItem,
    # ✅ NOUVEAU
    ProductOption, ProductOptionValue, ProductVariant,
)
from users.models import CustomUser


# ============================================================
# CATEGORY
# ============================================================
class CategorySerializer(serializers.ModelSerializer):
    full_path = serializers.ReadOnlyField()
    children_count = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'code', 'description', 'parent', 'full_path',
            'image', 'image_url', 'is_active', 'children_count', 'products_count',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def get_children_count(self, obj):
        if hasattr(obj, 'children_count_annotated'):
            return obj.children_count_annotated
        return obj.children.filter(is_active=True).count()

    def get_products_count(self, obj):
        if hasattr(obj, 'products_count_annotated'):
            return obj.products_count_annotated
        return obj.products.filter(status='active').count()

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None

    def validate_code(self, value):
        if Category.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(code=value).exists():
            raise serializers.ValidationError("Ce code existe déjà")
        return value

    def validate_image(self, value):
        if value:
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError(
                    "L'image ne doit pas dépasser 5 Mo")
            if not value.content_type.startswith('image/'):
                raise serializers.ValidationError(
                    "Le fichier doit être une image")
        return value


class CategoryListSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'code', 'image', 'image_url', 'is_active']

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None


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
# ✅ NOUVEAU : PRODUCT VARIANTS SERIALIZERS
# ============================================================
class ProductOptionValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductOptionValue
        fields = ['id', 'value', 'position']


class ProductOptionSerializer(serializers.ModelSerializer):
    values = ProductOptionValueSerializer(many=True, read_only=True)

    class Meta:
        model = ProductOption
        fields = ['id', 'name', 'position', 'values']


class ProductVariantSerializer(serializers.ModelSerializer):
    """Lecture d'une variante (liste / détail)."""
    option_values = ProductOptionValueSerializer(many=True, read_only=True)
    label = serializers.ReadOnlyField()
    image_url = serializers.SerializerMethodField()
    effective_purchase_price = serializers.ReadOnlyField()
    effective_selling_price = serializers.ReadOnlyField()
    current_stock = serializers.ReadOnlyField()

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'sku', 'barcode',
            'option_values', 'label',
            'purchase_price', 'selling_price',
            'wholesale_price', 'promo_price',
            'effective_purchase_price', 'effective_selling_price',
            'image', 'image_url',
            'is_active', 'is_default',
            'current_stock',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'current_stock']

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    """Création / mise à jour d'une variante."""
    option_value_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True, required=False
    )

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'sku', 'barcode',
            'purchase_price', 'selling_price',
            'wholesale_price', 'promo_price',
            'image', 'is_active', 'is_default',
            'option_value_ids',
        ]

    def validate_sku(self, value):
        qs = ProductVariant.objects.exclude(
            id=self.instance.id if self.instance else None
        ).filter(sku=value)
        if qs.exists():
            raise serializers.ValidationError("Ce SKU existe déjà.")
        return value

    def _set_options(self, variant, value_ids):
        if value_ids is None:
            return
        variant.option_values.set(value_ids)

    def create(self, validated_data):
        value_ids = validated_data.pop('option_value_ids', [])
        variant = ProductVariant.objects.create(**validated_data)
        self._set_options(variant, value_ids)
        return variant

    def update(self, instance, validated_data):
        value_ids = validated_data.pop('option_value_ids', None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        self._set_options(instance, value_ids)
        return instance


# ============================================================
# PRODUCT
# ============================================================
class ProductLiteSerializer(serializers.ModelSerializer):
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
            'is_featured', 'has_variants',  # ✅ NOUVEAU
            'image', 'image_url',
            'current_stock',
        ]

    def get_current_stock(self, obj):
        if hasattr(obj, 'current_stock_annotated'):
            return obj.current_stock_annotated or 0
        return obj.current_stock

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None


class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source='category.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    current_stock = serializers.SerializerMethodField()
    current_stock_value = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'barcode', 'name',
            'category', 'category_name',
            'unit', 'unit_symbol',
            'selling_price', 'wholesale_price', 'purchase_price',
            'current_stock', 'current_stock_value',
            'min_stock',
            'status', 'status_display',
            'has_expiry', 'has_variants',  # ✅ NOUVEAU
            'image', 'image_url',
            'is_featured',
        ]

    def get_current_stock(self, obj):
        if hasattr(obj, 'current_stock_annotated'):
            return obj.current_stock_annotated or 0
        return obj.current_stock

    def get_current_stock_value(self, obj):
        stock = self.get_current_stock(obj)
        return float(stock) * float(obj.purchase_price or 0)

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None


class ProductDetailSerializer(serializers.ModelSerializer):
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
    image_url = serializers.SerializerMethodField()
    gallery_urls = serializers.SerializerMethodField()

    # ✅ NOUVEAU : variantes + options
    options = ProductOptionSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

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
            'image', 'image_url', 'gallery', 'gallery_urls',
            'status', 'status_display', 'is_featured',
            'has_variants', 'options', 'variants',  # ✅ NOUVEAU
            'current_stock', 'current_stock_value',
            'expired_lots_count', 'expiring_lots_count',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

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

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        try:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        except Exception:
            return None

    def get_gallery_urls(self, obj):
        if not obj.gallery:
            return []
        request = self.context.get('request')
        urls = []
        for item in obj.gallery:
            url = item.get('url', '') if isinstance(item, dict) else str(item)
            if not url:
                continue
            if url.startswith('http'):
                urls.append(url)
            elif request:
                urls.append(request.build_absolute_uri(url))
            else:
                urls.append(url)
        return urls


class ProductWriteSerializer(serializers.ModelSerializer):
    """Création / mise à jour d'un produit (variantes gérées via actions dédiées)."""
    gallery_files = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False)
    clear_image = serializers.BooleanField(
        write_only=True, required=False, default=False)
    _clear_image = serializers.BooleanField(
        write_only=True, required=False, default=False)

    class Meta:
        model = Product
        fields = [
            'code', 'barcode', 'name', 'description', 'category', 'unit',
            'type', 'purchase_price', 'selling_price', 'wholesale_price',
            'promo_price', 'tax_rate', 'has_expiry', 'shelf_life_days',
            'alert_days', 'min_stock', 'max_stock', 'reorder_point',
            'reorder_quantity', 'image', 'gallery', 'gallery_files',
            'clear_image', '_clear_image', 'status', 'is_featured',
            'has_variants',  # ✅ NOUVEAU
        ]

    def to_internal_value(self, data):
        validated = super().to_internal_value(data)
        self._clear_image_flag = bool(
            validated.pop('clear_image', False)
            or validated.pop('_clear_image', False)
        )
        return validated

    def create(self, validated_data):
        gallery_files = validated_data.pop('gallery_files', [])
        request = self.context.get('request')
        if gallery_files:
            validated_data['gallery'] = self._build_gallery(
                gallery_files, existing=[], request=request)
        return Product.objects.create(**validated_data)

    def update(self, instance, validated_data):
        gallery_files = validated_data.pop('gallery_files', [])
        clear_image = getattr(self, '_clear_image_flag', False)

        if clear_image:
            if instance.image:
                try:
                    instance.image.delete(save=False)
                except Exception:
                    pass
            instance.image = None
            validated_data.pop('image', None)

        request = self.context.get('request')
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if gallery_files:
            instance.gallery = self._build_gallery(
                gallery_files, existing=instance.gallery or [], request=request)

        instance.save()
        return instance

    def _build_gallery(self, files, existing=None, request=None):
        gallery = list(existing or [])
        for f in files:
            try:
                path = default_storage.save(f"products/gallery/{f.name}", f)
                url = default_storage.url(path)
                if request:
                    url = request.build_absolute_uri(url)
                gallery.append({'url': url, 'name': f.name})
            except Exception:
                continue
        return gallery


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
    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'code', 'type', 'is_active']


# ============================================================
# LOT
# ============================================================
class LotListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
    variant_label = serializers.CharField(
        source='variant.label', read_only=True)  # ✅ NOUVEAU
    days_until_expiry = serializers.ReadOnlyField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    available_quantity = serializers.ReadOnlyField()

    class Meta:
        model = Lot
        fields = [
            'id', 'lot_number', 'batch_number',
            'product', 'product_name', 'product_code',
            'variant', 'variant_sku', 'variant_label',  # ✅ NOUVEAU
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
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_has_expiry = serializers.BooleanField(
        source='product.has_expiry', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    unit_symbol = serializers.CharField(source='unit.symbol', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
    variant_label = serializers.CharField(
        source='variant.label', read_only=True)  # ✅ NOUVEAU
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
            'variant', 'variant_sku', 'variant_label',  # ✅ NOUVEAU
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
        read_only_fields = ['id', 'reception_date', 'created_at', 'created_by']


class LotWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lot
        fields = [
            'lot_number', 'batch_number', 'barcode',
            'product', 'variant',  # ✅ NOUVEAU
            'warehouse', 'unit',
            'initial_quantity', 'current_quantity', 'min_quantity_alert',
            'manufacturing_date', 'expiry_date',
            'purchase_price', 'selling_price',
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
                    "La date de fabrication doit être antérieure à la date d'expiration")
        if data.get('current_quantity', 0) < 0:
            raise serializers.ValidationError(
                {"current_quantity": "La quantité ne peut pas être négative"})
        # ✅ NOUVEAU : cohérence variant ↔ product
        product = data.get('product')
        variant = data.get('variant')
        if variant and product and variant.product_id != product.id:
            raise serializers.ValidationError(
                {"variant": "La variante ne correspond pas au produit."})
        return data


# ============================================================
# STOCK
# ============================================================
class StockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
    variant_label = serializers.CharField(
        source='variant.label', read_only=True)  # ✅ NOUVEAU

    available_quantity = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    is_over_stock = serializers.SerializerMethodField()
    min_stock = serializers.SerializerMethodField()
    max_stock = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'variant', 'variant_sku', 'variant_label',  # ✅ NOUVEAU
            'warehouse', 'warehouse_name',
            'quantity', 'available_quantity', 'reserved_quantity',
            'min_stock', 'max_stock',
            'min_stock_override', 'max_stock_override',
            'is_low_stock', 'is_over_stock',
            'last_update'
        ]
        read_only_fields = ['id', 'last_update']

    def _get_min_stock(self, obj):
        if hasattr(obj, 'min_stock_annotated'):
            return obj.min_stock_annotated
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
        return (obj.quantity or 0) <= self._get_min_stock(obj)

    def get_is_over_stock(self, obj):
        max_s = self._get_max_stock(obj)
        return max_s > 0 and (obj.quantity or 0) >= max_s


class StockDetailSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
    available_quantity = serializers.ReadOnlyField()
    lots_fifo = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'product', 'product_name',
            'variant', 'variant_sku',  # ✅ NOUVEAU
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
    product_name = serializers.CharField(source='product.name', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
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
            'variant', 'variant_sku',  # ✅ NOUVEAU
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
    class Meta:
        model = StockMovement
        fields = [
            'product', 'lot', 'variant',  # ✅ NOUVEAU
            'from_warehouse', 'to_warehouse',
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
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    variant_sku = serializers.CharField(
        source='lot.variant.sku', read_only=True)  # ✅ NOUVEAU
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    severity_display = serializers.CharField(
        source='get_severity_display', read_only=True)

    class Meta:
        model = ExpiryAlert
        fields = [
            'id', 'lot', 'lot_number',
            'product', 'product_name', 'product_code',
            'variant_sku',  # ✅ NOUVEAU
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
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    variant_sku = serializers.CharField(
        source='variant.sku', read_only=True)  # ✅ NOUVEAU
    variant_label = serializers.CharField(
        source='variant.label', read_only=True)  # ✅ NOUVEAU
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    difference = serializers.ReadOnlyField()

    class Meta:
        model = InventoryLine
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'variant', 'variant_sku', 'variant_label',  # ✅ NOUVEAU
            'lot', 'lot_number',
            'expected_quantity', 'actual_quantity', 'difference',
            'expected_value', 'actual_value', 'value_difference',
            'is_verified', 'notes'
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
    class Meta:
        model = Inventory
        fields = ['warehouse', 'name', 'description', 'start_date', 'notes']


class InventoryLineUpdateSerializer(serializers.ModelSerializer):
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
    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(
        required=False, allow_null=True)  # ✅ NOUVEAU
    quantity = serializers.IntegerField(min_value=1)

    def validate_product_id(self, value):
        try:
            Product.objects.get(id=value, status='active')
        except Product.DoesNotExist:
            raise serializers.ValidationError(
                "Produit introuvable ou inactif.")
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
            variant_id = item.get('variant_id')
            quantity = item['quantity']

            try:
                qs = Stock.objects.filter(
                    product_id=product_id,
                    warehouse_id=from_warehouse_id,
                )
                if variant_id:
                    qs = qs.filter(variant_id=variant_id)
                else:
                    qs = qs.filter(variant__isnull=True)
                stock = qs.get()
            except Stock.DoesNotExist:
                v = f" (variante {variant_id})" if variant_id else ""
                raise serializers.ValidationError(
                    f"Le produit {product_id}{v} n'a pas de stock "
                    f"dans l'entrepôt source.")

            if stock.available_quantity < quantity:
                raise serializers.ValidationError(
                    f"Stock insuffisant pour le produit {product_id}. "
                    f"Disponible : {stock.available_quantity}")
        return data


class TransferSerializer(serializers.ModelSerializer):
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
            'product', 'variant', 'source_lot', 'destination_lot').all()
        return [{
            'id': item.id,
            'product': item.product.id,
            'product_name': item.product.name,
            'product_code': item.product.code,
            'variant': item.variant.id if item.variant else None,
            'variant_sku': item.variant.sku if item.variant else None,
            'quantity': item.quantity,
            'source_lot': item.source_lot.lot_number if item.source_lot else None,
            'destination_lot': item.destination_lot.lot_number if item.destination_lot else None,
        } for item in items]


class TransferItemResponseSerializer(serializers.Serializer):
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    from_warehouse = serializers.CharField()
    to_warehouse = serializers.CharField()
    lots_used = serializers.ListField(child=serializers.DictField())


class TransferResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    movements = TransferItemResponseSerializer(many=True)


# ============================================================
# MANUAL STOCK ADD
# ============================================================
class ManualStockAddSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(
        required=False, allow_null=True)  # ✅ NOUVEAU
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

        # ✅ NOUVEAU : cohérence variant ↔ product
        variant_id = data.get('variant_id')
        if variant_id:
            try:
                variant = ProductVariant.objects.get(id=variant_id)
            except ProductVariant.DoesNotExist:
                raise serializers.ValidationError(
                    {"variant_id": "Variante non trouvée"})
            if variant.product_id != product.id:
                raise serializers.ValidationError(
                    {"variant_id": "La variante n'appartient pas à ce produit"})
        elif product.has_variants:
            raise serializers.ValidationError({
                "variant_id": "Ce produit a des variantes, le champ variant_id est requis."
            })

        if data.get('expiry_date') and data['expiry_date'] < date.today():
            raise serializers.ValidationError(
                {"expiry_date": "La date d'expiration ne peut pas être dans le passé"})

        if product.has_expiry and not data.get('expiry_date'):
            raise serializers.ValidationError(
                {"expiry_date": "Ce produit a une date d'expiration obligatoire"})

        if not data.get('lot_number'):
            suffix = f"-{variant_id}" if variant_id else f"-{data['product_id']}"
            data['lot_number'] = (
                f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}{suffix}")
        return data


# ============================================================
# DASHBOARD / STATS
# ============================================================
class LowStockSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    variant_sku = serializers.CharField(required=False, allow_null=True)
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
    variant_sku = serializers.CharField(required=False, allow_null=True)
    warehouse_name = serializers.CharField()
    current_quantity = serializers.IntegerField()
    expiry_date = serializers.DateField()
    days_left = serializers.IntegerField()
    severity = serializers.CharField()
