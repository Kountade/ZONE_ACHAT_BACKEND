# apps/achats_fournisseurs/serializers.py
from rest_framework import serializers
from django.db import transaction
from django.db.models import Sum, F
from datetime import date
from decimal import Decimal

from .models import (
    Supplier, SupplierContact, SupplierProduct, PurchaseOrder,
    PurchaseOrderLine, Receipt, ReceiptLine, PurchaseReturn,
    PurchaseReturnLine, SupplierInvoice, FournisseurPaiement
)
from produits_stocks.models import Product, Lot, Stock, StockMovement


# ============================================================
# FOURNISSEUR - SERIALIZERS
# ============================================================

class SupplierContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierContact
        fields = ['id', 'name', 'position', 'phone', 'mobile', 'email',
                  'is_primary', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at']


class SupplierProductSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_unit = serializers.CharField(
        source='product.unit.symbol', read_only=True)

    class Meta:
        model = SupplierProduct
        fields = ['id', 'product', 'product_name', 'product_code', 'product_unit',
                  'supplier_sku', 'purchase_price', 'lead_time', 'minimum_order',
                  'is_active', 'notes', 'last_updated']
        read_only_fields = ['id', 'last_updated']


class SupplierListSerializer(serializers.ModelSerializer):
    total_purchases_display = serializers.SerializerMethodField()
    total_debt = serializers.SerializerMethodField()
    overdue_debt = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = ['id', 'code', 'name', 'commercial_name', 'type', 'phone', 'email',
                  'city', 'is_active', 'is_preferred', 'rating', 'total_purchases',
                  'total_purchases_display', 'total_debt', 'overdue_debt']
        read_only_fields = ['id', 'total_purchases', 'total_orders']

    def get_total_purchases_display(self, obj):
        return f"{obj.total_purchases:,.0f} FCFA" if obj.total_purchases else "0 FCFA"

    def get_total_debt(self, obj):
        return obj.total_debt

    def get_overdue_debt(self, obj):
        return obj.overdue_debt


class SupplierDetailSerializer(serializers.ModelSerializer):
    contacts = SupplierContactSerializer(many=True, read_only=True)
    products = SupplierProductSerializer(many=True, read_only=True)
    total_debt = serializers.SerializerMethodField()
    overdue_debt = serializers.SerializerMethodField()
    total_purchases_display = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = ['id', 'code', 'name', 'commercial_name', 'type', 'contact_person',
                  'phone', 'mobile', 'email', 'website', 'address', 'city', 'country',
                  'postal_code', 'tax_id', 'registration_number', 'payment_terms',
                  'delivery_lead_time', 'minimum_order', 'rating', 'total_purchases',
                  'total_purchases_display', 'total_orders', 'on_time_delivery_rate',
                  'is_active', 'is_preferred', 'notes', 'contacts', 'products',
                  'total_debt', 'overdue_debt', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'created_at', 'updated_at',
                            'total_purchases', 'total_orders']

    def get_total_purchases_display(self, obj):
        return f"{obj.total_purchases:,.0f} FCFA" if obj.total_purchases else "0 FCFA"

    def get_total_debt(self, obj):
        total = obj.invoices.filter(
            paiement_status__in=['unpaid', 'partial', 'overdue']
        ).aggregate(total=Sum(F('total_amount') - F('amount_paid')))['total']
        return total or Decimal('0')

    def get_overdue_debt(self, obj):
        total = obj.invoices.filter(
            due_date__lt=date.today(),
            paiement_status__in=['unpaid', 'partial']
        ).aggregate(total=Sum(F('total_amount') - F('amount_paid')))['total']
        return total or Decimal('0')


class SupplierWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['code', 'name', 'commercial_name', 'type', 'contact_person',
                  'phone', 'mobile', 'email', 'website', 'address', 'city', 'country',
                  'postal_code', 'tax_id', 'registration_number', 'payment_terms',
                  'delivery_lead_time', 'minimum_order', 'is_active', 'is_preferred',
                  'notes']

    def validate_code(self, value):
        instance_id = self.instance.id if self.instance else None
        if Supplier.objects.exclude(id=instance_id).filter(code=value).exists():
            raise serializers.ValidationError(
                "Ce code fournisseur existe déjà")
        return value


# ============================================================
# BON DE COMMANDE - SERIALIZERS
# ============================================================

class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    quantity_remaining = serializers.ReadOnlyField()

    class Meta:
        model = PurchaseOrderLine
        fields = ['id', 'product', 'product_name', 'product_code', 'quantity',
                  'quantity_received', 'quantity_remaining', 'unit_price',
                  'discount', 'tax_rate', 'total', 'notes']
        read_only_fields = ['id', 'quantity_received', 'total']


class PurchaseOrderLineCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLine
        fields = ['product', 'quantity', 'unit_price',
                  'discount', 'tax_rate', 'notes']

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "La quantité doit être supérieure à 0")
        return value

    def validate_unit_price(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le prix unitaire doit être supérieur à 0")
        return value


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.name', read_only=True)
    supplier_code = serializers.CharField(
        source='supplier.code', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    has_qr_code = serializers.SerializerMethodField()
    receipt_progress = serializers.SerializerMethodField()
    payment_progress = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ['id', 'po_number', 'supplier', 'supplier_name', 'supplier_code',
                  'order_date', 'expected_delivery_date', 'actual_delivery_date',
                  'total', 'status', 'status_display', 'created_by', 'has_qr_code',
                  'receipt_progress', 'payment_progress', 'is_fully_received',
                  'is_fully_invoiced', 'is_fully_paid']
        read_only_fields = ['id', 'order_date', 'po_number']

    def get_has_qr_code(self, obj):
        return bool(obj.qr_code)

    def get_receipt_progress(self, obj):
        return obj.receipt_progress

    def get_payment_progress(self, obj):
        return obj.payment_progress


class PurchaseOrderDetailSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.name', read_only=True)
    supplier_code = serializers.CharField(
        source='supplier.code', read_only=True)
    supplier_address = serializers.CharField(
        source='supplier.address', read_only=True)
    supplier_phone = serializers.CharField(
        source='supplier.phone', read_only=True)
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    receipt_progress = serializers.SerializerMethodField()
    invoice_progress = serializers.SerializerMethodField()
    payment_progress = serializers.SerializerMethodField()
    remaining_to_receive = serializers.SerializerMethodField()
    remaining_to_invoice = serializers.SerializerMethodField()
    remaining_to_pay = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ['id', 'po_number', 'supplier_reference', 'supplier', 'supplier_name',
                  'supplier_code', 'supplier_address', 'supplier_phone', 'order_date',
                  'expected_delivery_date', 'actual_delivery_date', 'subtotal',
                  'discount_type', 'discount_value', 'discount_amount', 'tax_rate',
                  'tax_amount', 'shipping_cost', 'total', 'status', 'status_display',
                  'notes', 'internal_notes', 'shipping_address', 'tracking_number',
                  'lines', 'created_at', 'updated_at', 'created_by', 'created_by_name',
                  'approved_by', 'approved_by_name', 'approved_at', 'qr_code',
                  'qr_code_data', 'qr_code_url', 'receipt_progress', 'invoice_progress',
                  'payment_progress', 'remaining_to_receive', 'remaining_to_invoice',
                  'remaining_to_pay', 'is_fully_received', 'is_fully_invoiced',
                  'is_fully_paid', 'total_received_amount', 'total_invoiced_amount',
                  'total_paid_amount']
        read_only_fields = ['id', 'order_date',
                            'po_number', 'qr_code', 'qr_code_data']

    def _user_full_name(self, user):
        if not user:
            return None
        return getattr(user, 'full_name', None) or user.get_full_name() or user.username

    def get_created_by_name(self, obj):
        return self._user_full_name(obj.created_by)

    def get_approved_by_name(self, obj):
        return self._user_full_name(obj.approved_by)

    def get_qr_code_url(self, obj):
        if obj.qr_code:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_receipt_progress(self, obj):
        if obj.total == 0:
            return 0
        return (obj.total_received_amount / obj.total) * 100

    def get_invoice_progress(self, obj):
        if obj.total == 0:
            return 0
        total_invoiced = obj.invoices.aggregate(
            total=Sum('total_amount'))['total'] or 0
        return (total_invoiced / obj.total) * 100

    def get_payment_progress(self, obj):
        if obj.total_invoiced_amount == 0:
            return 0
        return (obj.total_paid_amount / obj.total_invoiced_amount) * 100

    def get_remaining_to_receive(self, obj):
        return obj.total - obj.total_received_amount

    def get_remaining_to_invoice(self, obj):
        return obj.total - obj.total_invoiced_amount

    def get_remaining_to_pay(self, obj):
        return obj.total_invoiced_amount - obj.total_paid_amount


class PurchaseOrderCreateSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineCreateSerializer(many=True)

    class Meta:
        model = PurchaseOrder
        fields = ['supplier', 'supplier_reference', 'expected_delivery_date',
                  'discount_type', 'discount_value', 'tax_rate', 'shipping_cost',
                  'notes', 'internal_notes', 'shipping_address', 'lines']

    def validate_expected_delivery_date(self, value):
        if value < date.today():
            raise serializers.ValidationError(
                "La date de livraison prévue ne peut pas être dans le passé"
            )
        return value

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Au moins un produit est requis")
        product_ids = [line.get('product')
                       for line in value if line.get('product')]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Un produit ne peut apparaître qu'une seule fois dans la commande"
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        from .models import generate_number
        lines_data = validated_data.pop('lines')
        po_number = generate_number(PurchaseOrder, 'po_number', 'PO')
        purchase_order = PurchaseOrder.objects.create(
            po_number=po_number, **validated_data
        )
        for line_data in lines_data:
            PurchaseOrderLine.objects.create(
                purchase_order=purchase_order, **line_data
            )
        purchase_order.calculate_totals()
        purchase_order.generate_qr_code()
        purchase_order.save()
        return purchase_order


class PurchaseOrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = ['supplier_reference', 'expected_delivery_date', 'discount_type',
                  'discount_value', 'tax_rate', 'shipping_cost', 'notes',
                  'internal_notes', 'shipping_address', 'tracking_number']

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        instance.calculate_totals()
        instance.generate_qr_code()
        instance.save()
        return instance


class PurchaseOrderApproveSerializer(serializers.Serializer):
    approved = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True)


# ============================================================
# RÉCEPTION - SERIALIZERS
# ============================================================

class ReceiptLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    po_line_quantity = serializers.IntegerField(
        source='po_line.quantity', read_only=True)
    po_line_unit_price = serializers.DecimalField(
        source='po_line.unit_price', max_digits=10, decimal_places=2, read_only=True
    )
    quality_status_display = serializers.CharField(
        source='get_quality_status_display', read_only=True
    )

    class Meta:
        model = ReceiptLine
        fields = ['id', 'product', 'product_name', 'product_code', 'po_line',
                  'po_line_quantity', 'po_line_unit_price', 'quantity_ordered',
                  'quantity_received', 'quantity_damaged', 'lot', 'lot_number',
                  'expiry_date', 'manufacturing_date', 'is_quality_checked',
                  'quality_status', 'quality_status_display', 'quality_notes', 'notes']
        read_only_fields = ['id', 'po_line', 'quantity_ordered']


class ReceiptLineCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptLine
        fields = ['po_line', 'quantity_received', 'quantity_damaged', 'lot_number',
                  'expiry_date', 'manufacturing_date', 'quality_status',
                  'quality_notes', 'notes']

    def validate_quantity_received(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "La quantité reçue doit être supérieure à 0"
            )
        return value


class ReceiptListSerializer(serializers.ModelSerializer):
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    purchase_order_id = serializers.IntegerField(
        source='purchase_order.id', read_only=True)  # ✅ AJOUT
    supplier_name = serializers.CharField(
        source='purchase_order.supplier.name', read_only=True
    )
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    has_qr_code = serializers.SerializerMethodField()
    total_received = serializers.SerializerMethodField()
    is_invoiced_display = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ['id', 'receipt_number', 'po_number', 'purchase_order_id',  # ✅ AJOUT
                  'supplier_name', 'warehouse', 'warehouse_name', 'receipt_date',
                  'expected_date', 'status', 'status_display', 'created_by',
                  'has_qr_code', 'total_received', 'is_invoiced', 'is_invoiced_display']
        read_only_fields = ['id', 'receipt_number', 'receipt_date']

    def get_has_qr_code(self, obj):
        return bool(obj.qr_code)

    def get_total_received(self, obj):
        return obj.lines.aggregate(total=Sum('quantity_received'))['total'] or 0

    def get_is_invoiced_display(self, obj):
        return " Facturée" if obj.is_invoiced else " Non facturée"


class ReceiptDetailSerializer(serializers.ModelSerializer):
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    supplier_name = serializers.CharField(
        source='purchase_order.supplier.name', read_only=True
    )
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    lines = ReceiptLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    caisse_destination_nom = serializers.SerializerMethodField()
    compte_destination_nom = serializers.SerializerMethodField()
    mouvement_reference = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ['id', 'receipt_number', 'purchase_order', 'po_number',
                  'supplier_name', 'receipt_date', 'expected_date', 'warehouse',
                  'warehouse_name', 'status', 'status_display', 'notes',
                  'delivery_note', 'invoice_number', 'lines', 'created_at',
                  'created_by', 'created_by_name', 'qr_code', 'qr_code_data',
                  'qr_code_url', 'caisse_destination_id', 'caisse_destination_nom',
                  'compte_destination_id', 'compte_destination_nom',
                  'montant_decaissement', 'mouvement_reference', 'is_invoiced',
                  'supplier_invoice', 'auto_invoice', 'auto_invoice_number']
        read_only_fields = ['id', 'receipt_number', 'receipt_date', 'qr_code',
                            'qr_code_data', 'montant_decaissement']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return (getattr(obj.created_by, 'full_name', None)
                    or obj.created_by.get_full_name()
                    or obj.created_by.username)
        return None

    def get_qr_code_url(self, obj):
        if obj.qr_code:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_caisse_destination_nom(self, obj):
        if obj.caisse_destination_id:
            try:
                from tresorerie.models import Caisse
                return Caisse.objects.get(id=obj.caisse_destination_id).nom
            except Exception:
                return None
        return None

    def get_compte_destination_nom(self, obj):
        if obj.compte_destination_id:
            try:
                from tresorerie.models import CompteBancaire
                return CompteBancaire.objects.get(id=obj.compte_destination_id).nom
            except Exception:
                return None
        return None

    def get_mouvement_reference(self, obj):
        if obj.mouvement_tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie
                return MouvementTresorerie.objects.get(
                    id=obj.mouvement_tresorerie_id
                ).reference
            except Exception:
                return None
        return None


class ReceiptCreateSerializer(serializers.ModelSerializer):
    lines = ReceiptLineCreateSerializer(many=True)

    class Meta:
        model = Receipt
        fields = ['purchase_order', 'expected_date', 'warehouse', 'delivery_note',
                  'invoice_number', 'notes', 'lines', 'caisse_destination_id',
                  'compte_destination_id', 'auto_invoice']

    def validate(self, data):
        purchase_order = data.get('purchase_order')
        if purchase_order and purchase_order.status in ['cancelled', 'received']:
            raise serializers.ValidationError(
                "Cette commande ne peut plus être réceptionnée"
            )

        lines_data = data.get('lines', [])
        for line_data in lines_data:
            po_line = line_data.get('po_line')
            quantity_received = line_data.get('quantity_received', 0)
            total_received = ReceiptLine.objects.filter(
                po_line=po_line
            ).aggregate(total=Sum('quantity_received'))['total'] or 0
            quantity_remaining = po_line.quantity - total_received
            if quantity_received > quantity_remaining:
                raise serializers.ValidationError(
                    f"Quantité reçue ({quantity_received}) dépasse la quantité "
                    f"restante ({quantity_remaining})"
                )

        caisse = data.get('caisse_destination_id')
        compte = data.get('compte_destination_id')
        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination (caisse ou compte)."
            )
        return data

    @transaction.atomic
    def create(self, validated_data):
        from .models import generate_number

        lines_data = validated_data.pop('lines')
        purchase_order = validated_data.get('purchase_order')
        warehouse = validated_data.get('warehouse')
        user = self.context['request'].user
        auto_invoice = validated_data.pop('auto_invoice', True)

        receipt_number = generate_number(Receipt, 'receipt_number', 'REC')
        receipt = Receipt.objects.create(
            receipt_number=receipt_number,
            status='in_progress',
            auto_invoice=auto_invoice,
            created_by=user,
            **validated_data
        )

        for line_data in lines_data:
            po_line = line_data['po_line']
            quantity_received = line_data['quantity_received']
            quantity_damaged = line_data.get('quantity_damaged', 0)
            lot_number = (line_data.get('lot_number') or '').strip()
            expiry_date = line_data.get('expiry_date')
            manufacturing_date = line_data.get('manufacturing_date')
            quality_status = line_data.get('quality_status', 'pending')
            notes = line_data.get('notes', '')

            product = po_line.product
            lot = None

            if lot_number:
                existing_lot = Lot.objects.filter(
                    lot_number=lot_number).first()
                if existing_lot:
                    lot = existing_lot
                    if not lot.warehouse:
                        lot.warehouse = warehouse
                    lot.current_quantity += quantity_received
                    if expiry_date and not lot.expiry_date:
                        lot.expiry_date = expiry_date
                    if manufacturing_date and not lot.manufacturing_date:
                        lot.manufacturing_date = manufacturing_date
                    lot.save()
                else:
                    lot = Lot.objects.create(
                        lot_number=lot_number,
                        product=product,
                        warehouse=warehouse,
                        initial_quantity=quantity_received,
                        current_quantity=quantity_received,
                        purchase_price=po_line.unit_price,
                        selling_price=product.selling_price,
                        created_by=user,
                        expiry_date=expiry_date,
                        manufacturing_date=manufacturing_date,
                        status='good'
                    )
            else:
                auto_lot_number = (
                    f"LOT-{product.code}-{date.today().strftime('%Y%m%d')}-"
                    f"{ReceiptLine.objects.filter(product=product).count() + 1}"
                )
                lot = Lot.objects.create(
                    lot_number=auto_lot_number,
                    product=product,
                    warehouse=warehouse,
                    initial_quantity=quantity_received,
                    current_quantity=quantity_received,
                    purchase_price=po_line.unit_price,
                    selling_price=product.selling_price,
                    created_by=user,
                    expiry_date=expiry_date,
                    manufacturing_date=manufacturing_date,
                    status='good'
                )
                lot_number = auto_lot_number

            ReceiptLine.objects.create(
                receipt=receipt,
                po_line=po_line,
                product=product,
                quantity_ordered=po_line.quantity,
                quantity_received=quantity_received,
                quantity_damaged=quantity_damaged,
                lot=lot,
                lot_number=lot_number,
                expiry_date=expiry_date,
                manufacturing_date=manufacturing_date,
                quality_status=quality_status,
                notes=notes
            )

            stock, _ = Stock.objects.get_or_create(
                product=product,
                warehouse=warehouse,
                defaults={'quantity': 0, 'reserved_quantity': 0}
            )
            stock.update_quantity()

            StockMovement.objects.create(
                product=product,
                lot=lot,
                to_warehouse=warehouse,
                movement_type='purchase_in',
                quantity=quantity_received,
                reference_type='purchase_order',
                reference_id=purchase_order.id,
                reference_number=purchase_order.po_number,
                reason=f"Réception commande {purchase_order.po_number}",
                created_by=user,
                notes=f"Réception n°{receipt_number}"
            )

            purchase_order.total_received_amount += quantity_received * po_line.unit_price

        purchase_order.update_receipt_status()
        purchase_order.save()

        receipt.status = 'completed'
        receipt.save()

        receipt.creer_mouvement_decaissement(user)
        receipt.generate_qr_code()
        receipt.save()

        return receipt


