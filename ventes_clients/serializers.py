# apps/ventes_clients/serializers.py
# ============================================================
# SERIALIZERS COMPLET - AVEC WALLET CREATE
# ============================================================

from django.db import models

from produits_stocks.models import Product
from .models import LigneAvoir, LigneVente
from rest_framework import serializers
from django.db import transaction
from django.db.models import Sum
from datetime import date, timedelta
from decimal import Decimal
from .models import (
    Client, Vente, LigneVente, Paiement, Facture,
    Avoir, Taxe, Remise, Devis, LigneDevis, ClientWallet, WalletTransaction
)
from produits_stocks.models import Product, Lot, Stock, StockMovement
from produits_stocks.serializers import ProductListSerializer, LotListSerializer


# ============================================================
# CLIENT
# ============================================================

class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            'id', 'code', 'name', 'type', 'phone',
            'address', 'statut', 'notes',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        if Client.objects.exclude(id=self.instance.id if self.instance else None).filter(code=value).exists():
            raise serializers.ValidationError("Ce code client existe déjà")
        return value


class ClientListSerializer(serializers.ModelSerializer):
    """Serializer léger pour la liste des clients"""
    class Meta:
        model = Client
        fields = ['id', 'code', 'name', 'type', 'phone', 'statut']


# ============================================================
# DEVIS
# ============================================================

class LigneDevisSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)

    class Meta:
        model = LigneDevis
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'quantity', 'unit_price', 'discount', 'tax_rate', 'total', 'notes'
        ]
        read_only_fields = ['id', 'total']


class LigneDevisCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LigneDevis
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


class DevisListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    total_display = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    has_been_converted = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)

    class Meta:
        model = Devis
        fields = [
            'id', 'devis_number', 'client', 'client_name',
            'devis_date', 'valid_until', 'total', 'total_display',
            'status', 'status_display', 'is_expired', 'has_been_converted',
            'warehouse', 'warehouse_name', 'created_by'
        ]
        read_only_fields = ['id', 'devis_date', 'devis_number']

    def get_total_display(self, obj):
        return f"{obj.total:,.0f} FCFA" if obj.total else "0 FCFA"

    def get_is_expired(self, obj):
        return obj.valid_until < date.today() and obj.status not in ['accepted', 'converted']

    def get_has_been_converted(self, obj):
        return obj.status == 'converted' and obj.sale is not None


class DevisDetailSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_email = serializers.CharField(source='client.email', read_only=True)
    client_address = serializers.CharField(
        source='client.address', read_only=True)
    lignes = LigneDevisSerializer(many=True, read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)
    total_display = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    sale_info = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    warehouse_code = serializers.CharField(
        source='warehouse.code', read_only=True)

    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()

    class Meta:
        model = Devis
        fields = [
            'id', 'devis_number', 'client', 'client_name',
            'client_phone', 'client_email', 'client_address',
            'devis_date', 'valid_until',
            'subtotal', 'discount_type', 'discount_value', 'discount_amount',
            'tax_rate', 'tax_amount', 'shipping_fee', 'total', 'total_display',
            'status', 'status_display', 'is_expired',
            'notes', 'internal_notes', 'lignes', 'sale', 'sale_info',
            'warehouse', 'warehouse_name', 'warehouse_code',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'qr_code', 'qr_code_data', 'qr_code_url'
        ]
        read_only_fields = ['id', 'devis_date',
                            'devis_number', 'qr_code', 'qr_code_data']

    def get_total_display(self, obj):
        return f"{obj.total:,.0f} FCFA" if obj.total else "0 FCFA"

    def get_is_expired(self, obj):
        return obj.valid_until < date.today() and obj.status not in ['accepted', 'converted']

    def get_qr_code_url(self, obj):
        if obj.qr_code and hasattr(obj.qr_code, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_sale_info(self, obj):
        if obj.sale:
            from .serializers import VenteListSerializer
            return VenteListSerializer(obj.sale).data
        return None


class DevisCreateSerializer(serializers.ModelSerializer):
    lignes = LigneDevisCreateSerializer(many=True)

    class Meta:
        model = Devis
        fields = [
            'client', 'warehouse', 'valid_until',
            'discount_type', 'discount_value', 'tax_rate', 'shipping_fee',
            'notes', 'internal_notes', 'lignes'
        ]

    def validate_valid_until(self, value):
        if value < date.today():
            raise serializers.ValidationError(
                "La date de validité ne peut pas être dans le passé")
        return value

    def validate_lignes(self, value):
        if not value:
            raise serializers.ValidationError("Au moins un produit est requis")

        product_ids = [line.get('product')
                       for line in value if line.get('product')]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Un produit ne peut apparaître qu'une seule fois dans le devis."
            )
        return value

    def validate_warehouse(self, value):
        if not value:
            raise serializers.ValidationError("Un entrepôt est requis")
        return value

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes')
        client = validated_data.get('client')

        last_devis = Devis.objects.order_by('-id').first()
        if last_devis and last_devis.devis_number:
            try:
                num = int(last_devis.devis_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        devis_number = f"DEV-{date.today().year}-{num:04d}"

        devis = Devis.objects.create(
            devis_number=devis_number,
            client_name=client.name if client else '',
            client_phone=client.phone if client else '',
            client_email=client.email if client else '',
            client_address=client.address if client else '',
            **validated_data
        )

        for line_data in lignes_data:
            LigneDevis.objects.create(devis=devis, **line_data)

        devis.calculate_totals()
        devis.generate_qr_code()
        devis.save()

        return devis


class DevisUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Devis
        fields = [
            'valid_until', 'discount_type', 'discount_value',
            'tax_rate', 'shipping_fee', 'notes', 'internal_notes'
        ]

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        instance.calculate_totals()
        instance.generate_qr_code()
        instance.save()
        return instance


class DevisStatusUpdateSerializer(serializers.Serializer):
    status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, value):
        allowed = ['draft', 'sent', 'accepted', 'refused', 'expired']
        if value not in allowed:
            raise serializers.ValidationError(
                f"Statut invalide. Choisir parmi: {', '.join(allowed)}")
        return value


