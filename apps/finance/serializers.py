from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import Supplier

from .models import SupplierPayment


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
