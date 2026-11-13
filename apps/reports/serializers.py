from rest_framework import serializers

from apps.sales.serializers import PaymentMethodsTotalsSerializer


class DailyRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    sales_count = serializers.IntegerField()
    revenue = serializers.IntegerField()


class TopProductSerializer(serializers.Serializer):
    store_product = serializers.UUIDField()
    name = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    revenue = serializers.IntegerField()


class SellerRowSerializer(serializers.Serializer):
    seller = serializers.CharField()
    sales_count = serializers.IntegerField()
    revenue = serializers.IntegerField()


class SummarySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    sales_count = serializers.IntegerField()
    revenue = serializers.IntegerField()
    discounts = serializers.IntegerField()
    refunds = serializers.IntegerField()
    net_revenue = serializers.IntegerField()
    cost_of_goods = serializers.IntegerField()
    gross_margin = serializers.IntegerField()
    vat_collected = serializers.IntegerField()
    expenses = serializers.IntegerField()
    credit_issued = serializers.IntegerField()
    credit_collected = serializers.IntegerField()
    credit_outstanding = serializers.IntegerField()
    credit_overdue = serializers.IntegerField()
    payments_by_method = PaymentMethodsTotalsSerializer()
    stock_value = serializers.IntegerField()
    low_stock_count = serializers.IntegerField()
    out_of_stock_count = serializers.IntegerField()
    daily = DailyRowSerializer(many=True)
    top_products = TopProductSerializer(many=True)
    by_seller = SellerRowSerializer(many=True)


class SummaryQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, help_text="Default: today")
    date_to = serializers.DateField(required=False, help_text="Default: date_from")

    def validate(self, attrs):
        from django.utils import timezone

        attrs.setdefault("date_from", timezone.localdate())
        attrs.setdefault("date_to", attrs["date_from"])
        if attrs["date_to"] < attrs["date_from"]:
            raise serializers.ValidationError(
                {"date_to": "Must be after date_from."}, code="invalid"
            )
        if (attrs["date_to"] - attrs["date_from"]).days > 366:
            raise serializers.ValidationError({"date_to": "One year maximum."}, code="invalid")
        return attrs
