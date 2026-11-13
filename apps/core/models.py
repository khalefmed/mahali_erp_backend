import uuid

from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    """UUID primary key + timestamps. Public IDs are UUIDs, never sequential integers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StoreScopedModel(BaseModel):
    """Data that belongs to one store.

    Every concrete subclass MUST get a row-level security policy in its migration
    (`apps.core.rls.EnableRowLevelSecurity`). `apps/core/tests/test_rls.py` fails if one is
    missing. Queries only see rows of the store set by `apps.core.tenancy.activate_store`.
    """

    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True


class DocumentSequence(models.Model):
    """Gapless document counters per store and series (V-2611-0001, CR-0001…)."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="+")
    series = models.CharField(max_length=20)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "series"], name="uniq_sequence_store_series")
        ]


class AuditEvent(models.Model):
    """Append-only log of sensitive actions (approvals, impersonation, role changes…)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    realm = models.CharField(max_length=10)  # "merchant" | "console" | "system"
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    store = models.ForeignKey(
        "stores.Store", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("AuditEvent is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditEvent is append-only")
