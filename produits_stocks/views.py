# apps/produits_stocks/views.py
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q, Sum, F
from django.utils import timezone
from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Category, UnitMeasure, Product, Warehouse, Lot, Stock,
    StockMovement, ExpiryAlert, Inventory, InventoryLine,
)
from .serializers import (
    CategorySerializer, UnitMeasureSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductWriteSerializer,
    WarehouseSerializer,
    LotListSerializer, LotDetailSerializer, LotWriteSerializer,
    StockSerializer, StockDetailSerializer,
    StockMovementSerializer, StockMovementCreateSerializer,
    ExpiryAlertSerializer,
    InventorySerializer, InventoryCreateSerializer, InventoryLineSerializer,
    InventoryLineUpdateSerializer,
    LowStockSerializer, ExpiringProductsSerializer,
    ManualStockAddSerializer,
    TransferRequestSerializer, TransferResponseSerializer,
)
from users.permissions import IsAdmin, IsGestionnaire, IsMagasinier
from users.models import CustomUser


# ==================== CATEGORY ====================
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)
        elif parent_id == 'null':
            queryset = queryset.filter(parent__isnull=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ==================== UNIT MEASURE ====================
class UnitMeasureViewSet(viewsets.ModelViewSet):
    queryset = UnitMeasure.objects.all()
    serializer_class = UnitMeasureSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]


