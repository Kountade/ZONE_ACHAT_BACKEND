from rest_framework import serializers


class DashboardSummarySerializer(serializers.Serializer):
    """Résumé du tableau de bord"""
    products = serializers.DictField()
    sales = serializers.DictField()
    purchases = serializers.DictField()
    cash = serializers.DictField()
    alerts = serializers.DictField()
    receivables = serializers.DictField()
    recent_activities = serializers.ListField()


class SalesStatsSerializer(serializers.Serializer):
    """Statistiques de ventes"""
    period = serializers.CharField()
    total_sales = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order = serializers.DecimalField(max_digits=15, decimal_places=2)
    by_status = serializers.DictField()


class CashFlowSerializer(serializers.Serializer):
    """Flux de trésorerie"""
    date = serializers.DateField()
    entries = serializers.DecimalField(max_digits=15, decimal_places=2)
    exits = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2)


class TopProductsSerializer(serializers.Serializer):
    """Top produits"""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    quantity_sold = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class TopClientsSerializer(serializers.Serializer):
    """Top clients"""
    client_id = serializers.IntegerField()
    client_name = serializers.CharField()
    total_orders = serializers.IntegerField()
    total_purchases = serializers.DecimalField(max_digits=15, decimal_places=2)


class ActivitySerializer(serializers.Serializer):
    """Activité récente"""
    type = serializers.CharField()
    reference = serializers.CharField()
    date = serializers.DateTimeField()
    amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False)
    user = serializers.CharField(required=False)
