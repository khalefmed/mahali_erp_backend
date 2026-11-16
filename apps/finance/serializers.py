from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import Supplier
from apps.sales.models import PaymentMethod

from .models import ExpenseBudget, MoneyTransfer, RecurringExpense, SupplierPayment


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    amount = serializers.IntegerField(min_value=1)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = [
            "id",
            "supplier",
            "supplier_name",
            "amount",
            "method",
            "reference",
            "note",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class JournalQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=False, help_text="Default: today")


class JournalLineSerializer(serializers.Serializer):
    account = serializers.CharField(help_text="SYSCOHADA account number")
    account_name = serializers.CharField()
    label = serializers.CharField(allow_blank=True, help_text="Customer, supplier, note or empty")
    debit = serializers.IntegerField()
    credit = serializers.IntegerField()


class JournalEntrySerializer(serializers.Serializer):
    id = serializers.CharField()
    journal = serializers.ChoiceField(choices=["sales", "purchases", "bank", "cash", "misc"])
    reference = serializers.CharField(allow_blank=True)
    lines = JournalLineSerializer(many=True)


class JournalDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    entries = JournalEntrySerializer(many=True)


class PeriodQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, help_text="Default: 1st of this month")
    date_to = serializers.DateField(required=False, help_text="Default: today")

    def validate(self, attrs):
        today = timezone.localdate()
        attrs.setdefault("date_to", today)
        attrs.setdefault("date_from", attrs["date_to"].replace(day=1))
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_from": "After date_to."})
        return attrs


class ClosingCheckSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            "sales_posted",
            "purchases_matched",
            "bank_reconciled",
            "tills_closed",
            "expense_receipts",
            "cash_gaps",
        ]
    )
    done = serializers.BooleanField()
    count = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField(required=False, allow_null=True)
    account = serializers.CharField(required=False, allow_null=True)


class DeclarationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["to_file", "filed"])
    due_date = serializers.DateField()


class ClosingSerializer(serializers.Serializer):
    vat_deductible = serializers.IntegerField(help_text="VAT paid on purchases (account 445)")
    declaration = DeclarationSerializer()
    checks = ClosingCheckSerializer(many=True)


# ---------------------------------------------------------------- treasury


class MoneyAccountSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The payment method code")
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=["cash", "mobile_money", "bank"])
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    balance = serializers.IntegerField(help_text="Every recorded flow on the account, MRU")
    operations_today = serializers.IntegerField()
    opened_by_name = serializers.CharField(allow_null=True)
    is_store_till = serializers.BooleanField()
    reconciled_on = serializers.DateField(allow_null=True)


class MoneyAccountListSerializer(serializers.Serializer):
    results = MoneyAccountSerializer(many=True)


class MoneyMovementQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=False, help_text="Default: today")


class MoneyMovementSerializer(serializers.Serializer):
    id = serializers.CharField()
    at = serializers.DateTimeField()
    account_id = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=[
            "sale",
            "credit_repayment",
            "refund",
            "supplier_payment",
            "expense",
            "marketplace",
            "transfer",
        ]
    )
    reference = serializers.CharField(allow_blank=True)
    party = serializers.CharField(allow_blank=True)
    detail = serializers.CharField(allow_blank=True)
    amount = serializers.IntegerField(help_text="Signed: positive comes in")
    counterpart_id = serializers.CharField(allow_null=True)


class MoneyMovementListSerializer(serializers.Serializer):
    results = MoneyMovementSerializer(many=True)


class MoneyTransferSerializer(serializers.ModelSerializer):
    amount = serializers.IntegerField(min_value=1)

    class Meta:
        model = MoneyTransfer
        fields = ["id", "from_account", "to_account", "amount", "date", "note", "created_at"]
        read_only_fields = ["id", "created_at"]


# ---------------------------------------------------------------- expenses


class RecurringExpenseSerializer(serializers.ModelSerializer):
    amount = serializers.IntegerField(min_value=1)

    class Meta:
        model = RecurringExpense
        fields = [
            "id",
            "label",
            "category",
            "amount",
            "method",
            "frequency",
            "next_date",
            "variable_amount",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class RecurringExpenseListSerializer(serializers.Serializer):
    results = RecurringExpenseSerializer(many=True)


class ExpenseBudgetSerializer(serializers.ModelSerializer):
    amount = serializers.IntegerField(min_value=0)

    class Meta:
        model = ExpenseBudget
        fields = ["category", "amount"]


class ExpenseBudgetListSerializer(serializers.Serializer):
    results = ExpenseBudgetSerializer(many=True)

    def validate_results(self, value):
        categories = [row["category"] for row in value]
        if len(categories) != len(set(categories)):
            raise serializers.ValidationError("One budget per category.")
        return value
