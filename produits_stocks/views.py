# apps/produits_stocks/views.py
# ============================================================
# VIEWS - Support complet des variantes
# ============================================================

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Q, Sum, F, Count, Prefetch
from django.utils import timezone
from django.db import transaction
from datetime import date, timedelta
from decimal import Decimal
import uuid
import datetime as dt
from django.db.models.functions import Coalesce

from .models import (
    Category, UnitMeasure, Product, Warehouse, Lot, Stock,
    StockMovement, ExpiryAlert, Inventory, InventoryLine,
    Transfer, TransferItem,
    # ✅ NOUVEAU
    ProductOption, ProductOptionValue, ProductVariant,
)
from .serializers import (
    CategorySerializer, CategoryListSerializer,
    UnitMeasureSerializer,
    ProductLiteSerializer, ProductListSerializer,
    ProductDetailSerializer, ProductWriteSerializer,
    # ✅ NOUVEAU
    ProductOptionSerializer, ProductOptionValueSerializer,
    ProductVariantSerializer, ProductVariantWriteSerializer,
    WarehouseSerializer, WarehouseListSerializer,
    LotListSerializer, LotDetailSerializer, LotWriteSerializer,
    StockSerializer, StockDetailSerializer,
    StockMovementSerializer, StockMovementCreateSerializer,
    ExpiryAlertSerializer,
    InventorySerializer, InventoryListSerializer,
    InventoryCreateSerializer, InventoryLineSerializer,
    InventoryLineUpdateSerializer,
    TransferSerializer, TransferRequestSerializer,
    TransferResponseSerializer,
    ManualStockAddSerializer,
)
from users.permissions import IsAdmin, IsGestionnaire, IsMagasinier

from .pagination import (
    ProductPagination, StockPagination,
    MovementPagination, LotPagination, LargePagination
)


# ============================================================
# CATEGORY VIEWSET
# ============================================================
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LargePagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.action == 'list':
            return CategoryListSerializer
        return CategorySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = (
            Category.objects
            .select_related('parent', 'created_by')
            .annotate(
                children_count_annotated=Count(
                    'children', filter=Q(children__is_active=True), distinct=True),
                products_count_annotated=Count(
                    'products', filter=Q(products__status='active'), distinct=True),
            )
            .order_by('name')
        )
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)
        elif parent_id == 'null':
            queryset = queryset.filter(parent__isnull=True)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(code__icontains=search))
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ============================================================
# UNIT MEASURE VIEWSET
# ============================================================
class UnitMeasureViewSet(viewsets.ModelViewSet):
    queryset = UnitMeasure.objects.all()
    serializer_class = UnitMeasureSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    pagination_class = LargePagination


