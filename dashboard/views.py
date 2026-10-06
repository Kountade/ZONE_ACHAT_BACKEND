from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import date, timedelta
import logging

from users.models import CustomUser
from produits_stocks.models import Product, Stock, Warehouse, Lot, StockMovement
from ventes_clients.models import Vente, Client, Facture, Devis, LigneVente
from achats_fournisseurs.models import PurchaseOrder, Supplier, Receipt, SupplierInvoice
from tresorerie.models import Caisse, CompteBancaire, MouvementTresorerie

from .serializers import (
    DashboardSummarySerializer, SalesStatsSerializer,
    CashFlowSerializer, TopProductsSerializer, TopClientsSerializer,
    ActivitySerializer
)

logger = logging.getLogger(__name__)


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        try:
            today = timezone.now().date()
            start_of_month = today.replace(day=1)

            # --- Produits ---
            total_products = Product.objects.filter(status='active').count()
            low_stock_products = 0
            out_of_stock_products = 0
            total_stock_value = 0

            for product in Product.objects.filter(status='active'):
                stock_qty = product.current_stock
                if stock_qty <= 0:
                    out_of_stock_products += 1
                elif stock_qty <= product.min_stock:
                    low_stock_products += 1
                total_stock_value += stock_qty * product.purchase_price

            # --- Ventes ---
            sales_this_month = Vente.objects.filter(
                status__in=['confirmed', 'paid', 'delivered'],
                sale_date__date__gte=start_of_month
            )
            total_sales_count = sales_this_month.count()
            total_sales_amount = sales_this_month.aggregate(total=Sum('total'))[
                'total'] or 0

            # --- Achats ---
            purchases_this_month = PurchaseOrder.objects.filter(
                status__in=['received', 'confirmed'],
                order_date__date__gte=start_of_month
            )
            total_purchases_count = purchases_this_month.count()
            total_purchases_amount = purchases_this_month.aggregate(total=Sum('total'))[
                'total'] or 0

            # --- Trésorerie ---
            total_cash = Caisse.objects.filter(is_active=True).aggregate(
                total=Sum('solde_actuel')
            )['total'] or 0
            total_bank = CompteBancaire.objects.filter(is_active=True).aggregate(
                total=Sum('solde_actuel')
            )['total'] or 0

            # --- Alertes ---
            low_stock_alerts = Stock.objects.filter(
                quantity__lte=F('product__min_stock')
            ).count()
            expiring_lots = Lot.objects.filter(
                expiry_date__lte=today + timedelta(days=30),
                expiry_date__gte=today,
                current_quantity__gt=0
            ).count()
            overdue_invoices = Facture.objects.filter(
                due_date__lt=today,
                status__in=['sent', 'partial']
            ).count()

            # ============================================================
            # ✅ NOUVEAU : CRÉANCES CLIENTS (MONTANTS NON PAYÉS)
            # ============================================================
            # On récupère toutes les factures non soldées
            factures_impayees = Facture.objects.filter(
                status__in=['sent', 'partial', 'overdue']
            ).exclude(status='paid').select_related('client')

            total_receivables = 0
            receivables_by_client = {}

            for facture in factures_impayees:
                # remaining_amount est une @property : total - amount_paid
                remaining = facture.remaining_amount
                if remaining > 0:
                    total_receivables += remaining
                    client_name = (
                        facture.client.name
                        if facture.client
                        else "Client inconnu"
                    )
                    if client_name not in receivables_by_client:
                        receivables_by_client[client_name] = {
                            'client_id': facture.client.id if facture.client else None,
                            'client_name': client_name,
                            'total_due': 0,
                            'invoices_count': 0,
                        }
                    receivables_by_client[client_name]['total_due'] += remaining
                    receivables_by_client[client_name]['invoices_count'] += 1

            # Nombre de factures réellement impayées (remaining > 0)
            unpaid_invoices_count = len(receivables_by_client) and sum(
                c['invoices_count'] for c in receivables_by_client.values()
            ) or 0

            # Factures en retard (parmi les impayées)
            overdue_count = factures_impayees.filter(
                due_date__lt=today
            ).count()

            # Top 5 des clients les plus endettés
            top_debtors = sorted(
                receivables_by_client.values(),
                key=lambda x: x['total_due'],
                reverse=True
            )[:5]

            # --- Activités récentes ---
            recent_activities = []

            # Dernières ventes
            recent_sales = Vente.objects.filter(
                status__in=['confirmed', 'paid']
            ).order_by('-sale_date')[:5]
            for sale in recent_sales:
                recent_activities.append({
                    'type': 'vente',
                    'reference': sale.invoice_number,
                    'date': sale.sale_date,
                    'amount': sale.total,
                    'user': sale.created_by.get_full_name() if sale.created_by else None
                })

            # Derniers achats
            recent_purchases = PurchaseOrder.objects.filter(
                status__in=['confirmed', 'received']
            ).order_by('-order_date')[:5]
            for po in recent_purchases:
                recent_activities.append({
                    'type': 'achat',
                    'reference': po.po_number,
                    'date': po.order_date,
                    'amount': po.total,
                    'user': po.created_by.get_full_name() if po.created_by else None
                })

            # Derniers mouvements de trésorerie
            recent_movements = MouvementTresorerie.objects.filter(
                status='effectue'
            ).order_by('-date_mouvement')[:5]
            for mvmt in recent_movements:
                recent_activities.append({
                    'type': 'mouvement',
                    'reference': mvmt.reference,
                    'date': mvmt.date_mouvement,
                    'amount': mvmt.montant,
                    'user': mvmt.created_by.get_full_name() if mvmt.created_by else None,
                    'info': mvmt.libelle
                })

            recent_activities.sort(key=lambda x: x['date'], reverse=True)
            recent_activities = recent_activities[:10]

            # ============================================================
            # RÉPONSE
            # ============================================================
            data = {
                'products': {
                    'total': total_products,
                    'low_stock': low_stock_products,
                    'out_of_stock': out_of_stock_products,
                    'total_stock_value': total_stock_value,
                },
                'sales': {
                    'total_count': total_sales_count,
                    'total_amount': total_sales_amount,
                    'this_month': start_of_month.strftime('%Y-%m-%d'),
                },
                'purchases': {
                    'total_count': total_purchases_count,
                    'total_amount': total_purchases_amount,
                    'this_month': start_of_month.strftime('%Y-%m-%d'),
                },
                'cash': {
                    'total_cash': total_cash,
                    'total_bank': total_bank,
                    'total_available': total_cash + total_bank,
                },
                'alerts': {
                    'low_stock': low_stock_alerts,
                    'expiring_lots': expiring_lots,
                    'overdue_invoices': overdue_invoices,
                },
                # ✅ NOUVEAU BLOC
                'receivables': {
                    'total': float(total_receivables),
                    'invoices_count': unpaid_invoices_count,
                    'overdue_count': overdue_count,
                    'top_debtors': [
                        {
                            'client_id': d['client_id'],
                            'client_name': d['client_name'],
                            'total_due': float(d['total_due']),
                            'invoices_count': d['invoices_count'],
                        }
                        for d in top_debtors
                    ],
                },
                'recent_activities': recent_activities,
            }

            serializer = DashboardSummarySerializer(data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Erreur dans dashboard.summary: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class StatistiqueViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='sales')
    def sales_stats(self, request):
        try:
            period = request.query_params.get('period', 'month')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response(
                        {'error': 'Format de date invalide. Utilisez YYYY-MM-DD.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                today = timezone.now().date()
                if period == 'day':
                    start = end = today
                elif period == 'week':
                    start = today - timedelta(days=today.weekday())
                    end = today
                elif period == 'month':
                    start = today.replace(day=1)
                    end = today
                elif period == 'year':
                    start = today.replace(month=1, day=1)
                    end = today
                else:
                    start = today.replace(day=1)
                    end = today

            ventes = Vente.objects.filter(
                status__in=['confirmed', 'paid'],
                sale_date__date__gte=start,
                sale_date__date__lte=end
            )

            total_sales = ventes.count()
            total_amount = ventes.aggregate(total=Sum('total'))['total'] or 0
            avg_order = total_amount / total_sales if total_sales > 0 else 0

            status_counts = {}
            for code, _ in Vente.STATUS_CHOICES:
                count = ventes.filter(status=code).count()
                if count:
                    status_counts[code] = count

            data = {
                'period': f'{start} - {end}',
                'total_sales': total_sales,
                'total_amount': total_amount,
                'average_order': avg_order,
                'by_status': status_counts,
            }
            serializer = SalesStatsSerializer(data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Erreur dans sales_stats: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='purchases')
    def purchase_stats(self, request):
        try:
            period = request.query_params.get('period', 'month')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response({'error': 'Format de date invalide.'}, status=400)
            else:
                today = timezone.now().date()
                if period == 'month':
                    start = today.replace(day=1)
                    end = today
                else:
                    start = today - timedelta(days=30)
                    end = today

            purchases = PurchaseOrder.objects.filter(
                order_date__date__gte=start,
                order_date__date__lte=end,
                status__in=['confirmed', 'received']
            )

            total_orders = purchases.count()
            total_amount = purchases.aggregate(
                total=Sum('total'))['total'] or 0

            top_suppliers = purchases.values('supplier__name').annotate(
                total=Sum('total')
            ).order_by('-total')[:5]

            return Response({
                'period': f'{start} - {end}',
                'total_orders': total_orders,
                'total_amount': total_amount,
                'top_suppliers': top_suppliers,
            })

        except Exception as e:
            logger.error(f"Erreur dans purchase_stats: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='cashflow')
    def cash_flow(self, request):
        try:
            period = request.query_params.get('period', 'month')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response({'error': 'Format de date invalide.'}, status=400)
            else:
                today = timezone.now().date()
                if period == 'month':
                    start = today.replace(day=1)
                    end = today
                else:
                    start = today - timedelta(days=30)
                    end = today

            mouvements = MouvementTresorerie.objects.filter(
                status='effectue',
                date_mouvement__date__gte=start,
                date_mouvement__date__lte=end
            )

            entries = mouvements.filter(type_mouvement='encaissement').aggregate(
                total=Sum('montant')
            )['total'] or 0
            exits = mouvements.filter(type_mouvement='decaissement').aggregate(
                total=Sum('montant')
            )['total'] or 0

            daily_data = []
            current = start
            while current <= end:
                day_entries = mouvements.filter(
                    type_mouvement='encaissement',
                    date_mouvement__date=current
                ).aggregate(total=Sum('montant'))['total'] or 0
                day_exits = mouvements.filter(
                    type_mouvement='decaissement',
                    date_mouvement__date=current
                ).aggregate(total=Sum('montant'))['total'] or 0
                daily_data.append({
                    'date': current,
                    'entries': day_entries,
                    'exits': day_exits,
                    'balance': day_entries - day_exits,
                })
                current += timedelta(days=1)

            serializer = CashFlowSerializer(daily_data, many=True)
            return Response({
                'period': f'{start} - {end}',
                'total_entries': entries,
                'total_exits': exits,
                'net_flow': entries - exits,
                'daily': serializer.data,
            })

        except Exception as e:
            logger.error(f"Erreur dans cash_flow: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='inventory')
    def inventory_stats(self, request):
        try:
            total_products = Product.objects.filter(status='active').count()
            total_value = 0
            low_stock_items = 0
            out_of_stock_items = 0

            for product in Product.objects.filter(status='active'):
                qty = product.current_stock
                total_value += qty * product.purchase_price
                if qty <= 0:
                    out_of_stock_items += 1
                elif qty <= product.min_stock:
                    low_stock_items += 1

            warehouses_count = Warehouse.objects.filter(is_active=True).count()

            return Response({
                'total_products': total_products,
                'total_stock_value': total_value,
                'low_stock_items': low_stock_items,
                'out_of_stock_items': out_of_stock_items,
                'warehouses_count': warehouses_count,
            })

        except Exception as e:
            logger.error(f"Erreur dans inventory_stats: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AnalyseViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='top-products')
    def top_products(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response({'error': 'Format de date invalide.'}, status=400)
            else:
                today = timezone.now().date()
                start = today - timedelta(days=30)
                end = today

            top = LigneVente.objects.filter(
                sale__status__in=['confirmed', 'paid'],
                sale__sale_date__date__gte=start,
                sale__sale_date__date__lte=end
            ).values('product__id', 'product__name').annotate(
                total_quantity=Sum('quantity'),
                total_amount=Sum('total')
            ).order_by('-total_quantity')[:limit]

            result = [{
                'product_id': item['product__id'],
                'product_name': item['product__name'],
                'quantity_sold': item['total_quantity'] or 0,
                'total_amount': item['total_amount'] or 0,
            } for item in top]

            serializer = TopProductsSerializer(result, many=True)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Erreur dans top_products: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='top-clients')
    def top_clients(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response({'error': 'Format de date invalide.'}, status=400)
            else:
                today = timezone.now().date()
                start = today - timedelta(days=30)
                end = today

            top = Vente.objects.filter(
                status__in=['confirmed', 'paid'],
                sale_date__date__gte=start,
                sale_date__date__lte=end
            ).values('client__id', 'client__name').annotate(
                total_orders=Count('id'),
                total_purchases=Sum('total')
            ).order_by('-total_purchases')[:limit]

            result = [{
                'client_id': item['client__id'],
                'client_name': item['client__name'] or 'Client inconnu',
                'total_orders': item['total_orders'],
                'total_purchases': item['total_purchases'] or 0,
            } for item in top]

            serializer = TopClientsSerializer(result, many=True)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Erreur dans top_clients: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='top-suppliers')
    def top_suppliers(self, request):
        try:
            limit = int(request.query_params.get('limit', 10))
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            if start_date and end_date:
                try:
                    start = date.fromisoformat(start_date)
                    end = date.fromisoformat(end_date)
                except ValueError:
                    return Response({'error': 'Format de date invalide.'}, status=400)
            else:
                today = timezone.now().date()
                start = today - timedelta(days=30)
                end = today

            top = PurchaseOrder.objects.filter(
                status__in=['confirmed', 'received'],
                order_date__date__gte=start,
                order_date__date__lte=end
            ).values('supplier__name').annotate(
                total_orders=Count('id'),
                total_amount=Sum('total')
            ).order_by('-total_amount')[:limit]

            return Response(top)

        except Exception as e:
            logger.error(f"Erreur dans top_suppliers: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='trends')
    def trends(self, request):
        try:
            today = timezone.now().date()
            months = []
            for i in range(6, 0, -1):
                month = today.replace(day=1) - timedelta(days=i*30)
                months.append(month.replace(day=1))

            data = []
            for month_start in months:
                month_end = (month_start.replace(
                    day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

                ventes_mois = Vente.objects.filter(
                    status__in=['confirmed', 'paid'],
                    sale_date__date__gte=month_start,
                    sale_date__date__lte=month_end
                )
                sales_amount = ventes_mois.aggregate(
                    total=Sum('total'))['total'] or 0
                sales_count = ventes_mois.count()

                achats_mois = PurchaseOrder.objects.filter(
                    status__in=['confirmed', 'received'],
                    order_date__date__gte=month_start,
                    order_date__date__lte=month_end
                )
                purchase_amount = achats_mois.aggregate(
                    total=Sum('total'))['total'] or 0

                mouvements_mois = MouvementTresorerie.objects.filter(
                    status='effectue',
                    date_mouvement__date__gte=month_start,
                    date_mouvement__date__lte=month_end
                )
                entries = mouvements_mois.filter(type_mouvement='encaissement').aggregate(
                    total=Sum('montant'))['total'] or 0
                exits = mouvements_mois.filter(type_mouvement='decaissement').aggregate(
                    total=Sum('montant'))['total'] or 0

                data.append({
                    'month': month_start.strftime('%Y-%m'),
                    'sales_amount': sales_amount,
                    'sales_count': sales_count,
                    'purchase_amount': purchase_amount,
                    'cash_flow': entries - exits,
                })

            return Response(data)

        except Exception as e:
            logger.error(f"Erreur dans trends: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='financial-health')
    def financial_health(self, request):
        try:
            today = timezone.now().date()
            start_of_month = today.replace(day=1)

            ventes_mois = Vente.objects.filter(
                status__in=['confirmed', 'paid'],
                sale_date__date__gte=start_of_month
            )
            sales_total = ventes_mois.aggregate(
                total=Sum('total'))['total'] or 0

            achats_mois = PurchaseOrder.objects.filter(
                status__in=['confirmed', 'received'],
                order_date__date__gte=start_of_month
            )
            purchases_total = achats_mois.aggregate(
                total=Sum('total'))['total'] or 0

            cash_total = Caisse.objects.filter(is_active=True).aggregate(
                total=Sum('solde_actuel'))['total'] or 0
            bank_total = CompteBancaire.objects.filter(is_active=True).aggregate(
                total=Sum('solde_actuel'))['total'] or 0

            # ✅ CORRECTION : utiliser F() pour soustraire les champs
            receivables = Facture.objects.filter(
                status__in=['sent', 'partial'],
                due_date__lt=today
            ).aggregate(
                total=Sum(F('total') - F('amount_paid'))
            )['total'] or 0

            payables = SupplierInvoice.objects.filter(
                status__in=['received', 'verified', 'partial'],
                due_date__lt=today
            ).aggregate(
                total=Sum(F('total_amount') - F('amount_paid'))
            )['total'] or 0

            return Response({
                'monthly_sales': sales_total,
                'monthly_purchases': purchases_total,
                'cash_balance': cash_total + bank_total,
                'receivables': receivables,
                'payables': payables,
                'net_cash_position': (cash_total + bank_total) + receivables - payables,
            })

        except Exception as e:
            logger.error(f"Erreur dans financial_health: {str(e)}")
            return Response(
                {"error": f"Erreur interne: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
