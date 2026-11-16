"""Back-office money: what the shop pays its suppliers (the books and the treasury are
derived from it and from sales, payments and expenses, see selectors.py)."""

import pghistory
from django.conf import settings
from django.db import models

from apps.core.models import StoreScopedModel
from apps.sales.models import PaymentMethod


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