class ReceiptChoiceSerializer(serializers.ModelSerializer):
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    supplier_name = serializers.CharField(
        source='purchase_order.supplier.name', read_only=True
    )
    supplier_id = serializers.IntegerField(
        source='purchase_order.supplier.id', read_only=True
    )
    total_received_amount = serializers.SerializerMethodField()
    receipt_date_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    auto_invoice_display = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ['id', 'receipt_number', 'po_number', 'supplier_name', 'supplier_id',
                  'receipt_date', 'receipt_date_display', 'total_received_amount',
                  'is_invoiced', 'status', 'status_display', 'auto_invoice',
                  'auto_invoice_display', 'auto_invoice_number']

    def get_total_received_amount(self, obj):
        return obj.total_received_amount

    def get_receipt_date_display(self, obj):
        return obj.receipt_date.strftime('%d/%m/%Y') if obj.receipt_date else ''

    def get_auto_invoice_display(self, obj):
        return "✅ Activée" if obj.auto_invoice else "❌ Désactivée"


# ============================================================
# RETOUR FOURNISSEUR - SERIALIZERS
# ============================================================

class PurchaseReturnLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(
        source='receipt_line.lot_number', read_only=True
    )

    class Meta:
        model = PurchaseReturnLine
        fields = ['id', 'receipt_line', 'product', 'product_name', 'product_code',
                  'lot_number', 'quantity', 'unit_price', 'total']
        read_only_fields = ['id', 'total']