# ============================================================
# LIGNE VENTE
# ============================================================

class LigneVenteSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    price_type_display = serializers.CharField(
        source='get_price_type_display',
        read_only=True
    )
    subtotal = serializers.ReadOnlyField()
    tax_amount = serializers.ReadOnlyField()
    total_without_tax = serializers.ReadOnlyField()

    class Meta:
        model = LigneVente
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'lot', 'lot_number',
            'quantity', 'unit_price',
            'price_type', 'price_type_display',
            'discount', 'tax_rate',
            'subtotal', 'tax_amount', 'total_without_tax',
            'total', 'notes'
        ]
        read_only_fields = ['id', 'total']


class LigneVenteCreateSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour créer une ligne de vente avec choix du prix (détail ou gros)
    """
    price_type = serializers.ChoiceField(
        choices=[
            ('detail', 'Prix de détail'),
            ('gros', 'Prix de gros'),
        ],
        default='detail',
        write_only=True,
        required=False
    )

    class Meta:
        model = LigneVente
        fields = [
            'product', 'lot', 'quantity', 'unit_price',
            'discount', 'tax_rate', 'notes', 'price_type'
        ]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "La quantité doit être supérieure à 0"
            )
        return value

    def validate_unit_price(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le prix unitaire doit être supérieur à 0"
            )
        return value

    def validate(self, data):
        product_id = data.get('product')
        price_type = data.get('price_type', 'detail')

        if product_id:
            try:
                product = Product.objects.get(
                    id=product_id.id if hasattr(product_id, 'id') else product_id)

                if price_type == 'gros' and not product.wholesale_price:
                    raise serializers.ValidationError(
                        f"Le produit {product.name} n'a pas de prix de gros défini."
                    )

                if not data.get('unit_price') or data.get('unit_price') == 0:
                    if price_type == 'gros':
                        data['unit_price'] = product.wholesale_price or product.selling_price
                    else:
                        data['unit_price'] = product.selling_price

            except Product.DoesNotExist:
                raise serializers.ValidationError("Produit non trouvé")

        return data


# ============================================================
# VENTE
# ============================================================

class VenteListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    payment_status_display = serializers.CharField(
        source='get_payment_status_display', read_only=True)
    total_display = serializers.SerializerMethodField()
    has_facture = serializers.SerializerMethodField()
    from_devis = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)

    class Meta:
        model = Vente
        fields = [
            'id', 'invoice_number', 'order_number', 'client', 'client_name',
            'sale_date', 'total', 'total_display', 'status', 'status_display',
            'payment_status', 'payment_status_display', 'amount_paid', 'amount_due',
            'warehouse', 'warehouse_name', 'created_by', 'has_facture', 'from_devis'
        ]
        read_only_fields = ['id', 'sale_date', 'invoice_number']

    def get_total_display(self, obj):
        return f"{obj.total:,.0f} FCFA" if obj.total else "0 FCFA"

    def get_has_facture(self, obj):
        return obj.invoices.exists()

    def get_from_devis(self, obj):
        return obj.devis_source.filter(status='converted').exists()


class VenteDetailSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_email = serializers.CharField(source='client.email', read_only=True)
    client_address = serializers.CharField(
        source='client.address', read_only=True)
    lines = LigneVenteSerializer(many=True, read_only=True)
    payments = serializers.SerializerMethodField()
    factures = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    payment_status_display = serializers.CharField(
        source='get_payment_status_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)
    total_display = serializers.SerializerMethodField()
    from_devis = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    warehouse_code = serializers.CharField(
        source='warehouse.code', read_only=True)

    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()

    class Meta:
        model = Vente
        fields = [
            'id', 'invoice_number', 'order_number', 'client', 'client_name',
            'client_phone', 'client_email', 'client_address',
            'sale_date', 'delivery_date', 'payment_due_date',
            'subtotal', 'discount_type', 'discount_value', 'discount_amount',
            'tax_rate', 'tax_amount', 'shipping_fee', 'total', 'total_display',
            'payment_method', 'payment_status', 'payment_status_display',
            'amount_paid', 'amount_due', 'delivery_method', 'delivery_address',
            'delivery_status', 'tracking_number', 'status', 'status_display',
            'notes', 'internal_notes', 'lines', 'payments', 'factures',
            'warehouse', 'warehouse_name', 'warehouse_code',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'qr_code', 'qr_code_data', 'qr_code_url', 'from_devis'
        ]
        read_only_fields = ['id', 'sale_date',
                            'invoice_number', 'qr_code', 'qr_code_data']

    def get_total_display(self, obj):
        return f"{obj.total:,.0f} FCFA" if obj.total else "0 FCFA"

    def get_qr_code_url(self, obj):
        if obj.qr_code and hasattr(obj.qr_code, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_payments(self, obj):
        payments = []
        for facture in obj.invoices.all():
            for paiement in facture.paiements.all():
                payments.append(paiement)
        return PaiementSerializer(payments, many=True).data

    def get_factures(self, obj):
        factures = obj.invoices.all()
        return FactureSerializer(factures, many=True, context=self.context).data

    def get_from_devis(self, obj):
        return obj.devis_source.filter(status='converted').exists()


class VenteCreateSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour créer une vente avec gestion du type de prix
    """
    lines = LigneVenteCreateSerializer(many=True)

    class Meta:
        model = Vente
        fields = [
            'client', 'warehouse', 'delivery_date', 'payment_due_date',
            'discount_type', 'discount_value', 'tax_rate', 'shipping_fee',
            'payment_method', 'delivery_method', 'delivery_address',
            'notes', 'internal_notes', 'lines'
        ]

    def validate_payment_due_date(self, value):
        if value < date.today():
            raise serializers.ValidationError(
                "La date d'échéance ne peut pas être dans le passé"
            )
        return value

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Au moins un produit est requis")

        product_ids = []
        for line in value:
            product_id = line.get('product')
            if product_id:
                if hasattr(product_id, 'id'):
                    product_id = product_id.id
                product_ids.append(product_id)

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Un produit ne peut apparaître qu'une seule fois dans la vente."
            )
        return value

    def validate_warehouse(self, value):
        if not value:
            raise serializers.ValidationError("Un entrepôt est requis")
        return value

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        client = validated_data.get('client')

        # Génération du numéro de facture
        last_vente = Vente.objects.order_by('-id').first()
        if last_vente and last_vente.invoice_number:
            try:
                num = int(last_vente.invoice_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        invoice_number = f"INV-{date.today().year}-{num:04d}"

        if client:
            client_name = client.name or ''
            client_phone = client.phone or ''
            client_address = client.address or ''
        else:
            client_name = 'Client anonyme'
            client_phone = ''
            client_address = ''
            client = Client.create_anonymous(created_by=self.context.get(
                'request').user if self.context.get('request') else None)
            validated_data['client'] = client

        # Création de la vente
        vente = Vente.objects.create(
            invoice_number=invoice_number,
            client_name=client_name,
            client_phone=client_phone,
            client_email='',
            client_address=client_address,
            **validated_data
        )

        # Création des lignes
        for line_data in lines_data:
            line_data.pop('price_type', None)
            LigneVente.objects.create(sale=vente, **line_data)

        vente.calculate_totals()
        vente.generate_qr_code()
        vente.save()

        return vente


class VenteUpdateSerializer(serializers.ModelSerializer):
    lines = LigneVenteCreateSerializer(many=True, required=False)

    class Meta:
        model = Vente
        fields = [
            'delivery_date', 'payment_due_date', 'discount_type',
            'discount_value', 'tax_rate', 'shipping_fee',
            'payment_method', 'delivery_method', 'delivery_address',
            'notes', 'internal_notes', 'tracking_number', 'lines'
        ]

    def validate_lines(self, value):
        if value is None:
            return value

        if not value:
            raise serializers.ValidationError("Au moins un produit est requis")

        product_ids = []
        for line in value:
            product_id = line.get('product')
            if product_id:
                if hasattr(product_id, 'id'):
                    product_id = product_id.id
                product_ids.append(product_id)

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Un produit ne peut apparaître qu'une seule fois dans la vente."
            )
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                line_data.pop('price_type', None)
                LigneVente.objects.create(sale=instance, **line_data)

        instance.calculate_totals()
        instance.generate_qr_code()
        instance.save()
        return instance


