import pghistory
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import StoreScopedModel

QTY = {"max_digits": 12, "decimal_places": 3}


class Condition(models.TextChoices):
    NEW = "new", "Neuf"
    USED = "used", "Occasion"


@pghistory.track()
class StoreProduct(StoreScopedModel):
    """A catalog variant as sold by one store: its price, stock and average cost.
    New and used units of the same variant are two StoreProducts (different prices)."""

    variant = models.ForeignKey("catalog.Variant", on_delete=models.PROTECT, related_name="+")
    condition = models.CharField(max_length=4, choices=Condition.choices, default=Condition.NEW)
    sale_price = models.PositiveIntegerField(help_text="MRU, VAT included")
    quantity = models.DecimalField(default=0, **QTY)
    avg_cost = models.PositiveIntegerField(default=0, help_text="Weighted average cost, MRU")
    warranty_months = models.PositiveSmallIntegerField(default=0)
    reorder_level = models.DecimalField(default=0, **QTY)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["store", "variant", "condition"], name="uniq_store_variant_condition"
            ),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="stock_never_negative"),
        ]

    @property
    def tracks_serial(self) -> bool:
        return self.variant.product.category.tracks_serial


class SerialStatus(models.TextChoices):
    IN_STOCK = "in_stock"
    SOLD = "sold"
    LOST = "lost"


class SerialUnit(StoreScopedModel):
    """One physical unit with an IMEI / serial number (phones, laptops, consoles…)."""

    store_product = models.ForeignKey(
        StoreProduct, on_delete=models.PROTECT, related_name="serial_units"
    )
    serial = models.CharField(max_length=64)
    status = models.CharField(
        max_length=10, choices=SerialStatus.choices, default=SerialStatus.IN_STOCK, db_index=True
    )
    unit_cost = models.PositiveIntegerField(default=0)
    receipt_line = models.ForeignKey(
        "ReceiptLine", null=True, blank=True, on_delete=models.PROTECT, related_name="serial_units"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "serial"], name="uniq_store_serial")
        ]


class MovementKind(models.TextChoices):
    RECEIPT = "receipt", "Réception"
    SALE = "sale", "Vente"
    RETURN = "return", "Retour client"
    ADJUSTMENT = "adjustment", "Ajustement"


class StockMovement(StoreScopedModel):
    """Append-only stock journal. Quantity on hand = sum of movements."""

    store_product = models.ForeignKey(
        StoreProduct, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=12, choices=MovementKind.choices)
    quantity = models.DecimalField(**QTY, help_text="Positive in, negative out")
    unit_cost = models.PositiveIntegerField(default=0)
    balance_after = models.DecimalField(**QTY)
    reference = models.CharField(max_length=30, blank=True, help_text="Document number")
    source_id = models.UUIDField(null=True, blank=True)
    serial = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("StockMovement is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("StockMovement is append-only")


@pghistory.track()
class Supplier(StoreScopedModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]


class Receipt(StoreScopedModel):
    """Goods received from a supplier (bon de réception, BR-AAMM-####)."""

    number = models.CharField(max_length=20)
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )
    supplier_reference = models.CharField(
        max_length=60, blank=True, help_text="Supplier's invoice / delivery note number"
    )
    note = models.TextField(blank=True)
    total_cost = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["store", "number"], name="uniq_receipt_number")
        ]


class ReceiptLine(StoreScopedModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="lines")
    store_product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(**QTY)
    unit_cost = models.PositiveIntegerField()
    line_total = models.PositiveBigIntegerField()


class AdjustmentReason(models.TextChoices):
    INVENTORY_COUNT = "inventory_count", "Inventaire"
    DAMAGED = "damaged", "Casse / défaut"
    LOST = "lost", "Perte / vol"
    INITIAL = "initial", "Stock initial"
    OTHER = "other", "Autre"


class StockAdjustment(StoreScopedModel):
    number = models.CharField(max_length=20)
    store_product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name="+")
    quantity_delta = models.DecimalField(**QTY)
    unit_cost = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=20, choices=AdjustmentReason.choices)
    note = models.CharField(max_length=255, blank=True)
    serials = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
