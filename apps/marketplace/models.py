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


class PaymentMethod(models.TextChoices):
    CASH_ON_DELIVERY = "cash_on_delivery", "Paiement à la livraison"
    MEYSARA = "meysara", "Meysara (en 4 fois)"


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
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH_ON_DELIVERY
    )
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


class MeysaraPlanStatus(models.TextChoices):
    RESERVED = "reserved", "Réservé (avant livraison)"
    ACTIVE = "active", "En cours"
    PAID = "paid", "Soldé"
    CANCELLED = "cancelled", "Annulé"


class InstalmentMethod(models.TextChoices):
    BANKILY = "bankily", "Bankily"
    MASRVI = "masrvi", "Masrvi"
    SEDAD = "sedad", "Sedad"
    CASH = "cash", "Espèces (commerçant partenaire)"


class MeysaraPlan(BaseModel):
    """Meysara (Infinity's pay-in-4): part of an order paid in 4 instalments, no fees.

    Reserved when the order is placed, active once delivered (instalments get their due
    dates then), paid when every instalment is in, cancelled with the order.
    Rules: `apps.marketplace.meysara`."""

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="meysara_plan")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="meysara_plans"
    )
    percent = models.PositiveSmallIntegerField(help_text="Share of the order: 25, 50 or 100")
    financed = models.PositiveIntegerField(help_text="MRU paid in 4 instalments")
    on_delivery = models.PositiveIntegerField(help_text="MRU paid to the courier")
    status = models.CharField(
        max_length=10,
        choices=MeysaraPlanStatus.choices,
        default=MeysaraPlanStatus.RESERVED,
        db_index=True,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True, help_text="Paid off or cancelled")

    class Meta:
        ordering = ["-created_at"]


class MeysaraInstalment(BaseModel):
    plan = models.ForeignKey(MeysaraPlan, on_delete=models.CASCADE, related_name="instalments")
    number = models.PositiveSmallIntegerField()
    amount = models.PositiveIntegerField()
    due_date = models.DateField(null=True, blank=True, help_text="Set at delivery")
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_via = models.CharField(max_length=10, choices=InstalmentMethod.choices, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "number"], name="uniq_meysara_instalment")
        ]


class OrderSequence(models.Model):
    """Gapless marketplace order numbers per month: MP-2611-0001."""

    series = models.CharField(max_length=20, unique=True)
    last_value = models.PositiveIntegerField(default=0)


class IdentityStatus(models.TextChoices):
    PHONE_PENDING = "phone_pending", "Code SMS à saisir"
    DOCUMENTS_PENDING = "documents_pending", "Pièce d'identité et selfie à envoyer"
    VERIFIED = "verified", "Identité vérifiée"
    REJECTED = "rejected", "Refusée"


class IdentityVerification(BaseModel):
    """A shopper's e-KYC (BCM Instruction n°13/GR/2025, chapter II), required before Meysara.

    Three steps: identity details + consent, phone ownership (one-time code), then the ID
    card and a selfie checked by the provider (document, face match, liveness). The images
    are checked and dropped, never stored. Rules: `apps.marketplace.kyc`."""

    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity_verification"
    )
    status = models.CharField(
        max_length=20,
        choices=IdentityStatus.choices,
        default=IdentityStatus.PHONE_PENDING,
        db_index=True,
    )
    nni = models.CharField(max_length=10, help_text="Numéro national d'identification")
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    birth_date = models.DateField()
    phone = models.CharField(max_length=16, help_text="+222 and 8 digits")
    consent_at = models.DateTimeField(help_text="Explicit consent to the identity checks")
    otp_hash = models.CharField(max_length=128, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=20, help_text="`simulated` until a real provider")
    provider_reference = models.CharField(max_length=64, blank=True)
    checks = models.JSONField(
        default=dict, blank=True, help_text="Provider results: document, face_match, liveness"
    )
    reject_reason = models.CharField(max_length=40, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One identity, one shopper account.
            models.UniqueConstraint(
                fields=["nni"],
                condition=models.Q(status="verified"),
                name="uniq_verified_nni",
            )
        ]

    @property
    def is_verified(self) -> bool:
        return self.status == IdentityStatus.VERIFIED
