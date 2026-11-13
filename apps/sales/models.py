import pghistory
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import StoreScopedModel

QTY = {"max_digits": 12, "decimal_places": 3}
USER = settings.AUTH_USER_MODEL


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Espèces"
    BANKILY = "bankily", "Bankily"
    MASRVI = "masrvi", "Masrvi"
    SEDAD = "sedad", "Sedad"
    BANK_TRANSFER = "bank_transfer", "Virement"


@pghistory.track()
class Customer(StoreScopedModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]


class CashSession(StoreScopedModel):
    """A till shift: opened with a float, closed with a cash count (Z report)."""

    class Status(models.TextChoices):
        OPEN = "open"
        CLOSED = "closed"

    number = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)
    opened_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    opening_float = models.PositiveIntegerField(default=0)
    closed_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_cash = models.BigIntegerField(null=True, blank=True)
    counted_cash = models.BigIntegerField(null=True, blank=True)
    difference = models.BigIntegerField(null=True, blank=True)
    totals = models.JSONField(default=dict, blank=True, help_text="Z report frozen at closing")
    closing_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "opened_by"],
                condition=Q(status="open"),
                name="one_open_session_per_user",
            )
        ]


class Sale(StoreScopedModel):
    """Immutable once created. Corrections go through credit notes (avoirs)."""

    class Status(models.TextChoices):
        COMPLETED = "completed"
        PARTIALLY_REFUNDED = "partially_refunded"
        REFUNDED = "refunded"

    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="sales"
    )
    seller = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    subtotal = models.BigIntegerField(help_text="Before discounts")
    discount_total = models.BigIntegerField(default=0)
    total = models.BigIntegerField()
    vat_total = models.BigIntegerField(default=0)
    paid_total = models.BigIntegerField(default=0)
    credit_total = models.BigIntegerField(default=0, help_text="Left to pay, see Credit")
    refunded_total = models.BigIntegerField(default=0)
    cost_total = models.BigIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["store", "number"], name="uniq_sale_number")]


class SaleLine(StoreScopedModel):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    store_product = models.ForeignKey(
        "inventory.StoreProduct", on_delete=models.PROTECT, related_name="+"
    )
    serial_unit = models.ForeignKey(
        "inventory.SerialUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sale_lines",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(**QTY)
    unit_price = models.PositiveIntegerField()
    discount = models.PositiveIntegerField(default=0)
    line_total = models.BigIntegerField()
    vat_amount = models.BigIntegerField(default=0)
    unit_cost = models.PositiveIntegerField(default=0)
    warranty_months = models.PositiveSmallIntegerField(default=0)
    refunded_quantity = models.DecimalField(default=0, **QTY)


class Credit(StoreScopedModel):
    """What a customer still owes on a sale (CR-####)."""

    class Status(models.TextChoices):
        OPEN = "open"
        SETTLED = "settled"

    number = models.CharField(max_length=20)
    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, related_name="credit")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="credits")
    amount = models.BigIntegerField()
    balance = models.BigIntegerField()
    due_date = models.DateField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["due_date"]
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="credit_balance_not_negative")
        ]


class CreditNote(StoreScopedModel):
    """Avoir: returns goods and/or money for part of a sale (AV-AAMM-####)."""

    number = models.CharField(max_length=20)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="credit_notes")
    total = models.BigIntegerField()
    refund_method = models.CharField(
        max_length=20, help_text="Payment method, or `credit` to reduce what the customer owes"
    )
    reason = models.CharField(max_length=255)
    restock = models.BooleanField(default=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class CreditNoteLine(StoreScopedModel):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(**QTY)
    amount = models.BigIntegerField()


class Payment(StoreScopedModel):
    """Every money movement: sale payments, credit repayments, refunds (negative)."""

    class Kind(models.TextChoices):
        SALE = "sale"
        CREDIT_REPAYMENT = "credit_repayment"
        REFUND = "refund"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = models.BigIntegerField()
    reference = models.CharField(max_length=60, blank=True)
    cash_session = models.ForeignKey(
        CashSession, null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    sale = models.ForeignKey(
        Sale, null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    credit = models.ForeignKey(
        Credit, null=True, blank=True, on_delete=models.PROTECT, related_name="repayments"
    )
    credit_note = models.ForeignKey(
        CreditNote, null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class ExpenseCategory(models.TextChoices):
    RENT = "rent", "Loyer"
    SALARIES = "salaries", "Salaires"
    TRANSPORT = "transport", "Transport"
    UTILITIES = "utilities", "Électricité, eau, internet"
    SUPPLIES = "supplies", "Fournitures"
    OTHER = "other", "Autre"


class Expense(StoreScopedModel):
    category = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    amount = models.PositiveBigIntegerField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    note = models.CharField(max_length=255, blank=True)
    cash_session = models.ForeignKey(
        CashSession, null=True, blank=True, on_delete=models.PROTECT, related_name="expenses"
    )
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