# ============================================================
# PRODUCT VIEWSET - avec variantes
# ============================================================
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProductPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductWriteSerializer
        return ProductDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        queryset = (
            Product.objects
            .select_related('category', 'unit', 'created_by')
            .prefetch_related(
                'options__values',
                Prefetch('variants',
                         queryset=ProductVariant.objects
                         .prefetch_related('option_values__option')),
            )
            .annotate(
                current_stock_annotated=Sum(
                    'stocks__quantity'  # ✅ MODIFIÉ : stocks (inclut variantes)
                ),
                expired_lots_annotated=Count(
                    'lots', filter=Q(lots__status='expired'), distinct=True),
                expiring_lots_annotated=Count(
                    'lots', filter=Q(lots__status='expiring'), distinct=True),
            )
            .order_by('name')
        )

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(barcode__icontains=search)
            )
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category_id=category)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        low_stock = self.request.query_params.get('low_stock')
        if low_stock == 'true':
            queryset = queryset.annotate(
                low_stock_calc=F('current_stock_annotated') - F('min_stock')
            ).filter(low_stock_calc__lte=0, min_stock__gt=0)
        has_expiry = self.request.query_params.get('has_expiry')
        if has_expiry == 'true':
            queryset = queryset.filter(has_expiry=True)
        is_featured = self.request.query_params.get('is_featured')
        if is_featured == 'true':
            queryset = queryset.filter(is_featured=True)
        has_variants = self.request.query_params.get(
            'has_variants')  # ✅ NOUVEAU
        if has_variants == 'true':
            queryset = queryset.filter(has_variants=True)
        elif has_variants == 'false':
            queryset = queryset.filter(has_variants=False)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ------------------------------------------------------------
    # ACTIONS : LOTS / EXPIRATIONS
    # ------------------------------------------------------------
    @action(detail=True, methods=['get'])
    def lots(self, request, pk=None):
        product = self.get_object()
        lots = (product.lots
                .select_related('product', 'warehouse', 'unit', 'variant')
                .order_by('expiry_date'))
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def expiring_lots(self, request, pk=None):
        product = self.get_object()
        alert_date = date.today() + timedelta(days=product.alert_days)
        lots = (product.lots
                .select_related('product', 'warehouse', 'unit', 'variant')
                .filter(
                    expiry_date__lte=alert_date,
                    expiry_date__gte=date.today(),
                    current_quantity__gt=0)
                .order_by('expiry_date'))
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        alert_date = date.today() + timedelta(days=30)
        expiring_lots_prefetch = Prefetch(
            'lots',
            queryset=(Lot.objects
                      .select_related('warehouse', 'unit', 'variant')
                      .filter(
                          expiry_date__lte=alert_date,
                          expiry_date__gte=date.today(),
                          current_quantity__gt=0)
                      .order_by('expiry_date')),
            to_attr='expiring_lots_list'
        )
        products = (Product.objects
                    .filter(has_expiry=True)
                    .select_related('category', 'unit')
                    .prefetch_related(expiring_lots_prefetch)
                    .annotate(expiring_count=Count(
                        'lots',
                        filter=(Q(lots__expiry_date__lte=alert_date) &
                                Q(lots__expiry_date__gte=date.today()) &
                                Q(lots__current_quantity__gt=0)),
                        distinct=True))
                    .filter(expiring_count__gt=0))
        result = []
        for product in products:
            lots = getattr(product, 'expiring_lots_list', [])
            total_qty = sum(lot.current_quantity for lot in lots)
            result.append({
                'product': ProductListSerializer(product, context={'request': request}).data,
                'expiring_lots': LotListSerializer(lots, many=True).data,
                'total_quantity': total_qty
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def low_stock_list(self, request):
        products = (Product.objects
                    .filter(min_stock__gt=0)
                    .select_related('category', 'unit')
                    .annotate(current_stock_annotated=Sum('stocks__quantity'))
                    .filter(
                        current_stock_annotated__lte=F('min_stock'),
                        current_stock_annotated__isnull=False))
        result = []
        for product in products:
            current_stock = product.current_stock_annotated or 0
            result.append({
                'product': ProductListSerializer(product, context={'request': request}).data,
                'current_stock': current_stock,
                'min_stock': product.min_stock,
                'difference': current_stock - product.min_stock
            })
        return Response(result)

    # ------------------------------------------------------------
    # ACTIONS : VARIANTS & OPTIONS
    # ------------------------------------------------------------
    @action(detail=True, methods=['get'])
    def variants(self, request, pk=None):
        """GET /products/{id}/variants/"""
        product = self.get_object()
        qs = product.variants.prefetch_related('option_values__option')
        serializer = ProductVariantSerializer(
            qs, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-variant')
    def add_variant(self, request, pk=None):
        """POST /products/{id}/add-variant/"""
        product = self.get_object()
        serializer = ProductVariantWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save(product=product)
        if not product.has_variants:
            product.has_variants = True
            product.save(update_fields=['has_variants'])
        return Response(
            ProductVariantSerializer(
                variant, context={'request': request}).data,
            status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'], url_path=r'variants/(?P<variant_id>\d+)')
    def update_variant(self, request, pk=None, variant_id=None):
        """PATCH /products/{id}/variants/{variant_id}/"""
        product = self.get_object()
        try:
            variant = product.variants.get(id=variant_id)
        except ProductVariant.DoesNotExist:
            return Response({"error": "Variante non trouvée"},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = ProductVariantWriteSerializer(
            variant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductVariantSerializer(
            variant, context={'request': request}).data)

    @action(detail=True, methods=['delete'],
            url_path=r'variants/(?P<variant_id>\d+)')
    def delete_variant(self, request, pk=None, variant_id=None):
        """DELETE /products/{id}/variants/{variant_id}/"""
        product = self.get_object()
        try:
            variant = product.variants.get(id=variant_id)
        except ProductVariant.DoesNotExist:
            return Response({"error": "Variante non trouvée"},
                            status=status.HTTP_404_NOT_FOUND)
        variant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def options(self, request, pk=None):
        """GET /products/{id}/options/"""
        product = self.get_object()
        serializer = ProductOptionSerializer(
            product.options.prefetch_related('values'), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-option')
    def add_option(self, request, pk=None):
        """
        POST /products/{id}/add-option/
        Body: { "name": "Taille", "values": ["S", "M", "L"] }
        """
        product = self.get_object()
        name = request.data.get('name')
        values = request.data.get('values', [])
        if not name:
            return Response({"error": "Le nom de l'option est requis."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            option, _ = ProductOption.objects.get_or_create(
                product=product, name=name)
            for i, val in enumerate(values):
                ProductOptionValue.objects.get_or_create(
                    option=option, value=val, defaults={'position': i})
            product.has_variants = True
            product.save(update_fields=['has_variants'])

        return Response(
            ProductOptionSerializer(option).data,
            status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='create-with-variants')
    def create_with_variants(self, request):
        """
        POST /products/create-with-variants/
        Body:
        {
          "product": { "code": "TSHIRT", "name": "T-Shirt", ... },
          "options": [
            {"name": "Taille", "values": ["S", "M", "L"]},
            {"name": "Couleur", "values": ["Rouge", "Bleu"]}
          ],
          "variants": [
            {"sku": "TSHIRT-S-ROUGE",
             "option_values": ["S", "Rouge"],
             "selling_price": "5000.00"},
            ...
          ]
        }
        """
        product_data = request.data.get('product')
        options_data = request.data.get('options', [])
        variants_data = request.data.get('variants', [])

        if not product_data:
            return Response({"error": "Données produit requises."},
                            status=status.HTTP_400_BAD_REQUEST)

        product_serializer = ProductWriteSerializer(
            data=product_data, context={'request': request})
        product_serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            product = product_serializer.save(
                created_by=request.user,
                has_variants=bool(options_data or variants_data)
            )

            # Créer les options et valeurs
            value_map = {}  # (option_name, value) -> ProductOptionValue
            for i, opt in enumerate(options_data):
                option = ProductOption.objects.create(
                    product=product, name=opt['name'], position=i)
                for j, val in enumerate(opt.get('values', [])):
                    pov = ProductOptionValue.objects.create(
                        option=option, value=val, position=j)
                    value_map[(opt['name'], val)] = pov

            # Créer les variantes
            created_variants = []
            for v in variants_data:
                v_serializer = ProductVariantWriteSerializer(data={
                    'sku': v['sku'],
                    'barcode': v.get('barcode'),
                    'purchase_price': v.get('purchase_price'),
                    'selling_price': v.get('selling_price'),
                    'wholesale_price': v.get('wholesale_price'),
                    'promo_price': v.get('promo_price'),
                    'is_default': v.get('is_default', False),
                })
                v_serializer.is_valid(raise_exception=True)
                variant = v_serializer.save(product=product)

                # Lier les valeurs d'options (match par valeur)
                for combo in v.get('option_values', []):
                    for (opt_name, val), pov in value_map.items():
                        if val == combo:
                            variant.option_values.add(pov)
                created_variants.append(variant)

        return Response({
            'product_id': product.id,
            'has_variants': product.has_variants,
            'options_count': product.options.count(),
            'variants_count': len(created_variants),
        }, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------
    # ACTIONS : AJOUT DE STOCK (avec variantes)
    # ------------------------------------------------------------
    @action(detail=False, methods=['post'],
            permission_classes=[permissions.IsAuthenticated, IsGestionnaire])
    def add_stock_manual(self, request):
        serializer = ManualStockAddSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])
            variant = None
            if data.get('variant_id'):
                variant = ProductVariant.objects.get(
                    id=data['variant_id'], product=product)

            with transaction.atomic():
                lot_number = data.get('lot_number')
                batch_number = data.get('batch_number', '')

                # ✅ NOUVEAU : inclure variant dans la recherche du lot
                lookup = {
                    'product': product,
                    'warehouse': warehouse,
                    'variant': variant,
                    'lot_number': lot_number,
                }
                defaults = {
                    'batch_number': batch_number,
                    'initial_quantity': data['quantity'],
                    'current_quantity': data['quantity'],
                    'reserved_quantity': 0,
                    'unit': product.unit,
                    'expiry_date': data.get('expiry_date'),
                    'manufacturing_date': data.get('manufacturing_date'),
                    'purchase_price': data.get(
                        'purchase_price',
                        variant.effective_purchase_price if variant
                        else product.purchase_price),
                    'selling_price': data.get(
                        'selling_price',
                        variant.effective_selling_price if variant
                        else product.selling_price),
                    'notes': data.get('notes', ''),
                    'status': 'good',
                    'created_by': request.user,
                }
                lot, created = Lot.objects.get_or_create(
                    **lookup, defaults=defaults)

                if not created:
                    lot.current_quantity += data['quantity']
                    lot.notes = (
                        (lot.notes or '') +
                        f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M')}] "
                        f"Ajout de {data['quantity']} unités")
                    lot.save()

                stock, _ = Stock.objects.get_or_create(
                    product=product,
                    warehouse=warehouse,
                    variant=variant,  # ✅ NOUVEAU
                )
                stock.update_quantity()

                movement = StockMovement.objects.create(
                    product=product,
                    lot=lot,
                    variant=variant,  # ✅ NOUVEAU
                    to_warehouse=warehouse,
                    movement_type='purchase_in',
                    quantity=data['quantity'],
                    previous_quantity=lot.current_quantity - data['quantity'],
                    new_quantity=lot.current_quantity,
                    reason=data.get('reason', 'Ajout manuel de stock'),
                    notes=f"Lot: {lot_number} | {data.get('notes', '')} | "
                    f"Ajouté par {request.user.username}",
                    reference_type='manual_add',
                    reference_number=(
                        f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}"),
                    created_by=request.user)

                product.update_status()

                return Response({
                    'success': True,
                    'message': f"{data['quantity']} unités ajoutées au stock de {product.name}",
                    'lot': {
                        'id': lot.id,
                        'lot_number': lot.lot_number,
                        'current_quantity': lot.current_quantity,
                        'expiry_date': lot.expiry_date,
                        'created': created,
                    },
                    'stock': {
                        'quantity': stock.quantity,
                        'available_quantity': stock.available_quantity,
                    },
                    'movement': {
                        'id': movement.id,
                        'type': movement.movement_type,
                        'quantity': movement.quantity,
                    }
                }, status=status.HTTP_201_CREATED)

        except Product.DoesNotExist:
            return Response({"error": "Produit non trouvé"},
                            status=status.HTTP_404_NOT_FOUND)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt non trouvé"},
                            status=status.HTTP_404_NOT_FOUND)
        except ProductVariant.DoesNotExist:
            return Response({"error": "Variante non trouvée"},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'],
            permission_classes=[permissions.IsAuthenticated, IsGestionnaire])
    def add_stock(self, request, pk=None):
        product = self.get_object()
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity')
        variant_id = request.data.get('variant_id')  # ✅ NOUVEAU
        lot_number = request.data.get('lot_number')
        expiry_date = request.data.get('expiry_date')
        notes = request.data.get('notes', '')

        if not warehouse_id:
            return Response({"error": "L'entrepôt est requis"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({"error": "La quantité doit être un nombre positif"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt non trouvé"},
                            status=status.HTTP_404_NOT_FOUND)

        # ✅ NOUVEAU : gestion variante
        variant = None
        if variant_id:
            try:
                variant = ProductVariant.objects.get(
                    id=variant_id, product=product)
            except ProductVariant.DoesNotExist:
                return Response({"error": "Variante non trouvée"},
                                status=status.HTTP_404_NOT_FOUND)
        elif product.has_variants:
            return Response(
                {"error": "Ce produit a des variantes, variant_id est requis."},
                status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if not lot_number:
                suffix = f"-{variant_id}" if variant_id else f"-{product.id}"
                lot_number = (
                    f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}{suffix}")

            lot = Lot.objects.create(
                product=product,
                warehouse=warehouse,
                variant=variant,  # ✅ NOUVEAU
                lot_number=lot_number,
                initial_quantity=quantity,
                current_quantity=quantity,
                unit=product.unit,
                expiry_date=expiry_date if expiry_date else None,
                purchase_price=(variant.effective_purchase_price if variant
                                else product.purchase_price),
                selling_price=(variant.effective_selling_price if variant
                               else product.selling_price),
                notes=notes,
                status='good',
                created_by=request.user)

            stock, _ = Stock.objects.get_or_create(
                product=product, warehouse=warehouse, variant=variant)
            stock.update_quantity()

            StockMovement.objects.create(
                product=product,
                lot=lot,
                variant=variant,  # ✅ NOUVEAU
                to_warehouse=warehouse,
                movement_type='purchase_in',
                quantity=quantity,
                reason='Ajout manuel de stock',
                notes=notes,
                reference_type='manual_add',
                created_by=request.user)

            product.update_status()

            return Response({
                'success': True,
                'message': f"{quantity} unités ajoutées au stock de {product.name}",
                'lot': {
                    'id': lot.id,
                    'lot_number': lot.lot_number,
                    'current_quantity': lot.current_quantity,
                },
                'stock': {
                    'quantity': stock.quantity,
                    'available_quantity': stock.available_quantity,
                }
            }, status=status.HTTP_201_CREATED)


# ============================================================
# WAREHOUSE VIEWSET
# ============================================================
class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LargePagination

    def get_serializer_class(self):
        if self.action == 'list':
            return WarehouseListSerializer
        return WarehouseSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(code__icontains=search))
        return queryset

    @action(detail=True, methods=['get'])
    def stocks(self, request, pk=None):
        warehouse = self.get_object()
        stocks = (warehouse.stocks
                  .select_related('product', 'product__category',
                                  'product__unit', 'variant')
                  .order_by('product__name'))
        serializer = StockSerializer(stocks, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def lots(self, request, pk=None):
        warehouse = self.get_object()
        lots = (warehouse.lots
                .select_related('product', 'warehouse', 'unit', 'variant')
                .order_by('expiry_date'))
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)


# ============================================================
# LOT VIEWSET
# ============================================================
class LotViewSet(viewsets.ModelViewSet):
    queryset = Lot.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsMagasinier]
    pagination_class = LotPagination

    def get_serializer_class(self):
        if self.action == 'list':
            return LotListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return LotWriteSerializer
        return LotDetailSerializer

    def get_queryset(self):
        queryset = (Lot.objects
                    .select_related('product', 'warehouse', 'unit',
                                    'variant', 'created_by')
                    .order_by('expiry_date', 'created_at'))

        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        variant_id = self.request.query_params.get('variant')  # ✅ NOUVEAU
        if variant_id:
            queryset = queryset.filter(variant_id=variant_id)
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        expiring = self.request.query_params.get('expiring')
        if expiring == 'true':
            alert_date = date.today() + timedelta(days=30)
            queryset = queryset.filter(
                expiry_date__lte=alert_date,
                expiry_date__gte=date.today(),
                current_quantity__gt=0)
        expired = self.request.query_params.get('expired')
        if expired == 'true':
            queryset = queryset.filter(expiry_date__lt=date.today())
        available = self.request.query_params.get('available')
        if available == 'true':
            queryset = queryset.filter(
                current_quantity__gt=0, is_blocked=False).exclude(status='expired')
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(lot_number__icontains=search) |
                Q(batch_number__icontains=search) |
                Q(product__name__icontains=search) |
                Q(product__code__icontains=search) |
                Q(variant__sku__icontains=search))
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def reserve(self, request, pk=None):
        lot = self.get_object()
        quantity = request.data.get('quantity', 0)
        if quantity <= 0:
            return Response({"error": "La quantité doit être supérieure à 0"},
                            status=status.HTTP_400_BAD_REQUEST)
        if lot.reserve(quantity):
            return Response({
                "message": f"{quantity} unités réservées",
                "available_quantity": lot.available_quantity})
        return Response({"error": "Stock insuffisant"},
                        status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def consume(self, request, pk=None):
        lot = self.get_object()
        quantity = request.data.get('quantity', 0)
        reason = request.data.get('reason', '')
        if quantity <= 0:
            return Response({"error": "La quantité doit être supérieure à 0"},
                            status=status.HTTP_400_BAD_REQUEST)
        if lot.consume(quantity):
            StockMovement.objects.create(
                product=lot.product,
                lot=lot,
                variant=lot.variant,  # ✅ NOUVEAU
                from_warehouse=lot.warehouse,
                movement_type='sale_out',
                quantity=quantity,
                reason=reason,
                created_by=request.user)
            return Response({
                "message": f"{quantity} unités consommées",
                "current_quantity": lot.current_quantity})
        return Response({"error": "Stock insuffisant"},
                        status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        lot = self.get_object()
        reason = request.data.get('reason', '')
        lot.block(reason)
        return Response({"message": "Lot bloqué", "status": lot.status})

    @action(detail=True, methods=['post'])
    def unblock(self, request, pk=None):
        lot = self.get_object()
        lot.unblock()
        return Response({"message": "Lot débloqué", "status": lot.status})


# ============================================================
# STOCK VIEWSET
# ============================================================
class StockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StockPagination

    def get_queryset(self):
        queryset = (Stock.objects
                    .select_related('product', 'product__category',
                                    'product__unit', 'warehouse', 'variant')
                    .annotate(
                        min_stock_annotated=Coalesce(
                            'min_stock_override', 'product__min_stock'),
                        max_stock_annotated=Coalesce(
                            'max_stock_override', 'product__max_stock'),
                    )
                    .order_by('product__name'))

        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        variant_id = self.request.query_params.get('variant')  # ✅ NOUVEAU
        if variant_id:
            queryset = queryset.filter(variant_id=variant_id)
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        low_stock = self.request.query_params.get('low_stock')
        if low_stock == 'true':
            queryset = queryset.filter(quantity__lte=F('min_stock_annotated'))
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(product__name__icontains=search) |
                Q(product__code__icontains=search) |
                Q(variant__sku__icontains=search))
        return queryset

    @action(detail=True, methods=['get'])
    def detail(self, request, pk=None):
        stock = self.get_object()
        serializer = StockDetailSerializer(stock)
        return Response(serializer.data)


# ============================================================
# STOCK MOVEMENT VIEWSET
# ============================================================
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MovementPagination

    def get_queryset(self):
        queryset = (StockMovement.objects
                    .select_related(
                        'product', 'product__category', 'product__unit',
                        'lot', 'lot__warehouse',
                        'variant',
                        'from_warehouse', 'to_warehouse', 'created_by')
                    .order_by('-created_at'))

        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        variant_id = self.request.query_params.get('variant')  # ✅ NOUVEAU
        if variant_id:
            queryset = queryset.filter(variant_id=variant_id)
        lot_id = self.request.query_params.get('lot')
        if lot_id:
            queryset = queryset.filter(lot_id=lot_id)
        movement_type = self.request.query_params.get('type')
        if movement_type:
            type_list = [t.strip()
                         for t in movement_type.split(',') if t.strip()]
            if type_list:
                queryset = queryset.filter(movement_type__in=type_list)
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(
                Q(from_warehouse_id=warehouse_id) |
                Q(to_warehouse_id=warehouse_id))
        reference_type = self.request.query_params.get('reference_type')
        if reference_type:
            queryset = queryset.filter(reference_type=reference_type)
        reference_id = self.request.query_params.get('reference_id')
        if reference_id:
            queryset = queryset.filter(reference_id=reference_id)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            try:
                date_start = dt.datetime.strptime(date_from, '%Y-%m-%d')
                queryset = queryset.filter(created_at__gte=date_start)
            except ValueError:
                pass
        date_to = self.request.query_params.get('date_to')
        if date_to:
            try:
                date_end = dt.datetime.strptime(date_to, '%Y-%m-%d')
                date_end = date_end.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(created_at__lte=date_end)
            except ValueError:
                pass
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(product__name__icontains=search) |
                Q(product__code__icontains=search) |
                Q(variant__sku__icontains=search) |
                Q(lot__lot_number__icontains=search) |
                Q(lot__batch_number__icontains=search) |
                Q(reference_number__icontains=search) |
                Q(reason__icontains=search) |
                Q(notes__icontains=search) |
                Q(created_by__first_name__icontains=search) |
                Q(created_by__last_name__icontains=search))
        return queryset

    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = self.get_queryset()
        total = queryset.count()
        by_type = dict(
            queryset.values('movement_type')
            .annotate(count=Count('id'))
            .values_list('movement_type', 'count'))

        entrees_types = ['purchase_in', 'transfer_in',
                         'return_in', 'adjustment_plus']
        sorties_types = ['sale_out', 'transfer_out', 'expired_out',
                         'damaged_out', 'return_out', 'adjustment_minus']

        total_entrees = sum(by_type.get(t, 0) for t in entrees_types)
        total_sorties = sum(by_type.get(t, 0) for t in sorties_types)
        quantities = queryset.aggregate(
            total_entrees_qty=Sum('quantity',
                                  filter=Q(movement_type__in=entrees_types)),
            total_sorties_qty=Sum('quantity',
                                  filter=Q(movement_type__in=sorties_types)),
        )
        return Response({
            'total': total,
            'by_type': by_type,
            'entrees': total_entrees,
            'sorties': total_sorties,
            'entrees_quantity': quantities['total_entrees_qty'] or 0,
            'sorties_quantity': quantities['total_sorties_qty'] or 0,
            'ajustements': (by_type.get('adjustment_plus', 0) +
                            by_type.get('adjustment_minus', 0)),
        })

    @action(detail=False, methods=['get'], url_path='export')
    def export_csv(self, request):
        import csv
        from django.http import HttpResponse

        queryset = self.get_queryset()[:10000]
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f'attachment; filename="mouvements_{date.today().isoformat()}.csv"')
        response.write('\ufeff')

        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'Date', 'Produit', 'Code produit', 'SKU Variante', 'N° Lot',
            'Type', 'Quantité', 'Entrepôt source', 'Entrepôt destination',
            'Référence', 'Raison', 'Créé par'])

        for m in queryset:
            writer.writerow([
                m.created_at.strftime(
                    '%Y-%m-%d %H:%M') if m.created_at else '',
                m.product.name if m.product else '',
                m.product.code if m.product else '',
                m.variant.sku if m.variant else '',
                m.lot.lot_number if m.lot else '',
                m.get_movement_type_display() if hasattr(
                    m, 'get_movement_type_display') else m.movement_type,
                m.quantity or 0,
                m.from_warehouse.name if m.from_warehouse else '',
                m.to_warehouse.name if m.to_warehouse else '',
                m.reference_number or '',
                m.reason or '',
                m.created_by.get_full_name() if m.created_by else '',
            ])
        return response


# ============================================================
# EXPIRY ALERT VIEWSET
# ============================================================
class ExpiryAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExpiryAlert.objects.all()
    serializer_class = ExpiryAlertSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = MovementPagination

    def get_queryset(self):
        queryset = (ExpiryAlert.objects
                    .select_related('lot', 'lot__variant', 'product',
                                    'warehouse', 'processed_by')
                    .order_by('days_left', 'created_at'))
        unprocessed = self.request.query_params.get('unprocessed')
        if unprocessed == 'true':
            queryset = queryset.filter(is_processed=False)
        unread = self.request.query_params.get('unread')
        if unread == 'true':
            queryset = queryset.filter(is_read=False)
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        alert = self.get_object()
        alert.mark_as_read()
        return Response({"message": "Alerte marquée comme lue"})

    @action(detail=True, methods=['post'])
    def mark_processed(self, request, pk=None):
        alert = self.get_object()
        alert.mark_as_processed(request.user)
        return Response({"message": "Alerte marquée comme traitée"})


# ============================================================
# INVENTORY LINE VIEWSET
# ============================================================
class InventoryLineViewSet(viewsets.ModelViewSet):
    queryset = InventoryLine.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_queryset(self):
        queryset = (InventoryLine.objects
                    .select_related('inventory', 'product',
                                    'variant', 'lot', 'verified_by'))
        inventory_id = self.request.query_params.get('inventory')
        if inventory_id:
            queryset = queryset.filter(inventory_id=inventory_id)
        return queryset

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return InventoryLineUpdateSerializer
        return InventoryLineSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = InventoryLineUpdateSerializer(
            instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        inventory = instance.inventory
        inventory.total_expected_value = inventory.lines.aggregate(
            total=Sum('expected_value'))['total'] or 0
        inventory.total_actual_value = inventory.lines.aggregate(
            total=Sum('actual_value'))['total'] or 0
        inventory.total_difference = (
            inventory.total_actual_value - inventory.total_expected_value)
        inventory.save(update_fields=[
            'total_expected_value', 'total_actual_value', 'total_difference'])
        return Response(InventoryLineSerializer(instance).data)

    @action(detail=True, methods=['post'], url_path='apply-adjustment')
    def apply_adjustment(self, request, pk=None):
        line = self.get_object()
        if line.is_verified:
            return Response({"error": "Cette ligne a déjà été ajustée"},
                            status=status.HTTP_400_BAD_REQUEST)
        if line.actual_quantity is None:
            return Response({"error": "Veuillez saisir la quantité réelle avant d'ajuster"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                line.apply_adjustment(request.user)
            return Response({
                "status": "success",
                "message": f"Ajustement appliqué pour {line.product.name}",
                "difference": line.difference,
            })
        except Exception as e:
            return Response({"error": str(e)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# INVENTORY VIEWSET
# ============================================================
class InventoryViewSet(viewsets.ModelViewSet):
    queryset = Inventory.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]
    pagination_class = LargePagination

    def get_serializer_class(self):
        if self.action == 'create':
            return InventoryCreateSerializer
        elif self.action == 'list':
            return InventoryListSerializer
        return InventorySerializer

    def get_queryset(self):
        queryset = (Inventory.objects
                    .select_related('warehouse', 'created_by', 'verified_by')
                    .annotate(lines_count_annotated=Count('lines', distinct=True))
                    .order_by('-created_at'))
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        inventory = self.get_object()
        inventory.start()

        products = Product.objects.filter(
            status='active').select_related('unit').prefetch_related('variants')

        stocks_qs = Stock.objects.filter(
            warehouse=inventory.warehouse).select_related('variant')
        # Map (product_id, variant_id) -> stock
        stocks_map = {(s.product_id, s.variant_id): s for s in stocks_qs}

        lines_to_create = []
        for product in products:
            if product.has_variants:
                for variant in product.variants.filter(is_active=True):
                    stock = stocks_map.get((product.id, variant.id))
                    expected = stock.quantity if stock else 0
                    lines_to_create.append(InventoryLine(
                        inventory=inventory,
                        product=product,
                        variant=variant,
                        expected_quantity=expected))
            else:
                stock = stocks_map.get((product.id, None))
                expected = stock.quantity if stock else 0
                lines_to_create.append(InventoryLine(
                    inventory=inventory,
                    product=product,
                    variant=None,
                    expected_quantity=expected))

        InventoryLine.objects.bulk_create(
            lines_to_create, ignore_conflicts=True, batch_size=500)

        return Response({
            "message": f"Inventaire démarré avec {len(lines_to_create)} lignes",
            "status": inventory.status})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        inventory = self.get_object()
        inventory.complete()
        return Response({"message": "Inventaire terminé",
                         "status": inventory.status})

    @action(detail=True, methods=['get'])
    def lines(self, request, pk=None):
        inventory = self.get_object()
        lines = (inventory.lines
                 .select_related('product', 'product__category',
                                 'variant', 'lot', 'verified_by'))
        serializer = InventoryLineSerializer(lines, many=True)
        return Response(serializer.data)


# ============================================================
# TRANSFER VIEWSET
# ============================================================
class TransferViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def list(self, request):
        transfers = (Transfer.objects
                     .select_related('from_warehouse', 'to_warehouse',
                                     'created_by', 'validated_by')
                     .prefetch_related('items__product', 'items__variant',
                                       'items__source_lot',
                                       'items__destination_lot')
                     .order_by('-created_at')[:100])
        serializer = TransferSerializer(transfers, many=True)
        return Response(serializer.data)

    def create(self, request):
        serializer = TransferRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors,
                            status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        from_warehouse_id = data['from_warehouse_id']
        to_warehouse_id = data['to_warehouse_id']
        items = data['items']
        reason = data.get('reason', '')
        notes = data.get('notes', '')

        try:
            from_warehouse = Warehouse.objects.get(id=from_warehouse_id)
            to_warehouse = Warehouse.objects.get(id=to_warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt source ou destination introuvable."},
                            status=status.HTTP_404_NOT_FOUND)

        movements_created = []
        reference_number = (
            f"TRANSF-{timezone.now().strftime('%Y%m%d%H%M%S')}")

        with transaction.atomic():
            transfer = Transfer.objects.create(
                from_warehouse=from_warehouse,
                to_warehouse=to_warehouse,
                reference_number=reference_number,
                status='completed',
                reason=reason, notes=notes,
                created_by=request.user,
                validated_at=timezone.now(),
                validated_by=request.user)

            for item in items:
                product_id = item['product_id']
                variant_id = item.get('variant_id')
                quantity = item['quantity']

                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    return Response(
                        {"error": f"Produit {product_id} introuvable."},
                        status=status.HTTP_404_NOT_FOUND)

                variant = None
                if variant_id:
                    try:
                        variant = ProductVariant.objects.get(
                            id=variant_id, product=product)
                    except ProductVariant.DoesNotExist:
                        return Response(
                            {"error": f"Variante {variant_id} introuvable."},
                            status=status.HTTP_404_NOT_FOUND)

                # Récupérer stock source
                qs = Stock.objects.filter(
                    product=product, warehouse=from_warehouse)
                if variant:
                    qs = qs.filter(variant=variant)
                else:
                    qs = qs.filter(variant__isnull=True)
                try:
                    stock_source = qs.get()
                except Stock.DoesNotExist:
                    return Response(
                        {"error": f"Pas de stock source pour {product.name}."},
                        status=status.HTTP_400_BAD_REQUEST)

                success, lots_used = stock_source.consume_stock(quantity)
                if not success:
                    return Response(
                        {"error": f"Impossible de consommer le stock pour {product.name}."},
                        status=status.HTTP_400_BAD_REQUEST)

                for lot_data in lots_used:
                    lot = lot_data['lot']
                    qty = lot_data['quantity']

                    StockMovement.objects.create(
                        product=product,
                        lot=lot,
                        variant=variant,
                        from_warehouse=from_warehouse,
                        to_warehouse=to_warehouse,
                        movement_type='transfer_out',
                        quantity=qty,
                        reason=reason, notes=notes,
                        created_by=request.user,
                        reference_number=reference_number)

                    unique_suffix = uuid.uuid4().hex[:8]
                    new_lot_number = f"{lot.lot_number}-TRANSF-{unique_suffix}"

                    new_lot = Lot.objects.create(
                        product=product,
                        warehouse=to_warehouse,
                        variant=variant,
                        lot_number=new_lot_number,
                        batch_number=lot.batch_number,
                        barcode=lot.barcode,
                        initial_quantity=qty,
                        current_quantity=qty,
                        reserved_quantity=0,
                        unit=lot.unit,
                        manufacturing_date=lot.manufacturing_date,
                        expiry_date=lot.expiry_date,
                        purchase_price=lot.purchase_price,
                        selling_price=lot.selling_price,
                        status='good',
                        created_by=request.user,
                        notes=f"Transfert depuis {from_warehouse.name} - {notes}")

                    StockMovement.objects.create(
                        product=product,
                        lot=new_lot,
                        variant=variant,
                        from_warehouse=from_warehouse,
                        to_warehouse=to_warehouse,
                        movement_type='transfer_in',
                        quantity=qty,
                        reason=reason, notes=notes,
                        created_by=request.user,
                        reference_number=reference_number)

                    TransferItem.objects.create(
                        transfer=transfer,
                        product=product,
                        variant=variant,
                        quantity=qty,
                        source_lot=lot,
                        destination_lot=new_lot)

                stock_source.update_quantity()
                stock_dest, _ = Stock.objects.get_or_create(
                    product=product, warehouse=to_warehouse,
                    variant=variant)
                stock_dest.update_quantity()

                movements_created.append({
                    "product": product.name,
                    "variant": variant.sku if variant else None,
                    "quantity": quantity,
                    "from_warehouse": from_warehouse.name,
                    "to_warehouse": to_warehouse.name,
                    "lots_used": [
                        {"lot": l['lot'].lot_number, "qty": l['quantity']}
                        for l in lots_used]
                })

        return Response({
            "message": "Transfert effectué avec succès",
            "transfer_id": transfer.id,
            "reference_number": reference_number,
            "movements": movements_created
        }, status=status.HTTP_201_CREATED)


# ============================================================
# DASHBOARD STATS VIEWSET
# ============================================================
class DashboardStatsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        total_products = Product.objects.filter(status='active').count()
        products_with_stock = (Product.objects
                               .filter(status='active', min_stock__gt=0)
                               .annotate(current_stock_annotated=Sum('stocks__quantity')))
        low_stock_products = 0
        out_of_stock_products = 0
        for product in products_with_stock:
            stock = product.current_stock_annotated or 0
            if stock <= 0:
                out_of_stock_products += 1
            elif stock <= product.min_stock:
                low_stock_products += 1

        expiring_lots = Lot.objects.filter(
            expiry_date__lte=date.today() + timedelta(days=30),
            expiry_date__gte=date.today(),
            current_quantity__gt=0).count()
        expired_lots = Lot.objects.filter(
            expiry_date__lt=date.today(),
            current_quantity__gt=0).count()
        total_warehouses = Warehouse.objects.filter(is_active=True).count()
        unprocessed_alerts = ExpiryAlert.objects.filter(
            is_processed=False).count()

        return Response({
            'products': {
                'total': total_products,
                'low_stock': low_stock_products,
                'out_of_stock': out_of_stock_products,
            },
            'lots': {
                'expiring_soon': expiring_lots,
                'expired': expired_lots,
            },
            'warehouses': {'total': total_warehouses},
            'alerts': {'unprocessed': unprocessed_alerts},
        })

    @action(detail=False, methods=['get'])
    def expiring_products(self, request):
        result = []
        alert_date = date.today() + timedelta(days=30)
        lots = (Lot.objects
                .select_related('product', 'warehouse', 'variant')
                .filter(
                    expiry_date__lte=alert_date,
                    expiry_date__gte=date.today(),
                    current_quantity__gt=0)
                .order_by('expiry_date'))
        for lot in lots:
            days_left = (lot.expiry_date - date.today()).days
            severity = 'danger' if days_left <= 7 else (
                'warning' if days_left <= 15 else 'info')
            result.append({
                'lot_id': lot.id,
                'lot_number': lot.lot_number,
                'product_id': lot.product.id,
                'product_name': lot.product.name,
                'product_code': lot.product.code,
                'variant_sku': lot.variant.sku if lot.variant else None,
                'warehouse_name': lot.warehouse.name if lot.warehouse else 'N/A',
                'current_quantity': lot.current_quantity,
                'expiry_date': lot.expiry_date,
                'days_left': days_left,
                'severity': severity,
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        result = []
        stocks = (Stock.objects
                  .filter(quantity__lte=F('product__min_stock'))
                  .select_related('product', 'warehouse', 'variant'))
        for stock in stocks:
            result.append({
                'product_id': stock.product.id,
                'product_name': stock.product.name,
                'product_code': stock.product.code,
                'variant_sku': stock.variant.sku if stock.variant else None,
                'current_stock': stock.quantity,
                'min_stock': stock.min_stock,
                'warehouse_id': stock.warehouse.id,
                'warehouse_name': stock.warehouse.name,
                'difference': stock.quantity - stock.min_stock,
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def stock_value(self, request):
        total_value = Decimal('0')
        lots = (Lot.objects
                .filter(current_quantity__gt=0)
                .exclude(status='expired')
                .values('current_quantity', 'purchase_price'))
        for lot in lots:
            total_value += (Decimal(str(lot['current_quantity'])) *
                            Decimal(str(lot['purchase_price'])))
        return Response({
            'total_stock_value': float(total_value),
            'currency': 'XOF',
        })