class PurchaseReturnSerializer(serializers.ModelSerializer):
    """✅ Serializer de LECTURE + mise à jour du statut (PATCH)"""
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    supplier_name = serializers.CharField(
        source='purchase_order.supplier.name', read_only=True
    )
    supplier_code = serializers.CharField(
        source='purchase_order.supplier.code', read_only=True
    )
    receipt_number = serializers.CharField(
        source='receipt.receipt_number', read_only=True
    )
    lines = PurchaseReturnLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    reason_display = serializers.CharField(
        source='get_reason_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReturn
        fields = ['id', 'return_number', 'purchase_order', 'po_number',
                  'supplier_name', 'supplier_code', 'receipt', 'receipt_number',
                  'return_date', 'reason', 'reason_display', 'status',
                  'status_display', 'notes', 'lines', 'total_amount',
                  'created_by', 'created_by_name', 'qr_code', 'qr_code_data',
                  'qr_code_url']
        read_only_fields = ['id', 'return_number', 'return_date', 'purchase_order',
                            'receipt', 'reason', 'qr_code', 'qr_code_data']
        # ⚠️ 'status' et 'notes' restent modifiables

    def get_created_by_name(self, obj):
        if obj.created_by:
            return (getattr(obj.created_by, 'full_name', None)
                    or obj.created_by.get_full_name()
                    or obj.created_by.username)
        return None

    def get_qr_code_url(self, obj):
        if obj.qr_code:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_total_amount(self, obj):
        return sum(float(line.total or 0) for line in obj.lines.all())

    def validate_status(self, value):
        """✅ Vérifier que la transition de statut est cohérente"""
        if not self.instance:
            return value

        current = self.instance.status
        allowed_transitions = {
            'requested': ['approved', 'rejected'],
            'approved': ['shipped', 'rejected'],
            'shipped': ['refunded', 'replaced'],
            'refunded': [],
            'replaced': [],
            'rejected': [],
        }

        if value != current and value not in allowed_transitions.get(current, []):
            raise serializers.ValidationError(
                f"Transition invalide : {current} → {value}. "
                f"Transitions autorisées : {allowed_transitions.get(current, [])}"
            )
        return value


# apps/achats_fournisseurs/serializers.py

class PurchaseReturnLineCreateSerializer(serializers.Serializer):
    """✅ Serializer simple pour les lignes du retour"""
    receipt_line = serializers.IntegerField(required=True)
    quantity = serializers.IntegerField(required=True, min_value=1)
    # ✅ product et unit_price sont OPTIONNELS (déduits du receipt_line)
    product = serializers.IntegerField(required=False)
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )


class PurchaseReturnCreateSerializer(serializers.ModelSerializer):
    """✅ Serializer de CRÉATION avec gestion du stock"""
    lines = PurchaseReturnLineCreateSerializer(many=True, write_only=True)

    class Meta:
        model = PurchaseReturn
        fields = ['purchase_order', 'receipt', 'reason', 'notes', 'lines']

    def validate(self, data):
        purchase_order = data.get('purchase_order')
        receipt = data.get('receipt')

        if not purchase_order:
            raise serializers.ValidationError(
                {"purchase_order": "La commande est obligatoire"}
            )

        if not receipt:
            raise serializers.ValidationError(
                {"receipt": "La réception est obligatoire"}
            )

        if receipt.purchase_order_id != purchase_order.id:
            raise serializers.ValidationError(
                {"receipt": "La réception ne correspond pas à la commande sélectionnée"}
            )

        if receipt.status != 'completed':
            raise serializers.ValidationError(
                {"receipt": f"La réception {receipt.receipt_number} n'est pas terminée (statut: {receipt.get_status_display()})"}
            )

        lines_data = data.get('lines', [])
        if not lines_data:
            raise serializers.ValidationError(
                {"lines": "Au moins un produit doit être retourné"}
            )

        valid_lines = [l for l in lines_data if l.get('quantity', 0) > 0]
        if not valid_lines:
            raise serializers.ValidationError(
                {"lines": "Au moins un produit doit avoir une quantité > 0"}
            )

        for line_data in valid_lines:
            receipt_line_id = line_data.get('receipt_line')
            quantity = line_data.get('quantity', 0)

            try:
                receipt_line = ReceiptLine.objects.get(id=receipt_line_id)
            except ReceiptLine.DoesNotExist:
                raise serializers.ValidationError(
                    {"lines": f"Ligne de réception {receipt_line_id} introuvable"}
                )

            if receipt_line.receipt_id != receipt.id:
                raise serializers.ValidationError({
                    "lines": (
                        f"La ligne {receipt_line_id} n'appartient pas à la "
                        f"réception {receipt.receipt_number}"
                    )
                })

            already_returned = PurchaseReturnLine.objects.filter(
                receipt_line=receipt_line
            ).exclude(
                purchase_return__status='rejected'
            ).aggregate(total=Sum('quantity'))['total'] or 0

            available = receipt_line.quantity_received - already_returned

            if quantity > available:
                raise serializers.ValidationError({
                    "lines": (
                        f"Quantité retournée ({quantity}) dépasse la quantité "
                        f"disponible ({available}) pour le produit "
                        f"{receipt_line.product.name}"
                    )
                })

        return data

    @transaction.atomic
    def create(self, validated_data):
        from .models import generate_number

        lines_data = validated_data.pop('lines')
        purchase_order = validated_data.get('purchase_order')
        receipt = validated_data.get('receipt')
        user = self.context['request'].user

        return_number = generate_number(PurchaseReturn, 'return_number', 'RET')

        purchase_return = PurchaseReturn.objects.create(
            return_number=return_number,
            purchase_order=purchase_order,
            receipt=receipt,
            reason=validated_data.get('reason'),
            notes=validated_data.get('notes', ''),
            status='requested',
            created_by=user
        )

        for line_data in lines_data:
            quantity = line_data.get('quantity', 0)
            if quantity <= 0:
                continue

            receipt_line = ReceiptLine.objects.get(
                id=line_data['receipt_line'])
            product = receipt_line.product
            unit_price = receipt_line.po_line.unit_price

            PurchaseReturnLine.objects.create(
                purchase_return=purchase_return,
                receipt_line=receipt_line,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
            )

            # Mouvement de stock (sortie)
            if receipt_line.lot:
                lot = receipt_line.lot
                lot.current_quantity -= quantity
                lot.save()

                StockMovement.objects.create(
                    product=product,
                    lot=lot,
                    from_warehouse=lot.warehouse,
                    movement_type='return_out',
                    quantity=quantity,
                    reference_type='purchase_return',
                    reference_id=purchase_return.id,
                    reference_number=return_number,
                    reason=f"Retour fournisseur - {purchase_return.get_reason_display()}",
                    created_by=user
                )

        purchase_return.generate_qr_code()
        purchase_return.save()

        return purchase_return
