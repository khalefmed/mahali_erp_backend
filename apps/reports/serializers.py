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


class CategoryRevenueSerializer(serializers.Serializer):
    category = serializers.CharField(allow_null=True, help_text="Category slug")
    name = serializers.CharField()
    revenue = serializers.IntegerField(help_text="MRU, VAT excluded")


class ReportDetailsSerializer(serializers.Serializer):
    sales_by_category = CategoryRevenueSerializer(many=True)
    dormant_products = serializers.IntegerField(help_text="In stock, no sale for dormant_days")
    dormant_days = serializers.IntegerField()
    supplier_payables = serializers.IntegerField(help_text="Received goods minus supplier payments")


class MemberActivitySerializer(serializers.Serializer):
    user = serializers.UUIDField()
    phone = serializers.CharField(allow_null=True)
    last_seen_at = serializers.DateTimeField(allow_null=True)
    online = serializers.BooleanField(help_text="Seen in the last 5 minutes")
    till_open = serializers.BooleanField()


class MemberActivityListSerializer(serializers.Serializer):
    results = MemberActivitySerializer(many=True)


class SellerPerformanceQuerySerializer(serializers.Serializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", required=False, help_text="YYYY-MM")


class LeaderboardRowSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    name = serializers.CharField()
    store_name = serializers.CharField()
    revenue = serializers.IntegerField()
    is_me = serializers.BooleanField()


class SellerPerformanceSerializer(serializers.Serializer):
    month = serializers.CharField()
    revenue = serializers.IntegerField(help_text="Collected sales of the month, MRU")
    sales_count = serializers.IntegerField()
    commission_rate = serializers.FloatField(help_text="0 until commissions are configured")
    commission = serializers.IntegerField()
    target = serializers.IntegerField(allow_null=True)
    bonus = serializers.IntegerField(allow_null=True)
    stores_count = serializers.IntegerField()
    leaderboard = LeaderboardRowSerializer(many=True)
