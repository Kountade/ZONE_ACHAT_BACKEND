# apps/achats_fournisseurs/purchase_alerts.py
from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from django.db.models import Q, Count, Sum, F
from .models import PurchaseOrder, Receipt, PurchaseReturn, SupplierInvoice, Supplier
from produits_stocks.models import Product, Lot
import logging

logger = logging.getLogger(__name__)


class PurchaseAlert:
    """
    Classe pour gérer les alertes liées aux achats fournisseurs
    """

    # ==================== COMMANDES ====================
    @staticmethod
    def check_overdue_orders():
        """Vérifie les commandes en retard de livraison"""
        today = date.today()
        overdue_orders = PurchaseOrder.objects.filter(
            status__in=['draft', 'sent', 'confirmed', 'partial'],
            expected_delivery_date__lt=today
        ).select_related('supplier')

        alerts = []
        for order in overdue_orders:
            days_late = (today - order.expected_delivery_date).days
            alerts.append({
                'type': 'overdue_order',
                'level': 'error',
                'message': f"Commande {order.po_number} en retard de {days_late} jours",
                'order_id': order.id,
                'order_number': order.po_number,
                'supplier_name': order.supplier.name if order.supplier else 'N/A',
                'days_late': days_late
            })

        return alerts

    @staticmethod
    def check_orders_receiving_soon():
        """Vérifie les commandes à réceptionner bientôt (3 jours)"""
        today = date.today()
        soon_date = today + timedelta(days=3)

        upcoming_orders = PurchaseOrder.objects.filter(
            status__in=['sent', 'confirmed'],
            expected_delivery_date__gte=today,
            expected_delivery_date__lte=soon_date
        ).select_related('supplier')

        alerts = []
        for order in upcoming_orders:
            days_until = (order.expected_delivery_date - today).days
            alerts.append({
                'type': 'upcoming_receipt',
                'level': 'info',
                'message': f"Commande {order.po_number} à réceptionner dans {days_until} jours",
                'order_id': order.id,
                'order_number': order.po_number,
                'supplier_name': order.supplier.name if order.supplier else 'N/A',
                'days_until': days_until
            })

        return alerts

    @staticmethod
    def check_orders_with_no_receipt():
        """Vérifie les commandes confirmées sans réception depuis 7 jours"""
        threshold_date = date.today() - timedelta(days=7)

        orders_without_receipt = PurchaseOrder.objects.filter(
            status='confirmed',
            order_date__date__lte=threshold_date
        ).exclude(
            receipts__status__in=['completed', 'in_progress']
        ).select_related('supplier')

        alerts = []
        for order in orders_without_receipt:
            days_waiting = (date.today() - order.order_date.date()).days
            alerts.append({
                'type': 'no_receipt',
                'level': 'warning',
                'message': f"Commande {order.po_number} sans réception depuis {days_waiting} jours",
                'order_id': order.id,
                'order_number': order.po_number,
                'supplier_name': order.supplier.name if order.supplier else 'N/A',
                'days_waiting': days_waiting
            })

        return alerts

    # ==================== FACTURES ====================
    @staticmethod
    def check_overdue_invoices():
        """Vérifie les factures en retard de paiement"""
        today = date.today()
        overdue_invoices = SupplierInvoice.objects.filter(
            status__in=['received', 'verified', 'partial'],
            due_date__lt=today
        ).select_related('supplier', 'purchase_order')

        alerts = []
        for invoice in overdue_invoices:
            days_late = (today - invoice.due_date).days
            alerts.append({
                'type': 'overdue_invoice',
                'level': 'error',
                'message': f"Facture {invoice.invoice_number} en retard de {days_late} jours",
                'invoice_id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'supplier_name': invoice.supplier.name if invoice.supplier else 'N/A',
                'amount': str(invoice.remaining_amount),
                'days_late': days_late
            })

        return alerts

    @staticmethod
    def check_invoices_due_soon():
        """Vérifie les factures à échéance proche (5 jours)"""
        today = date.today()
        soon_date = today + timedelta(days=5)

        upcoming_invoices = SupplierInvoice.objects.filter(
            status__in=['received', 'verified'],
            due_date__gte=today,
            due_date__lte=soon_date
        ).select_related('supplier', 'purchase_order')

        alerts = []
        for invoice in upcoming_invoices:
            days_until = (invoice.due_date - today).days
            alerts.append({
                'type': 'upcoming_invoice_due',
                'level': 'info',
                'message': f"Facture {invoice.invoice_number} à payer dans {days_until} jours",
                'invoice_id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'supplier_name': invoice.supplier.name if invoice.supplier else 'N/A',
                'amount': str(invoice.remaining_amount),
                'days_until': days_until
            })

        return alerts

    # ==================== STOCKS ====================
    @staticmethod
    def check_low_stock_products():
        """Vérifie les produits avec un stock bas"""
        # Note: Adaptez selon votre modèle Product
        low_stock_products = Product.objects.filter(
            current_stock__lte=5,
            current_stock__gt=0
        ).select_related('unit')

        alerts = []
        for product in low_stock_products:
            alerts.append({
                'type': 'low_stock',
                'level': 'warning',
                'message': f"Stock bas pour {product.name} ({product.current_stock} {product.unit.symbol if product.unit else 'unités'})",
                'product_id': product.id,
                'product_name': product.name,
                'current_stock': product.current_stock,
                'threshold': 5
            })

        return alerts

    @staticmethod
    def check_expiring_lots():
        """Vérifie les lots qui vont expirer bientôt (30 jours)"""
        today = date.today()
        soon_date = today + timedelta(days=30)

        expiring_lots = Lot.objects.filter(
            expiry_date__isnull=False,
            expiry_date__gte=today,
            expiry_date__lte=soon_date,
            current_quantity__gt=0
        ).select_related('product', 'warehouse')

        alerts = []
        for lot in expiring_lots:
            days_until = (lot.expiry_date - today).days
            alerts.append({
                'type': 'expiring_lot',
                'level': 'warning',
                'message': f"Lot {lot.lot_number} expire dans {days_until} jours",
                'lot_id': lot.id,
                'lot_number': lot.lot_number,
                'product_name': lot.product.name if lot.product else 'N/A',
                'days_until': days_until,
                'quantity': lot.current_quantity
            })

        return alerts

    @staticmethod
    def check_expired_lots():
        """Vérifie les lots déjà expirés"""
        today = date.today()

        expired_lots = Lot.objects.filter(
            expiry_date__isnull=False,
            expiry_date__lt=today,
            current_quantity__gt=0
        ).select_related('product', 'warehouse')

        alerts = []
        for lot in expired_lots:
            days_overdue = (today - lot.expiry_date).days
            alerts.append({
                'type': 'expired_lot',
                'level': 'error',
                'message': f"Lot {lot.lot_number} expiré depuis {days_overdue} jours",
                'lot_id': lot.id,
                'lot_number': lot.lot_number,
                'product_name': lot.product.name if lot.product else 'N/A',
                'days_overdue': days_overdue,
                'quantity': lot.current_quantity
            })

        return alerts

    # ==================== FOURNISSEURS ====================
    @staticmethod
    def check_suppliers_with_high_delays():
        """Vérifie les fournisseurs avec un taux de retard élevé"""
        suppliers = Supplier.objects.annotate(
            total_orders=Count('purchase_orders'),
            delayed_orders=Count('purchase_orders', filter=Q(
                purchase_orders__actual_delivery_date__gt=F(
                    'purchase_orders__expected_delivery_date')
            ))
        ).filter(
            total_orders__gte=3
        )

        alerts = []
        for supplier in suppliers:
            if supplier.total_orders > 0:
                delay_rate = (supplier.delayed_orders /
                              supplier.total_orders) * 100
                if delay_rate > 50:  # Plus de 50% de retard
                    alerts.append({
                        'type': 'supplier_high_delay',
                        'level': 'warning',
                        'message': f"Fournisseur {supplier.name} a un taux de retard de {delay_rate:.1f}%",
                        'supplier_id': supplier.id,
                        'supplier_name': supplier.name,
                        'delay_rate': round(delay_rate, 1),
                        'delayed_orders': supplier.delayed_orders,
                        'total_orders': supplier.total_orders
                    })

        return alerts

    @staticmethod
    def check_suppliers_with_low_rating():
        """Vérifie les fournisseurs avec une note inférieure à 3"""
        low_rated_suppliers = Supplier.objects.filter(
            is_active=True,
            rating__lt=3,
            rating__gt=0
        )

        alerts = []
        for supplier in low_rated_suppliers:
            alerts.append({
                'type': 'supplier_low_rating',
                'level': 'warning',
                'message': f"Fournisseur {supplier.name} a une note de {supplier.rating}/5",
                'supplier_id': supplier.id,
                'supplier_name': supplier.name,
                'rating': float(supplier.rating)
            })

        return alerts

    # ==================== RETOURS ====================
    @staticmethod
    def check_pending_returns():
        """Vérifie les retours en attente depuis plus de 3 jours"""
        threshold_date = date.today() - timedelta(days=3)

        pending_returns = PurchaseReturn.objects.filter(
            status='requested',
            return_date__date__lte=threshold_date
        ).select_related('purchase_order__supplier', 'purchase_order')

        alerts = []
        for return_item in pending_returns:
            days_waiting = (date.today() - return_item.return_date.date()).days
            alerts.append({
                'type': 'pending_return',
                'level': 'warning',
                'message': f"Retour {return_item.return_number} en attente depuis {days_waiting} jours",
                'return_id': return_item.id,
                'return_number': return_item.return_number,
                'supplier_name': return_item.purchase_order.supplier.name if return_item.purchase_order and return_item.purchase_order.supplier else 'N/A',
                'days_waiting': days_waiting
            })

        return alerts

    # ==================== ALERTES GLOBALES ====================
    @staticmethod
    def get_all_alerts():
        """Récupère toutes les alertes"""
        alerts = []

        # Alertes commandes
        alerts.extend(PurchaseAlert.check_overdue_orders())
        alerts.extend(PurchaseAlert.check_orders_receiving_soon())
        alerts.extend(PurchaseAlert.check_orders_with_no_receipt())

        # Alertes factures
        alerts.extend(PurchaseAlert.check_overdue_invoices())
        alerts.extend(PurchaseAlert.check_invoices_due_soon())

        # Alertes stocks
        alerts.extend(PurchaseAlert.check_low_stock_products())
        alerts.extend(PurchaseAlert.check_expiring_lots())
        alerts.extend(PurchaseAlert.check_expired_lots())

        # Alertes fournisseurs
        alerts.extend(PurchaseAlert.check_suppliers_with_high_delays())
        alerts.extend(PurchaseAlert.check_suppliers_with_low_rating())

        # Alertes retours
        alerts.extend(PurchaseAlert.check_pending_returns())

        # Ajouter un ID unique
        for i, alert in enumerate(alerts):
            alert['id'] = i + 1
            alert['created_at'] = timezone.now().isoformat()

        return alerts

    @staticmethod
    def get_alerts_count():
        """Récupère le nombre d'alertes par niveau"""
        alerts = PurchaseAlert.get_all_alerts()

        counts = {
            'total': len(alerts),
            'error': len([a for a in alerts if a.get('level') == 'error']),
            'warning': len([a for a in alerts if a.get('level') == 'warning']),
            'info': len([a for a in alerts if a.get('level') == 'info'])
        }

        return counts