# ============================================================
# SUPPLIER INVOICE - SERIALIZERS
# ============================================================


class SupplierInvoiceListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.name', read_only=True)
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    paiement_status_display = serializers.CharField(
        source='get_paiement_status_display', read_only=True
    )
    total_display = serializers.SerializerMethodField()
    amount_paid_display = serializers.SerializerMethodField()
    remaining_display = serializers.SerializerMethodField()
    paid_percentage = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    receipt_number = serializers.SerializerMethodField()
    receipt_id = serializers.SerializerMethodField()

    class Meta:
        model = SupplierInvoice
        fields = ['id', 'invoice_number', 'purchase_order', 'po_number', 'supplier',
                  'supplier_name', 'invoice_date', 'due_date',
                  'total_amount', 'total_display',
                  'amount_paid', 'amount_paid_display',
                  'remaining_amount', 'remaining_display',
                  'paid_percentage', 'status', 'status_display',
                  'paiement_status', 'paiement_status_display',
                  'is_fully_paid', 'is_overdue', 'receipt_number', 'receipt_id']

    def get_total_display(self, obj):
        return f"{obj.total_amount:,.0f} FCFA" if obj.total_amount else "0 FCFA"

    def get_amount_paid_display(self, obj):
        return f"{obj.amount_paid:,.0f} FCFA" if obj.amount_paid else "0 FCFA"

    def get_remaining_display(self, obj):
        remaining = obj.total_amount - obj.amount_paid
        return f"{remaining:,.0f} FCFA" if remaining else "0 FCFA"

    def get_paid_percentage(self, obj):
        if obj.total_amount == 0:
            return 0
        return (obj.amount_paid / obj.total_amount) * 100

    def get_is_overdue(self, obj):
        return obj.is_overdue

    def get_receipt_number(self, obj):
        receipt = obj.receipts.first()
        return receipt.receipt_number if receipt else None

    def get_receipt_id(self, obj):
        receipt = obj.receipts.first()
        return receipt.id if receipt else None


class SupplierInvoiceDetailSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier.name', read_only=True)
    po_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    paiement_status_display = serializers.CharField(
        source='get_paiement_status_display', read_only=True
    )
    total_display = serializers.SerializerMethodField()
    amount_paid_display = serializers.SerializerMethodField()
    remaining_display = serializers.SerializerMethodField()
    paid_percentage = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    days_overdue = serializers.SerializerMethodField()
    paiements = serializers.SerializerMethodField()
    receipt = serializers.SerializerMethodField()

    class Meta:
        model = SupplierInvoice
        fields = ['id', 'invoice_number', 'purchase_order', 'po_number', 'supplier',
                  'supplier_name', 'invoice_date', 'due_date', 'amount', 'tax_amount',
                  'total_amount', 'total_display', 'amount_paid', 'amount_paid_display',
                  'remaining_amount', 'remaining_display', 'paid_percentage',
                  'status', 'status_display', 'paiement_status',
                  'paiement_status_display', 'is_fully_paid', 'is_overdue',
                  'days_overdue', 'payment_date', 'payment_reference', 'notes',
                  'paiements', 'receipt', 'created_at', 'updated_at']
        read_only_fields = ['id', 'amount_paid', 'created_at', 'updated_at']

    def get_total_display(self, obj):
        return f"{obj.total_amount:,.0f} FCFA" if obj.total_amount else "0 FCFA"

    def get_amount_paid_display(self, obj):
        return f"{obj.amount_paid:,.0f} FCFA" if obj.amount_paid else "0 FCFA"

    def get_remaining_display(self, obj):
        remaining = obj.total_amount - obj.amount_paid
        return f"{remaining:,.0f} FCFA" if remaining else "0 FCFA"

    def get_paid_percentage(self, obj):
        if obj.total_amount == 0:
            return 0
        return (obj.amount_paid / obj.total_amount) * 100

    def get_is_overdue(self, obj):
        return obj.is_overdue

    def get_days_overdue(self, obj):
        return obj.days_overdue

    def get_paiements(self, obj):
        return FournisseurPaiementSerializer(
            obj.paiements.filter(status='confirmed').order_by('-payment_date'),
            many=True
        ).data

    def get_receipt(self, obj):
        receipt = obj.receipts.first()
        if receipt:
            return {
                'id': receipt.id,
                'receipt_number': receipt.receipt_number,
                'receipt_date': receipt.receipt_date,
                'total': receipt.total_received_amount
            }
        return None


