import pghistory
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .roles import Role


class Trade(models.TextChoices):
    TELEPHONES = "telephones", "Téléphones & électronique"
    APPLIANCES = "electromenager", "Électroménager"
    PHARMACY = "pharmacie", "Pharmacie"
    HARDWARE = "quincaillerie", "Quincaillerie"


class StoreStatus(models.TextChoices):
    DRAFT = "draft"  # being filled in by the owner
    PENDING_APPROVAL = "pending_approval"  # submitted, waiting for the Mahali team
    INFO_REQUESTED = "info_requested"  # team asked for more information
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"  # by the Mahali team: read-only
    ARCHIVED = "archived"  # closed: read-only


EDITABLE_ONBOARDING = {StoreStatus.DRAFT, StoreStatus.INFO_REQUESTED}
READ_ONLY_STATUSES = {StoreStatus.SUSPENDED, StoreStatus.ARCHIVED}


@pghistory.track()
class Store(BaseModel):
    name = models.CharField(max_length=120)
    trade = models.CharField(max_length=20, choices=Trade.choices)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_stores"
    )
    status = models.CharField(
        max_length=20, choices=StoreStatus.choices, default=StoreStatus.DRAFT, db_index=True
    )
    city = models.CharField(max_length=80)
    address = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    # Settings
    vat_enabled = models.BooleanField(default=False)
    vat_rate = models.PositiveSmallIntegerField(default=16)
    max_discount_percent = models.PositiveSmallIntegerField(
        default=10, help_text="Above this, a discount needs sales.discount_override."
    )
    # Review
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision_message = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DocumentKind(models.TextChoices):
    ID_FRONT = "id_front", "NNI recto"
    ID_BACK = "id_back", "NNI verso"
    STOREFRONT = "storefront", "Photo de la devanture"
    PHARMACY_LICENSE = "pharmacy_license", "Autorisation d'exercice"
    OTHER = "other", "Autre"


def document_path(instance, filename):
    return f"stores/{instance.store_id}/documents/{instance.id}{instance.extension}"


class StoreDocument(BaseModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=20, choices=DocumentKind.choices)
    file = models.FileField(upload_to=document_path, max_length=255)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    extension = ""


@pghistory.track()
class Membership(BaseModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "user"], name="uniq_membership"),
            models.UniqueConstraint(
                fields=["store"], condition=Q(role=Role.OWNER), name="one_owner_per_store"
            ),
        ]


class Invitation(BaseModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class OwnershipTransfer(BaseModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="ownership_transfers")
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incoming_ownership_transfers",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
