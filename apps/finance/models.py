"""Back-office money: what the shop pays its suppliers (the books and the treasury are
derived from it and from sales, payments and expenses, see selectors.py)."""

import pghistory
from django.conf import settings
from django.db import models

from apps.core.models import StoreScopedModel
from apps.sales.models import ExpenseCategory, PaymentMethod


@pghistory.track()
class SupplierPayment(StoreScopedModel):
    """Règlement fournisseur. Cash ones come out of the open till (like expenses)."""

    supplier = models.ForeignKey(
        "inventory.Supplier", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.PositiveBigIntegerField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=255, blank=True)
    cash_session = models.ForeignKey(
        "sales.CashSession",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_payments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]


class Frequency(models.TextChoices):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class RecurringExpense(StoreScopedModel):
    """Charge fixe (loyer, salaires…). `post_recurring_expenses` records the due ones;
    bills whose amount varies (`variable_amount`) wait for the owner to confirm them."""

    label = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    amount = models.PositiveBigIntegerField(help_text="An estimate when variable_amount")
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    next_date = models.DateField()
    variable_amount = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["next_date", "label"]


class ExpenseBudget(StoreScopedModel):
    """Monthly budget of one expense category."""

    category = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    amount = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "category"], name="one_budget_per_category")
        ]


@pghistory.track()
class MoneyTransfer(StoreScopedModel):
    """Money moved between two of the shop's accounts (one account per payment method:
    till, Bankily, Masrvi, Sedad, bank)."""

    from_account = models.CharField(max_length=20, choices=PaymentMethod.choices)
    to_account = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = models.PositiveBigIntegerField()
    date = models.DateField()
    note = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")),
                name="transfer_between_two_accounts",
            )
        ]
