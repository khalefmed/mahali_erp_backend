from decimal import Decimal

import pghistory
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class StaffRole(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super-admin"
    OPERATIONS = "operations", "Opérations"
    SUPPORT = "support", "Support"
    FINANCE = "finance", "Finance"


@pghistory.track()
class PlatformStaff(BaseModel):
    """A Mahali team member. Signs in to the console realm only."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_staff"
    )
    role = models.CharField(max_length=20, choices=StaffRole.choices)
    is_active = models.BooleanField(default=True)


class StoreNote(BaseModel):
    """Internal note about a store, visible to the Mahali team only."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()

    class Meta:
        ordering = ["-created_at"]


class PlatformSettings(models.Model):
    """Singleton (pk=1)."""

    review_sla_hours = models.PositiveSmallIntegerField(default=24)
    announcement = models.CharField(
        max_length=280, blank=True, help_text="Banner shown to every merchant"
    )
    signups_open = models.BooleanField(default=True)
    marketplace_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal(10),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Added to the cheapest store price on the marketplace",
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def signups_are_open(cls) -> bool:
        return cls.load().signups_open

    @classmethod
    def load(cls) -> "PlatformSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
