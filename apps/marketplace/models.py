"""The Mahali marketplace: one shop window for every store, merchants never shown.

Customers see catalog products at the price of the cheapest store that has them in
stock, plus the Mahali margin (`PlatformSettings.marketplace_margin_percent`).

An `Order` belongs to Mahali and the customer (customer prices, delivery details). It is
split into one `StoreOrder` per store, store-scoped like any store data: a store sees only
its own part, at its own prices, and never the customer.
"""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel, StoreScopedModel
from apps.inventory.models import QTY


class OrderStatus(models.TextChoices):
    PENDING = "pending", "En attente des boutiques"
    CONFIRMED = "confirmed", "Confirmée"
    READY = "ready", "Prête à livrer"
    DELIVERED = "delivered", "Livrée"
    CANCELLED = "cancelled", "Annulée"


class Order(BaseModel):
    number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_orders"
    )
    status = models.CharField(
        max_length=10, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True
    )
    margin_percent = models.DecimalField(max_digits=5, decimal_places=2)
    subtotal = models.PositiveIntegerField(help_text="MRU, customer prices")
    delivery_fee = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField()
    payment_method = models.CharField(max_length=20, default="cash_on_delivery")
    delivery_name = models.CharField(max_length=120)
    delivery_phone = models.CharField(max_length=32)
    delivery_city = models.CharField(max_length=80)
    delivery_address = models.CharField(max_length=255)
    note = models.CharField(max_length=255, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number


class OrderLine(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey("catalog.Variant", on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(**QTY)
    unit_price = models.PositiveIntegerField(help_text="MRU, customer price")
    line_total = models.PositiveIntegerField()


class StoreOrderStatus(models.TextChoices):
    PENDING = "pending", "À confirmer"
    ACCEPTED = "accepted", "Acceptée"
    READY = "ready", "Prête"
    PICKED_UP = "picked_up", "Récupérée par Mahali"
    REJECTED = "rejected", "Refusée"
    CANCELLED = "cancelled", "Annulée"


class StoreOrder(StoreScopedModel):
    """One store's part of an order. Accepting it takes the goods out of stock."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="store_orders")
    status = models.CharField(
        max_length=10,
        choices=StoreOrderStatus.choices,
        default=StoreOrderStatus.PENDING,
        db_index=True,
    )
    total = models.PositiveIntegerField(help_text="MRU, store prices")
    reject_reason = models.CharField(max_length=255, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True, help_text="Rejected or cancelled")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["order", "store"], name="uniq_store_order_per_store")
        ]


class StoreOrderLine(StoreScopedModel):
    store_order = models.ForeignKey(StoreOrder, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="+")
    store_product = models.ForeignKey(
        "inventory.StoreProduct", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(**QTY)
    unit_price = models.PositiveIntegerField(help_text="MRU, store price")
    line_total = models.PositiveIntegerField()
    serials = models.JSONField(default=list, blank=True, help_text="Set when accepted")


class OrderSequence(models.Model):
    """Gapless marketplace order numbers per month: MP-2611-0001."""

    series = models.CharField(max_length=20, unique=True)
    last_value = models.PositiveIntegerField(default=0)
