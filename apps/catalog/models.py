"""The Mahali catalog: global, normalized, managed by the Mahali team only.

Stores never create products. They pick variants from this catalog (see
`inventory.StoreProduct`) or ask for a missing one (`ProductRequest`). This is what
lets the marketplace show one "iPhone 15 · 128 Go · Noir" sold by many stores.
"""

import pghistory
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel
from apps.stores.models import Trade


@pghistory.track()
class Category(BaseModel):
    """`attribute_schema` lists the attributes products of this category must describe:

        [{"key": "storage", "label": "Stockage", "label_ar": "السعة", "type": "choice",
          "options": ["64 Go", "128 Go"], "required": true, "level": "variant"}]

    type: choice | text | number | boolean. level: product (same for all variants) or
    variant (what distinguishes variants: storage, color…).
    """

    trade = models.CharField(max_length=20, choices=Trade.choices, db_index=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    name = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100, blank=True)
    slug = models.SlugField(max_length=120, unique=True)
    tracks_serial = models.BooleanField(
        default=False, help_text="Each unit has a serial number / IMEI (phones, laptops…)"
    )
    default_warranty_months = models.PositiveSmallIntegerField(default=0)
    attribute_schema = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["trade", "sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Brand(BaseModel):
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, unique=True)
    trades = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="uniq_brand_name_ci")]

    def __str__(self):
        return self.name


class ProductStatus(models.TextChoices):
    ACTIVE = "active"
    ARCHIVED = "archived"


@pghistory.track()
class Product(BaseModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=160)
    name_ar = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(blank=True)
    status = models.CharField(
        max_length=10, choices=ProductStatus.choices, default=ProductStatus.ACTIVE, db_index=True
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


@pghistory.track()
class Variant(BaseModel):
    """What is actually sold and stocked: "128 Go · Noir". Carries the barcode."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=120, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    barcode = models.CharField(max_length=32, null=True, blank=True, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product__name", "name"]

    def __str__(self):
        return f"{self.product.name} {self.name}".strip()

    @property
    def full_name(self) -> str:
        return str(self)


class ProductRequestStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def request_photo_path(instance, filename):
    return f"stores/{instance.store_id}/product-requests/{instance.id}{instance.extension}"


class ProductRequest(BaseModel):
    """'Demander un produit': a store asks the Mahali team to add a missing product."""

    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="product_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    name = models.CharField(max_length=160)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    brand_name = models.CharField(max_length=80, blank=True)
    barcode = models.CharField(max_length=32, blank=True)
    note = models.TextField(blank=True)
    photo = models.FileField(upload_to=request_photo_path, null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=ProductRequestStatus.choices,
        default=ProductRequestStatus.PENDING,
        db_index=True,
    )
    variant = models.ForeignKey(
        Variant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_message = models.TextField(blank=True)
    extension = ""

    class Meta:
        ordering = ["-created_at"]