class SupplierInvoiceCreateSerializer(serializers.ModelSerializer):
    receipt_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = SupplierInvoice
        fields = ['invoice_number', 'purchase_order', 'invoice_date', 'due_date',
                  'amount', 'tax_amount', 'total_amount', 'notes', 'receipt_id']

    def validate_invoice_number(self, value):
        if SupplierInvoice.objects.filter(invoice_number=value).exists():
            raise serializers.ValidationError(
                "Ce numéro de facture existe déjà")
        return value

    def validate_receipt_id(self, value):
        try:
            receipt = Receipt.objects.get(id=value)
        except Receipt.DoesNotExist:
            raise serializers.ValidationError("Cette réception n'existe pas")

        if receipt.status != 'completed':
            raise serializers.ValidationError(
                f"La réception {receipt.receipt_number} n'est pas terminée"
            )

        if receipt.is_invoiced:
            raise serializers.ValidationError(
                f"La réception {receipt.receipt_number} est déjà facturée"
            )

        return value

    def validate(self, data):
        purchase_order = data.get('purchase_order')
        receipt_id = data.get('receipt_id')

        if receipt_id:
            try:
                receipt = Receipt.objects.get(id=receipt_id)
                if receipt.purchase_order_id != purchase_order.id:
                    raise serializers.ValidationError(
                        f"La réception {receipt.receipt_number} n'appartient pas "
                        f"à la commande sélectionnée"
                    )

                if not data.get('amount'):
                    data['amount'] = receipt.total_received_amount
                if not data.get('total_amount'):
                    data['total_amount'] = (
                        receipt.total_received_amount +
                        data.get('tax_amount', 0)
                    )
            except Receipt.DoesNotExist:
                pass

        return data

    @transaction.atomic
    def create(self, validated_data):
        receipt_id = validated_data.pop('receipt_id')
        purchase_order = validated_data.get('purchase_order')
        supplier = purchase_order.supplier
        receipt = Receipt.objects.get(id=receipt_id)

        invoice = SupplierInvoice.objects.create(
            supplier=supplier, **validated_data)

        receipt.is_invoiced = True
        receipt.supplier_invoice = invoice
        receipt.save()

        purchase_order.update_invoice_status()

        return invoice


class SupplierInvoiceUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierInvoice
        fields = ['invoice_number', 'invoice_date', 'due_date', 'amount',
                  'tax_amount', 'total_amount', 'notes', 'status']

    def validate_invoice_number(self, value):
        if SupplierInvoice.objects.exclude(id=self.instance.id).filter(
            invoice_number=value
        ).exists():
            raise serializers.ValidationError(
                "Ce numéro de facture existe déjà")
        return value


class SupplierInvoicePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_date = serializers.DateField()
    payment_reference = serializers.CharField(required=False, allow_blank=True)
    method = serializers.CharField()
    caisse_destination_id = serializers.IntegerField(
        required=False, allow_null=True)
    compte_destination_id = serializers.IntegerField(
        required=False, allow_null=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0")
        return value

    def validate(self, data):
        caisse = data.get('caisse_destination_id')
        compte = data.get('compte_destination_id')
        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination (caisse ou compte)."
            )
        return data


# ============================================================
# PAIEMENT FOURNISSEUR - SERIALIZERS
# ============================================================

class FournisseurPaiementSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source='supplier_invoice.supplier.name', read_only=True
    )
    invoice_number = serializers.CharField(
        source='supplier_invoice.invoice_number', read_only=True
    )
    method_display = serializers.CharField(
        source='get_method_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    purchase_order_number = serializers.CharField(
        source='purchase_order.po_number', read_only=True
    )

    total_amount = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    paid_percentage = serializers.SerializerMethodField()

    amount_display = serializers.SerializerMethodField()
    qr_code_url = serializers.SerializerMethodField()
    mouvement_reference = serializers.SerializerMethodField()
    caisse_destination_nom = serializers.SerializerMethodField()
    compte_destination_nom = serializers.SerializerMethodField()

    class Meta:
        model = FournisseurPaiement
        fields = ['id', 'reference', 'supplier_invoice', 'invoice_number',
                  'supplier_name', 'purchase_order', 'purchase_order_number',
                  'amount', 'amount_display', 'method', 'method_display',
                  'reference_number', 'payment_date', 'status', 'status_display',
                  'notes', 'created_by', 'created_by_name', 'created_at',
                  'qr_code', 'qr_code_data', 'qr_code_url',
                  'caisse_destination_id', 'caisse_destination_nom',
                  'compte_destination_id', 'compte_destination_nom',
                  'mouvement_tresorerie_id', 'mouvement_reference',
                  'total_amount', 'amount_paid', 'remaining_amount', 'paid_percentage']
        read_only_fields = ['id', 'reference', 'payment_date', 'qr_code',
                            'qr_code_data', 'mouvement_tresorerie_id']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return (getattr(obj.created_by, 'full_name', None)
                    or obj.created_by.get_full_name()
                    or obj.created_by.username)
        return None

    def get_total_amount(self, obj):
        return obj.supplier_invoice.total_amount

    def get_amount_paid(self, obj):
        return obj.supplier_invoice.amount_paid

    def get_remaining_amount(self, obj):
        return obj.supplier_invoice.total_amount - obj.supplier_invoice.amount_paid

    def get_paid_percentage(self, obj):
        if obj.supplier_invoice.total_amount == 0:
            return 0
        return (obj.supplier_invoice.amount_paid
                / obj.supplier_invoice.total_amount) * 100

    def get_amount_display(self, obj):
        return f"{obj.amount:,.0f} FCFA"

    def get_qr_code_url(self, obj):
        if obj.qr_code:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_mouvement_reference(self, obj):
        if obj.mouvement_tresorerie_id:
            try:
                from tresorerie.models import MouvementTresorerie
                return MouvementTresorerie.objects.get(
                    id=obj.mouvement_tresorerie_id
                ).reference
            except Exception:
                return None
        return None

    def get_caisse_destination_nom(self, obj):
        if obj.caisse_destination_id:
            try:
                from tresorerie.models import Caisse
                return Caisse.objects.get(id=obj.caisse_destination_id).nom
            except Exception:
                return None
        return None

    def get_compte_destination_nom(self, obj):
        if obj.compte_destination_id:
            try:
                from tresorerie.models import CompteBancaire
                return CompteBancaire.objects.get(
                    id=obj.compte_destination_id
                ).nom
            except Exception:
                return None
        return None


class FournisseurPaiementCreateSerializer(serializers.ModelSerializer):
    """✅ Serializer pour la création d'un paiement fournisseur"""

    class Meta:
        model = FournisseurPaiement
        fields = ['supplier_invoice', 'purchase_order', 'amount', 'method',
                  'reference_number', 'payment_date', 'notes',
                  'caisse_destination_id', 'compte_destination_id']

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0")
        return value

    def validate(self, data):
        supplier_invoice = data.get('supplier_invoice')
        amount = data.get('amount', 0)

        if supplier_invoice:
            remaining = supplier_invoice.total_amount - supplier_invoice.amount_paid

            if amount > remaining:
                raise serializers.ValidationError({
                    "amount": (
                        f"⚠️ Le montant ({amount:,.0f} FCFA) dépasse le solde "
                        f"restant ({remaining:,.0f} FCFA)"
                    )
                })

            if supplier_invoice.is_fully_paid:
                raise serializers.ValidationError({
                    "supplier_invoice": "❌ Cette facture est déjà entièrement payée"
                })

        caisse = data.get('caisse_destination_id')
        compte = data.get('compte_destination_id')
        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination (caisse ou compte)."
            )

        if not caisse and not compte:
            raise serializers.ValidationError(
                "Veuillez sélectionner une caisse ou un compte bancaire."
            )

        return data

    @transaction.atomic
    def create(self, validated_data):
        supplier_invoice = validated_data.get('supplier_invoice')
        user = self.context['request'].user
        amount = validated_data.get('amount')

        if supplier_invoice.is_fully_paid:
            raise serializers.ValidationError({
                "supplier_invoice": "❌ Cette facture est déjà entièrement payée"
            })

        if not validated_data.get('purchase_order'):
            validated_data['purchase_order'] = supplier_invoice.purchase_order

        paiement = FournisseurPaiement.objects.create(
            status='confirmed',
            created_by=user,
            **validated_data
        )

        supplier_invoice.amount_paid += amount
        supplier_invoice.update_payment_status()

        purchase_order = paiement.purchase_order or supplier_invoice.purchase_order
        if purchase_order:
            purchase_order.update_payment_status()

        paiement.creer_mouvement_tresorerie(user)
        paiement.generate_qr_code()
        paiement.save()

        supplier_invoice.refresh_from_db()

        return paiement


# ============================================================
# DASHBOARD STATS - SERIALIZERS
# ============================================================

class AchatsDashboardStatsSerializer(serializers.Serializer):
    orders = serializers.DictField()
    receipts = serializers.DictField()
    invoices = serializers.DictField()
    suppliers = serializers.DictField()
    alerts = serializers.DictField()