class VenteStatusUpdateSerializer(serializers.Serializer):
    status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, value):
        allowed = ['draft', 'confirmed', 'paid',
                   'delivered', 'cancelled', 'returned']
        if value not in allowed:
            raise serializers.ValidationError(
                f"Statut invalide. Choisir parmi: {', '.join(allowed)}")
        return value


# ============================================================
# FACTURE
# ============================================================

class FactureSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    sale_number = serializers.CharField(
        source='sale.invoice_number', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    remaining_amount = serializers.ReadOnlyField()
    paiements = serializers.SerializerMethodField()
    total_display = serializers.SerializerMethodField()
    remaining_display = serializers.SerializerMethodField()

    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()

    class Meta:
        model = Facture
        fields = [
            'id', 'invoice_number', 'sale', 'sale_number', 'client', 'client_name',
            'invoice_date', 'due_date', 'subtotal', 'tax_amount', 'total',
            'total_display', 'amount_paid', 'remaining_amount', 'remaining_display',
            'status', 'status_display',
            'pdf_file', 'notes', 'paiements',
            'qr_code', 'qr_code_data', 'qr_code_url',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'invoice_date', 'qr_code', 'qr_code_data']

    def get_qr_code_url(self, obj):
        if obj.qr_code and hasattr(obj.qr_code, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

    def get_paiements(self, obj):
        paiements = obj.paiements.all()
        return PaiementSerializer(paiements, many=True).data

    def get_total_display(self, obj):
        return f"{obj.total:,.0f} FCFA" if obj.total else "0 FCFA"

    def get_remaining_display(self, obj):
        return f"{obj.remaining_amount:,.0f} FCFA" if obj.remaining_amount else "0 FCFA"


class FactureCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Facture
        fields = ['sale', 'due_date', 'notes']

    def validate(self, data):
        sale = data.get('sale')
        if sale and sale.status in ['cancelled']:
            raise serializers.ValidationError(
                "Cette vente ne peut pas être facturée")

        if sale and Facture.objects.filter(sale=sale).exists():
            raise serializers.ValidationError(
                "Une facture existe déjà pour cette vente")

        return data

    @transaction.atomic
    def create(self, validated_data):
        sale = validated_data.get('sale')
        client = sale.client

        if not client:
            client = Client.create_anonymous()
            sale.client = client
            sale.client_name = client.name
            sale.save(update_fields=['client', 'client_name'])

        last_facture = Facture.objects.order_by('-id').first()
        if last_facture and last_facture.invoice_number:
            try:
                num = int(last_facture.invoice_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        invoice_number = f"FAC-{date.today().year}-{num:04d}"

        facture = Facture.objects.create(
            invoice_number=invoice_number,
            client=client,
            subtotal=sale.subtotal,
            tax_amount=sale.tax_amount,
            total=sale.total,
            **validated_data
        )

        facture.generate_qr_code()
        facture.save()

        return facture


# ============================================================
# PAIEMENT
# ============================================================

class PaiementSerializer(serializers.ModelSerializer):
    method_display = serializers.CharField(
        source='get_method_display', read_only=True)
    received_by_name = serializers.CharField(
        source='received_by.full_name', read_only=True)

    facture_number = serializers.CharField(
        source='facture.invoice_number', read_only=True)
    client_name = serializers.CharField(
        source='facture.client.name', read_only=True)
    remaining_amount = serializers.SerializerMethodField()
    facture_total = serializers.SerializerMethodField()
    amount_display = serializers.SerializerMethodField()

    qr_code = serializers.ImageField(read_only=True)
    qr_code_data = serializers.CharField(read_only=True)
    qr_code_url = serializers.SerializerMethodField()

    caisse_destination_nom = serializers.CharField(
        source='caisse_destination.nom', read_only=True)
    compte_destination_nom = serializers.CharField(
        source='compte_destination.nom', read_only=True)

    class Meta:
        model = Paiement
        fields = [
            'id',
            'facture', 'facture_number',
            'client_name',
            'amount', 'amount_display',
            'method', 'method_display',
            'reference',
            'payment_date',
            'received_by', 'received_by_name',
            'remaining_amount',
            'facture_total',
            'notes',
            'qr_code', 'qr_code_data', 'qr_code_url',
            'caisse_destination', 'caisse_destination_nom',
            'compte_destination', 'compte_destination_nom',
        ]
        read_only_fields = ['id', 'payment_date', 'qr_code', 'qr_code_data']

    def get_remaining_amount(self, obj):
        return obj.facture.remaining_amount

    def get_facture_total(self, obj):
        return obj.facture.total

    def get_amount_display(self, obj):
        return f"{obj.amount:,.0f} FCFA" if obj.amount else "0 FCFA"

    def get_qr_code_url(self, obj):
        if obj.qr_code and hasattr(obj.qr_code, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.qr_code.url)
            return obj.qr_code.url
        return None

# apps/ventes_clients/serializers.py


class PaiementCreateSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour la création d'un paiement
    """
    class Meta:
        model = Paiement
        fields = [
            'facture', 'amount', 'method', 'reference', 'notes',
            'caisse_destination', 'compte_destination'
        ]
        extra_kwargs = {
            'method': {
                'error_messages': {
                    'invalid_choice': 'Méthode de paiement invalide. Choisissez parmi: cash, card, check, transfer, mobile_money, credit, wallet'
                }
            }
        }

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0"
            )
        return value

    def validate_method(self, value):
        """
        Valide que la méthode de paiement est valide
        """
        valid_methods = ['cash', 'card', 'check',
                         'transfer', 'mobile_money', 'credit', 'wallet']
        if value not in valid_methods:
            raise serializers.ValidationError(
                f"Méthode de paiement invalide. Choisissez parmi: {', '.join(valid_methods)}"
            )
        return value

    def validate(self, data):
        facture = data.get('facture')
        amount = data.get('amount', 0)
        method = data.get('method')

        # Vérifier que la facture existe
        if not facture:
            raise serializers.ValidationError(
                {"facture": "La facture est requise"}
            )

        # Vérifier le montant restant
        if amount > facture.remaining_amount:
            raise serializers.ValidationError(
                {"amount": f"Le montant dépasse le solde restant ({facture.remaining_amount:,.0f} FCFA)"}
            )

        # Vérifier la destination unique
        caisse = data.get('caisse_destination')
        compte = data.get('compte_destination')

        if caisse and compte:
            raise serializers.ValidationError(
                "Choisissez une seule destination (caisse ou compte)."
            )

        # Si méthode wallet, pas besoin de destination
        if method == 'wallet':
            # Le wallet ne nécessite pas de destination
            pass
        else:
            # Pour les autres méthodes, vérifier qu'il y a une destination
            if not caisse and not compte:
                raise serializers.ValidationError(
                    "Veuillez spécifier une destination (caisse ou compte) pour le paiement."
                )

            # Vérifier que la destination appartient au bon entrepôt
            if facture and facture.sale and facture.sale.warehouse:
                warehouse = facture.sale.warehouse
                if caisse and caisse.warehouse != warehouse:
                    raise serializers.ValidationError(
                        {"caisse_destination": "La caisse choisie n'appartient pas à l'entrepôt de la vente."}
                    )
                if compte and compte.warehouse != warehouse:
                    raise serializers.ValidationError(
                        {"compte_destination": "Le compte bancaire choisi n'appartient pas à l'entrepôt de la vente."}
                    )

        return data

# ============================================================
# AVOIR
# ============================================================


# ============================================================
# LIGNE AVOIR
# ============================================================
# ============================================================
# LIGNE AVOIR
# ============================================================
# ============================================================
# LIGNE AVOIR
# ============================================================
class LigneAvoirSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = LigneAvoir
        fields = [
            "id", "product", "product_name", "product_code",
            "ligne_vente", "quantity", "unit_price",
            "discount", "total", "notes",
        ]


class LigneAvoirCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LigneAvoir
        fields = [
            "product", "ligne_vente",
            "quantity", "unit_price", "discount", "notes",
        ]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être > 0")
        return value


# ============================================================
# AVOIR — LECTURE
# ============================================================
class AvoirSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    client_phone = serializers.CharField(source="client.phone", read_only=True)
    sale_number = serializers.CharField(
        source="sale.invoice_number", read_only=True)
    type_display = serializers.CharField(
        source="get_type_display", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True
    )
    lignes = LigneAvoirSerializer(many=True, read_only=True)

    class Meta:
        model = Avoir
        fields = [
            "id", "avoir_number", "sale", "sale_number",
            "client", "client_name", "client_phone",
            "type", "type_display", "amount",
            "reason", "date", "notes",
            "restore_stock", "stock_restored_at",
            "lignes",
            "created_by", "created_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "avoir_number", "date",
            "restore_stock", "stock_restored_at",
            "created_at", "updated_at",
        ]


# ============================================================
# AVOIR — CRÉATION
# ============================================================
class AvoirCreateSerializer(serializers.ModelSerializer):
    lignes = LigneAvoirCreateSerializer(many=True, required=False)
    restore_stock = serializers.BooleanField(
        default=False, write_only=True, required=False
    )

    class Meta:
        model = Avoir
        fields = [
            "sale", "client", "type", "amount",
            "reason", "notes", "lignes", "restore_stock",
        ]
        extra_kwargs = {"amount": {"required": False}}

    def validate_type(self, value):
        valid = ["refund", "return", "discount", "error"]
        if value not in valid:
            raise serializers.ValidationError(
                f"Type invalide. Choisir parmi : {', '.join(valid)}"
            )
        return value

    def validate(self, data):
        sale = data.get("sale")
        lignes = data.get("lignes", [])
        amount = data.get("amount", 0)
        avoir_type = data.get("type")

        if sale and not lignes and amount > sale.total:
            raise serializers.ValidationError({
                "amount": f"Le montant ne peut pas dépasser {sale.total:,.0f} FCFA"
            })

        if sale and sale.status == "cancelled":
            raise serializers.ValidationError({
                "sale": "Impossible de créer un avoir sur une vente annulée"
            })

        if avoir_type == "return" and not sale:
            raise serializers.ValidationError({
                "sale": "Une vente est requise pour un avoir de type 'return'"
            })

        # Validation des lignes
        if lignes and sale:
            product_ids = [l["product"].id for l in lignes]
            if len(product_ids) != len(set(product_ids)):
                raise serializers.ValidationError({
                    "lignes": "Un produit ne peut apparaître qu'une seule fois"
                })

            for l in lignes:
                product = l["product"]
                qty = l["quantity"]
                vente_ligne = sale.lines.filter(product=product).first()

                if not vente_ligne:
                    raise serializers.ValidationError({
                        "lignes": f"{product.name} n'est pas dans la vente"
                    })

                if qty > vente_ligne.quantity:
                    raise serializers.ValidationError({
                        "lignes": f"Quantité ({qty}) > vendue ({vente_ligne.quantity}) pour {product.name}"
                    })

                deja = (
                    LigneAvoir.objects
                    .filter(ligne_vente=vente_ligne)
                    .aggregate(total=models.Sum("quantity"))["total"] or 0
                )
                if deja + qty > vente_ligne.quantity:
                    raise serializers.ValidationError({
                        "lignes": f"Retours cumulés ({deja + qty}) > vendue ({vente_ligne.quantity}) pour {product.name}"
                    })

        return data

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop("lignes", [])
        validated_data.pop("restore_stock", None)

        # Calcul auto du montant
        if lignes_data:
            total = sum(
                (l["quantity"] * l["unit_price"]) - l.get("discount", 0)
                for l in lignes_data
            )
            validated_data["amount"] = total

        avoir = Avoir.objects.create(**validated_data)

        for ligne_data in lignes_data:
            LigneAvoir.objects.create(avoir=avoir, **ligne_data)

        return avoir

# ============================================================
# AVOIR
# ============================================================


class TaxeSerializer(serializers.ModelSerializer):
    rate_display = serializers.SerializerMethodField()

    class Meta:
        model = Taxe
        fields = ['id', 'name', 'rate',
                  'rate_display', 'is_default', 'is_active']
        read_only_fields = ['id']

    def get_rate_display(self, obj):
        return f"{obj.rate}%"


# ============================================================
# REMISE
# ============================================================

class RemiseSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    clients_count = serializers.SerializerMethodField()
    value_display = serializers.SerializerMethodField()

    class Meta:
        model = Remise
        fields = [
            'id', 'name', 'type', 'type_display', 'value', 'value_display',
            'min_purchase', 'start_date', 'end_date',
            'is_active', 'clients', 'clients_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_clients_count(self, obj):
        return obj.clients.count()

    def get_value_display(self, obj):
        if obj.type == 'percentage':
            return f"{obj.value}%"
        return f"{obj.value:,.0f} FCFA"


# ============================================================
# DASHBOARD STATS SERIALIZERS
# ============================================================

class SalesSummarySerializer(serializers.Serializer):
    sales = serializers.DictField()
    amounts = serializers.DictField()
    payments = serializers.DictField()
    clients = serializers.DictField()
    invoices = serializers.DictField()
    devis = serializers.DictField()


class SalesTrendSerializer(serializers.Serializer):
    date = serializers.DateField()
    total_sales = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class TopProductsSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity_sold = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class TopClientsSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    client_name = serializers.CharField()
    total_orders = serializers.IntegerField()
    total_purchases = serializers.DecimalField(max_digits=15, decimal_places=2)


class DevisStatsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    acceptes = serializers.IntegerField()
    expires = serializers.IntegerField()
    convertis = serializers.IntegerField()


# ============================================================
# WALLET SERIALIZERS
# ============================================================

# apps/ventes_clients/serializers.py - Modifier ClientWalletSerializer

class ClientWalletSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    client_code = serializers.CharField(source='client.code', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_type = serializers.CharField(source='client.type', read_only=True)
    client_statut = serializers.CharField(
        source='client.statut', read_only=True)
    balance_display = serializers.SerializerMethodField()

    class Meta:
        model = ClientWallet
        fields = [
            'id',
            'client',
            'client_name',
            'client_code',
            'client_phone',
            'client_type',
            'client_statut',
            'balance',
            'balance_display',
            'total_deposits',
            'total_used',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'balance', 'total_deposits', 'total_used']

    def get_balance_display(self, obj):
        return f"{obj.balance:,.0f} FCFA"


class WalletTransactionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_display', read_only=True)
    source_display = serializers.CharField(
        source='get_source_display', read_only=True)
    amount_display = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.full_name', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'type', 'type_display',
            'amount', 'amount_display',
            'source', 'source_display',
            'reference', 'notes',
            'balance_after', 'created_at',
            'created_by', 'created_by_name'
        ]

    def get_amount_display(self, obj):
        return f"{obj.amount:,.0f} FCFA"


class WalletDepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=['cash', 'card', 'transfer', 'mobile_money'],
        default='cash'
    )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0")
        return value


class WalletPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    sale_id = serializers.IntegerField()
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Le montant doit être supérieur à 0")
        return value

    def validate_sale_id(self, value):
        try:
            sale = Vente.objects.get(id=value)
            if sale.status == 'cancelled':
                raise serializers.ValidationError("Cette vente est annulée")
            return value
        except Vente.DoesNotExist:
            raise serializers.ValidationError("Vente non trouvée")


# ============================================================
# ✅ NOUVEAU : CLIENT WALLET CREATE SERIALIZER
# ============================================================

class ClientWalletCreateSerializer(serializers.Serializer):
    """
    Serializer pour la création d'un wallet
    """
    client_id = serializers.IntegerField(required=True)
    initial_balance = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        required=False
    )

    def validate_client_id(self, value):
        try:
            client = Client.objects.get(id=value)
            # Vérifier si le client a déjà un wallet
            if hasattr(client, 'wallet'):
                raise serializers.ValidationError(
                    "Ce client a déjà un porte-monnaie"
                )
            return value
        except Client.DoesNotExist:
            raise serializers.ValidationError(
                f"Client avec l'ID {value} non trouvé"
            )

    def validate_initial_balance(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Le solde initial ne peut pas être négatif"
            )
        return value
