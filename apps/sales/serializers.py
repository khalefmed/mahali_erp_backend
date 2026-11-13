from decimal import Decimal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.serializers import StoreProductField

from .models import (
    CashSession,
    Credit,
    CreditNote,
    CreditNoteLine,
    Customer,
    Expense,
    ExpenseCategory,
    Payment,
    PaymentMethod,
    Sale,
    SaleLine,
)

QTY = {"max_digits": 12, "decimal_places": 3}


class CustomerSerializer(serializers.ModelSerializer):
    credit_balance = serializers.IntegerField(
        read_only=True, default=0, help_text="Total still owed (open credits)"
    )

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "address",
            "note",
            "is_active",
            "credit_balance",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


@extend_schema_field(OpenApiTypes.UUID)
class CustomerField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Customer.objects.filter(is_active=True)


@extend_schema_field(OpenApiTypes.UUID)
class CashSessionField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return CashSession.objects.filter(status=CashSession.Status.OPEN)


class PaymentMethodsTotalsSerializer(serializers.Serializer):
    cash = serializers.IntegerField()
    bankily = serializers.IntegerField()
    masrvi = serializers.IntegerField()
    sedad = serializers.IntegerField()
    bank_transfer = serializers.IntegerField()


class SessionTotalsSerializer(serializers.Serializer):
    sales_count = serializers.IntegerField()
    sales_total = serializers.IntegerField()
    discount_total = serializers.IntegerField()
    vat_total = serializers.IntegerField()
    credit_issued = serializers.IntegerField()
    credit_repayments = serializers.IntegerField()
    refunds = serializers.IntegerField()
    expenses = serializers.IntegerField()
    payments_by_method = PaymentMethodsTotalsSerializer()
    expected_cash = serializers.IntegerField()


class CashSessionSerializer(serializers.ModelSerializer):
    opened_by_name = serializers.CharField(source="opened_by.full_name", read_only=True)
    closed_by_name = serializers.CharField(
        source="closed_by.full_name", read_only=True, default=None
    )
    totals = serializers.SerializerMethodField(
        help_text="Live while open, frozen Z report once closed"
    )

    class Meta:
        model = CashSession
        fields = [
            "id",
            "number",
            "status",
            "opened_by_name",
            "opening_float",
            "created_at",
            "closed_by_name",
            "closed_at",
            "expected_cash",
            "counted_cash",
            "difference",
            "closing_note",
            "totals",
        ]
        read_only_fields = [f for f in fields if f != "opening_float"]

    @extend_schema_field(SessionTotalsSerializer)
    def get_totals(self, obj):
        from .services import session_totals

        return session_totals(obj) if obj.status == CashSession.Status.OPEN else obj.totals


class CloseSessionSerializer(serializers.Serializer):
    counted_cash = serializers.IntegerField(min_value=0)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class SaleLineInputSerializer(serializers.Serializer):
    store_product = StoreProductField()
    quantity = serializers.DecimalField(min_value=Decimal("0.001"), **QTY)
    discount = serializers.IntegerField(min_value=0, default=0, help_text="MRU off this line")
    serial = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text="IMEI / serial, required for tracked products",
    )


class PaymentInputSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    amount = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(
        max_length=60,
        required=False,
        allow_blank=True,
        help_text="Bankily / Masrvi transaction number",
    )


class SaleCreateSerializer(serializers.Serializer):
    lines = SaleLineInputSerializer(many=True, allow_empty=False)
    payments = PaymentInputSerializer(many=True, required=False, default=list)
    customer = CustomerField(required=False, allow_null=True)
    cash_session = CashSessionField(
        required=False, allow_null=True, help_text="Defaults to my open till"
    )
    due_date = serializers.DateField(required=False, help_text="For the unpaid part (credit)")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class SaleLineSerializer(serializers.ModelSerializer):
    serial = serializers.CharField(source="serial_unit.serial", default=None)

    class Meta:
        model = SaleLine
        fields = [
            "id",
            "store_product",
            "description",
            "serial",
            "quantity",
            "unit_price",
            "discount",
            "line_total",
            "vat_amount",
            "warranty_months",
            "refunded_quantity",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "kind", "method", "amount", "reference", "created_at"]


class SaleListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", default=None)
    seller_name = serializers.CharField(source="seller.full_name")

    class Meta:
        model = Sale
        fields = [
            "id",
            "number",
            "status",
            "customer",
            "customer_name",
            "seller_name",
            "total",
            "paid_total",
            "credit_total",
            "refunded_total",
            "created_at",
        ]


class SaleSerializer(SaleListSerializer):
    lines = SaleLineSerializer(many=True)
    payments = PaymentSerializer(many=True)
    credit_number = serializers.CharField(source="credit.number", default=None)

    class Meta(SaleListSerializer.Meta):
        fields = [
            *SaleListSerializer.Meta.fields,
            "subtotal",
            "discount_total",
            "vat_total",
            "note",
            "credit_number",
            "lines",
            "payments",
        ]


class CreditSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    sale_number = serializers.CharField(source="sale.number", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Credit
        fields = [
            "id",
            "number",
            "sale",
            "sale_number",
            "customer",
            "customer_name",
            "amount",
            "balance",
            "due_date",
            "status",
            "is_overdue",
            "created_at",
        ]

    def get_is_overdue(self, obj) -> bool:
        from django.utils import timezone

        return obj.status == Credit.Status.OPEN and obj.due_date < timezone.localdate()


class RepaymentSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True)


@extend_schema_field(OpenApiTypes.UUID)
class SaleLineField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return SaleLine.objects.all()


@extend_schema_field(OpenApiTypes.UUID)
class SaleField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Sale.objects.all()


class CreditNoteLineSerializer(serializers.ModelSerializer):
    sale_line = SaleLineField()
    quantity = serializers.DecimalField(min_value=Decimal("0.001"), **QTY)
    description = serializers.CharField(source="sale_line.description", read_only=True)

    class Meta:
        model = CreditNoteLine
        fields = ["sale_line", "description", "quantity", "amount"]
        read_only_fields = ["amount"]


class CreditNoteSerializer(serializers.ModelSerializer):
    sale = SaleField()
    sale_number = serializers.CharField(source="sale.number", read_only=True)
    lines = CreditNoteLineSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(
        choices=[*PaymentMethod.choices, ("credit", "Réduire le crédit du client")]
    )

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "number",
            "sale",
            "sale_number",
            "lines",
            "refund_method",
            "reason",
            "restock",
            "total",
            "created_at",
        ]
        read_only_fields = ["id", "number", "total", "created_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    category = serializers.ChoiceField(choices=ExpenseCategory.choices)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model = Expense
        fields = ["id", "category", "amount", "method", "note", "created_by_name", "created_at"]
        read_only_fields = ["id", "created_at"]