# ==================== PRODUCT ====================
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductWriteSerializer
        return ProductDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related('category', 'unit')

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
            queryset = queryset.filter(min_stock__gt=0)
            product_ids = [
                p.id for p in queryset
                if p.current_stock <= p.min_stock
            ]
            queryset = queryset.filter(id__in=product_ids)

        has_expiry = self.request.query_params.get('has_expiry')
        if has_expiry == 'true':
            queryset = queryset.filter(has_expiry=True)

        is_featured = self.request.query_params.get('is_featured')
        if is_featured == 'true':
            queryset = queryset.filter(is_featured=True)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ---------- CREATE avec réponse détaillée ----------
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        detail = ProductDetailSerializer(serializer.instance)
        return Response(detail.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_update(serializer)
        detail = ProductDetailSerializer(serializer.instance)
        return Response(detail.data)

    # ---------- ACTIONS ----------
    @action(detail=True, methods=['get'])
    def lots(self, request, pk=None):
        product = self.get_object()
        lots = product.lots.all().order_by('expiry_date')
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def expiring_lots(self, request, pk=None):
        product = self.get_object()
        alert_date = date.today() + timedelta(days=product.alert_days)
        lots = product.lots.filter(
            expiry_date__lte=alert_date,
            expiry_date__gte=date.today(),
            current_quantity__gt=0
        ).order_by('expiry_date')
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        products = Product.objects.filter(has_expiry=True)
        result = []
        for product in products:
            alert_date = date.today() + timedelta(days=product.alert_days)
            expiring_lots = product.lots.filter(
                expiry_date__lte=alert_date,
                expiry_date__gte=date.today(),
                current_quantity__gt=0
            )
            if expiring_lots.exists():
                result.append({
                    'product': ProductListSerializer(product).data,
                    'expiring_lots': LotListSerializer(expiring_lots, many=True).data,
                    'total_quantity': expiring_lots.aggregate(
                        total=Sum('current_quantity')
                    )['total']
                })
        return Response(result)

    @action(detail=False, methods=['get'])
    def low_stock_list(self, request):
        products = Product.objects.filter(min_stock__gt=0)
        result = []
        for product in products:
            current_stock = product.current_stock
            if current_stock <= product.min_stock:
                result.append({
                    'product': ProductListSerializer(product).data,
                    'current_stock': current_stock,
                    'min_stock': product.min_stock,
                    'difference': current_stock - product.min_stock
                })
        return Response(result)

    @action(
        detail=False, methods=['post'],
        permission_classes=[permissions.IsAuthenticated, IsGestionnaire]
    )
    def add_stock_manual(self, request):
        serializer = ManualStockAddSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            product = Product.objects.get(id=data['product_id'])
            warehouse = Warehouse.objects.get(id=data['warehouse_id'])

            with transaction.atomic():
                lot_number = data.get('lot_number')
                batch_number = data.get('batch_number', '')

                lot, created = Lot.objects.get_or_create(
                    product=product,
                    warehouse=warehouse,
                    lot_number=lot_number,
                    defaults={
                        'batch_number': batch_number,
                        'initial_quantity': data['quantity'],
                        'current_quantity': data['quantity'],
                        'reserved_quantity': 0,
                        'unit': product.unit,
                        'expiry_date': data.get('expiry_date'),
                        'manufacturing_date': data.get('manufacturing_date'),
                        'purchase_price': data.get('purchase_price', product.purchase_price),
                        'selling_price': data.get('selling_price', product.selling_price),
                        'notes': data.get('notes', ''),
                        'status': 'good',
                        'created_by': request.user,
                    }
                )

                if not created:
                    lot.current_quantity += data['quantity']
                    lot.notes = (lot.notes or '') + (
                        f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M')}] "
                        f"Ajout de {data['quantity']} unités"
                    )
                    lot.save()

                stock, _ = Stock.objects.get_or_create(
                    product=product, warehouse=warehouse
                )
                stock.update_quantity()

                movement = StockMovement.objects.create(
                    product=product,
                    lot=lot,
                    to_warehouse=warehouse,
                    movement_type='purchase_in',
                    quantity=data['quantity'],
                    reason=data.get('reason', 'Ajout manuel de stock'),
                    notes=data.get('notes', ''),
                    reference_type='manual_add',
                    reference_number=f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                    created_by=request.user
                )

                product.update_status()

                return Response({
                    'success': True,
                    'message': f"{data['quantity']} unités ajoutées à {product.name}",
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
            return Response({"error": "Produit non trouvé"}, status=404)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt non trouvé"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(
        detail=True, methods=['post'],
        permission_classes=[permissions.IsAuthenticated, IsGestionnaire]
    )
    def add_stock(self, request, pk=None):
        product = self.get_object()
        warehouse_id = request.data.get('warehouse_id')
        quantity = request.data.get('quantity')
        lot_number = request.data.get('lot_number')
        expiry_date = request.data.get('expiry_date')
        notes = request.data.get('notes', '')

        if not warehouse_id:
            return Response({"error": "L'entrepôt est requis"}, status=400)

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return Response({"error": "Quantité invalide"}, status=400)

        if quantity <= 0:
            return Response({"error": "Quantité > 0 requise"}, status=400)

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt non trouvé"}, status=404)

        with transaction.atomic():
            if not lot_number:
                lot_number = f"MAN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{product.id}"

            lot = Lot.objects.create(
                product=product,
                warehouse=warehouse,
                lot_number=lot_number,
                initial_quantity=quantity,
                current_quantity=quantity,
                reserved_quantity=0,
                unit=product.unit,
                expiry_date=expiry_date or None,
                purchase_price=product.purchase_price,
                selling_price=product.selling_price,
                notes=notes,
                status='good',
                created_by=request.user
            )

            stock, _ = Stock.objects.get_or_create(
                product=product, warehouse=warehouse
            )
            stock.update_quantity()

            StockMovement.objects.create(
                product=product,
                lot=lot,
                to_warehouse=warehouse,
                movement_type='purchase_in',
                quantity=quantity,
                reason='Ajout manuel de stock',
                notes=notes,
                reference_type='manual_add',
                created_by=request.user
            )

            product.update_status()

            return Response({
                'success': True,
                'message': f"{quantity} unités ajoutées à {product.name}",
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


# ==================== WAREHOUSE ====================
class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        active = self.request.query_params.get('active')
        if active == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset

    @action(detail=True, methods=['get'])
    def stocks(self, request, pk=None):
        warehouse = self.get_object()
        stocks = warehouse.stocks.all().select_related('product')
        return Response(StockSerializer(stocks, many=True).data)

    @action(detail=True, methods=['get'])
    def lots(self, request, pk=None):
        warehouse = self.get_object()
        lots = warehouse.lots.all().select_related('product').order_by('expiry_date')
        return Response(LotListSerializer(lots, many=True).data)


# ==================== LOT ====================
class LotViewSet(viewsets.ModelViewSet):
    queryset = Lot.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsMagasinier]

    def get_serializer_class(self):
        if self.action == 'list':
            return LotListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return LotWriteSerializer
        return LotDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
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
                current_quantity__gt=0
            )
        expired = self.request.query_params.get('expired')
        if expired == 'true':
            queryset = queryset.filter(expiry_date__lt=date.today())
        available = self.request.query_params.get('available')
        if available == 'true':
            queryset = queryset.filter(
                current_quantity__gt=0, is_blocked=False
            ).exclude(status='expired')
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def reserve(self, request, pk=None):
        lot = self.get_object()
        quantity = request.data.get('quantity', 0)
        if quantity <= 0:
            return Response({"error": "Quantité > 0 requise"}, status=400)
        if lot.reserve(quantity):
            return Response({
                "message": f"{quantity} unités réservées",
                "available_quantity": lot.available_quantity
            })
        return Response({"error": "Stock insuffisant"}, status=400)

    @action(detail=True, methods=['post'])
    def consume(self, request, pk=None):
        lot = self.get_object()
        quantity = request.data.get('quantity', 0)
        reason = request.data.get('reason', '')
        if quantity <= 0:
            return Response({"error": "Quantité > 0 requise"}, status=400)
        if lot.consume(quantity):
            StockMovement.objects.create(
                product=lot.product,
                lot=lot,
                from_warehouse=lot.warehouse,
                movement_type='sale_out',
                quantity=quantity,
                reason=reason,
                created_by=request.user
            )
            return Response({
                "message": f"{quantity} unités consommées",
                "current_quantity": lot.current_quantity
            })
        return Response({"error": "Stock insuffisant"}, status=400)

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


# ==================== STOCK ====================
class StockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        low_stock = self.request.query_params.get('low_stock')
        if low_stock == 'true':
            queryset = queryset.filter(quantity__lte=F('product__min_stock'))
        return queryset

    @action(detail=True, methods=['get'])
    def detail(self, request, pk=None):
        stock = self.get_object()
        return Response(StockDetailSerializer(stock).data)


# ==================== STOCK MOVEMENT ====================
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        lot_id = self.request.query_params.get('lot')
        if lot_id:
            queryset = queryset.filter(lot_id=lot_id)
        movement_type = self.request.query_params.get('type')
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


# ==================== EXPIRY ALERT ====================
class ExpiryAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExpiryAlert.objects.all()
    serializer_class = ExpiryAlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
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


# ==================== INVENTORY LINE ====================
class InventoryLineViewSet(viewsets.ModelViewSet):
    queryset = InventoryLine.objects.all()
    serializer_class = InventoryLineSerializer
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_queryset(self):
        queryset = super().get_queryset()
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
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        inventory = instance.inventory
        inventory.total_expected_value = inventory.lines.aggregate(
            total=Sum('expected_value')
        )['total'] or 0
        inventory.total_actual_value = inventory.lines.aggregate(
            total=Sum('actual_value')
        )['total'] or 0
        inventory.total_difference = (
            inventory.total_actual_value - inventory.total_expected_value
        )
        inventory.save(update_fields=[
            'total_expected_value', 'total_actual_value', 'total_difference'
        ])
        return Response(InventoryLineSerializer(instance).data)

    @action(detail=True, methods=['post'], url_path='apply-adjustment')
    def apply_adjustment(self, request, pk=None):
        line = self.get_object()
        if line.is_verified:
            return Response(
                {"error": "Cette ligne a déjà été ajustée"}, status=400
            )
        if line.actual_quantity is None:
            return Response(
                {"error": "Veuillez saisir la quantité réelle avant d'ajuster"},
                status=400
            )
        try:
            with transaction.atomic():
                line.apply_adjustment(request.user)
            return Response({
                "status": "success",
                "message": f"Ajustement appliqué pour {line.product.name}",
                "difference": line.difference,
            })
        except Exception as e:
            return Response({"error": str(e)}, status=500)


# ==================== INVENTORY ====================
class InventoryViewSet(viewsets.ModelViewSet):
    queryset = Inventory.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def get_serializer_class(self):
        if self.action == 'create':
            return InventoryCreateSerializer
        return InventorySerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        inventory = self.get_object()
        inventory.start()
        products = Product.objects.filter(status='active')
        for product in products:
            stock = Stock.objects.filter(
                product=product, warehouse=inventory.warehouse
            ).first()
            expected_quantity = stock.quantity if stock else 0
            InventoryLine.objects.get_or_create(
                inventory=inventory,
                product=product,
                defaults={'expected_quantity': expected_quantity}
            )
        return Response({
            "message": "Inventaire démarré",
            "status": inventory.status
        })

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        inventory = self.get_object()
        inventory.complete()
        return Response({
            "message": "Inventaire terminé",
            "status": inventory.status
        })

    @action(detail=True, methods=['get'])
    def lines(self, request, pk=None):
        inventory = self.get_object()
        lines = inventory.lines.all().select_related('product', 'lot')
        return Response(InventoryLineSerializer(lines, many=True).data)


# ==================== TRANSFER ====================
class TransferViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsGestionnaire]

    def create(self, request):
        serializer = TransferRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

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
            return Response(
                {"error": "Entrepôt source ou destination introuvable."},
                status=404
            )

        movements_created = []

        with transaction.atomic():
            for item in items:
                product_id = item['product_id']
                quantity = item['quantity']
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    return Response(
                        {"error": f"Produit {product_id} introuvable."},
                        status=404
                    )

                try:
                    stock_source = Stock.objects.get(
                        product=product, warehouse=from_warehouse
                    )
                except Stock.DoesNotExist:
                    return Response(
                        {"error": f"Le produit {product.name} n'a pas de stock dans l'entrepôt source."},
                        status=400
                    )

                success, lots_used = stock_source.consume_stock(quantity)
                if not success:
                    return Response(
                        {"error": f"Impossible de consommer le stock pour {product.name}."},
                        status=400
                    )

                reference_number = f"TRANSF-{timezone.now().strftime('%Y%m%d%H%M%S')}"

                for lot_data in lots_used:
                    lot = lot_data['lot']
                    qty = lot_data['quantity']
                    StockMovement.objects.create(
                        product=product,
                        lot=lot,
                        from_warehouse=from_warehouse,
                        to_warehouse=to_warehouse,
                        movement_type='transfer_out',
                        quantity=qty,
                        reason=reason,
                        notes=notes,
                        created_by=request.user,
                        reference_number=reference_number
                    )

                for lot_data in lots_used:
                    source_lot = lot_data['lot']
                    qty = lot_data['quantity']

                    unique_suffix = uuid.uuid4().hex[:8]
                    new_lot_number = f"{source_lot.lot_number}-TRANSF-{unique_suffix}"

                    new_lot = Lot.objects.create(
                        product=product,
                        warehouse=to_warehouse,
                        lot_number=new_lot_number,
                        batch_number=source_lot.batch_number,
                        barcode=source_lot.barcode,
                        initial_quantity=qty,
                        current_quantity=qty,
                        reserved_quantity=0,
                        unit=source_lot.unit,
                        manufacturing_date=source_lot.manufacturing_date,
                        expiry_date=source_lot.expiry_date,
                        purchase_price=source_lot.purchase_price,
                        selling_price=source_lot.selling_price,
                        status='good',
                        created_by=request.user,
                        notes=f"Transfert depuis {from_warehouse.name} - {notes}"
                    )

                    StockMovement.objects.create(
                        product=product,
                        lot=new_lot,
                        from_warehouse=from_warehouse,
                        to_warehouse=to_warehouse,
                        movement_type='transfer_in',
                        quantity=qty,
                        reason=reason,
                        notes=notes,
                        created_by=request.user,
                        reference_number=reference_number
                    )

                stock_source.update_quantity()
                stock_dest, _ = Stock.objects.get_or_create(
                    product=product, warehouse=to_warehouse
                )
                stock_dest.update_quantity()

                movements_created.append({
                    "product": product.name,
                    "quantity": quantity,
                    "from_warehouse": from_warehouse.name,
                    "to_warehouse": to_warehouse.name,
                    "lots_used": [
                        {"lot": l['lot'].lot_number, "qty": l['quantity']}
                        for l in lots_used
                    ]
                })

        response_serializer = TransferResponseSerializer({
            "message": "Transfert effectué avec succès",
            "movements": movements_created
        })
        return Response(response_serializer.data, status=201)


# ==================== DASHBOARD STATS ====================
class DashboardStatsViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        total_products = Product.objects.filter(status='active').count()
        low_stock_products = 0
        out_of_stock_products = 0

        for product in Product.objects.filter(status='active'):
            stock = product.current_stock
            if stock <= 0:
                out_of_stock_products += 1
            elif stock <= product.min_stock:
                low_stock_products += 1

        expiring_lots = Lot.objects.filter(
            expiry_date__lte=date.today() + timedelta(days=30),
            expiry_date__gte=date.today(),
            current_quantity__gt=0
        ).count()

        expired_lots = Lot.objects.filter(
            expiry_date__lt=date.today(),
            current_quantity__gt=0
        ).count()

        total_warehouses = Warehouse.objects.filter(is_active=True).count()
        unprocessed_alerts = ExpiryAlert.objects.filter(
            is_processed=False).count()

        return Response({
            'products': {
                'total': total_products,
                'low_stock': low_stock_products,
                'out_of_stock': out_of_stock_products
            },
            'lots': {
                'expiring_soon': expiring_lots,
                'expired': expired_lots
            },
            'warehouses': {'total': total_warehouses},
            'alerts': {'unprocessed': unprocessed_alerts}
        })

    @action(detail=False, methods=['get'])
    def expiring_products(self, request):
        result = []
        alert_date = date.today() + timedelta(days=30)
        lots = Lot.objects.filter(
            expiry_date__lte=alert_date,
            expiry_date__gte=date.today(),
            current_quantity__gt=0
        ).select_related('product', 'warehouse').order_by('expiry_date')

        for lot in lots:
            days_left = (lot.expiry_date - date.today()).days
            if days_left <= 7:
                severity = 'danger'
            elif days_left <= 15:
                severity = 'warning'
            else:
                severity = 'info'

            result.append({
                'lot_id': lot.id,
                'lot_number': lot.lot_number,
                'product_id': lot.product.id,
                'product_name': lot.product.name,
                'product_code': lot.product.code,
                'warehouse_name': lot.warehouse.name if lot.warehouse else 'N/A',
                'current_quantity': lot.current_quantity,
                'expiry_date': lot.expiry_date,
                'days_left': days_left,
                'severity': severity
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        result = []
        stocks = Stock.objects.filter(
            quantity__lte=F('product__min_stock')
        ).select_related('product', 'warehouse')

        for stock in stocks:
            result.append({
                'product_id': stock.product.id,
                'product_name': stock.product.name,
                'product_code': stock.product.code,
                'current_stock': stock.quantity,
                'min_stock': stock.min_stock,
                'warehouse_id': stock.warehouse.id,
                'warehouse_name': stock.warehouse.name,
                'difference': stock.quantity - stock.min_stock
            })
        return Response(result)

    @action(detail=False, methods=['get'])
    def stock_value(self, request):
        total_value = 0
        lots = Lot.objects.filter(
            current_quantity__gt=0).exclude(status='expired')
        for lot in lots:
            total_value += lot.current_quantity * lot.purchase_price
        return Response({
            'total_stock_value': float(total_value),
            'currency': 'XOF'
        })
