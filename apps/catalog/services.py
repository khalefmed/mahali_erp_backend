import csv
import io

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from apps.core import audit
from apps.core.exceptions import ApiError, Conflict
from apps.core.notifications import notify
from apps.stores.files import sniff

from .attributes import validate_attributes
from .models import Brand, Category, Product, ProductRequest, ProductRequestStatus, Variant


def create_product_request(request, store, data) -> ProductRequest:
    photo = data.pop("photo", None)
    product_request = ProductRequest(store=store, requested_by=request.user, **data)
    if photo:
        _, product_request.extension = sniff(photo)
        product_request.photo.save(photo.name, photo, save=False)
    product_request.save()
    return product_request


@transaction.atomic
def decide_product_request(
    request,
    product_request: ProductRequest,
    *,
    approve: bool,
    variant: Variant | None = None,
    message: str = "",
) -> ProductRequest:
    product_request = ProductRequest.objects.select_for_update().get(pk=product_request.pk)
    if product_request.status != ProductRequestStatus.PENDING:
        raise Conflict("already_decided", "This request was already handled.")
    if approve and variant is None:
        raise ApiError("variant_required", "Link the catalog variant that was added.")
    product_request.status = (
        ProductRequestStatus.APPROVED if approve else ProductRequestStatus.REJECTED
    )
    product_request.variant = variant if approve else None
    product_request.decided_by = request.user
    product_request.decided_at = timezone.now()
    product_request.decision_message = message
    product_request.save()
    audit.record(
        request,
        f"product_request.{product_request.status}",
        target=product_request,
        store=product_request.store,
        reason=message,
    )
    notify(
        product_request.requested_by,
        f"product_request_{product_request.status}",
        {"request": product_request, "store": product_request.store},
    )
    return product_request


def import_csv(upload, *, dry_run: bool) -> dict:
    """All or nothing: any error and nothing is written."""
    text = upload.read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    errors: list[dict] = []
    created_products = created_variants = 0
    categories = {c.slug: c for c in Category.objects.all()}
    brands = {b.name.lower(): b for b in Brand.objects.all()}
    products: dict[tuple, Product] = {}
    barcodes_seen: set[str] = set()

    with transaction.atomic():
        for line, row in enumerate(rows, start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            category = categories.get(row.get("category", ""))
            if category is None:
                errors.append(
                    {
                        "row": line,
                        "field": "category",
                        "code": "unknown_category",
                        "detail": f"Unknown category {row.get('category')!r}.",
                    }
                )
                continue
            if not row.get("product"):
                errors.append(
                    {
                        "row": line,
                        "field": "product",
                        "code": "required",
                        "detail": "Product name is required.",
                    }
                )
                continue
            brand = None
            if row.get("brand"):
                brand = brands.get(row["brand"].lower())
                if brand is None:
                    brand = Brand.objects.create(
                        name=row["brand"], slug=slugify(row["brand"]), trades=[category.trade]
                    )
                    brands[row["brand"].lower()] = brand
            p_attrs = {k[2:]: _parse(v) for k, v in row.items() if k.startswith("p:") and v}
            v_attrs = {k[2:]: _parse(v) for k, v in row.items() if k.startswith("v:") and v}
            try:
                p_attrs = validate_attributes(
                    category.attribute_schema, p_attrs, "product", "attributes"
                )
                v_attrs = validate_attributes(
                    category.attribute_schema, v_attrs, "variant", "variant_attributes"
                )
            except ValidationError as exc:
                for field, messages in exc.detail.items():
                    errors.append(
                        {
                            "row": line,
                            "field": field,
                            "code": "invalid_attribute",
                            "detail": str(messages[0]),
                        }
                    )
                continue
            barcode = row.get("barcode") or None
            if barcode and (
                barcode in barcodes_seen or Variant.objects.filter(barcode=barcode).exists()
            ):
                errors.append(
                    {
                        "row": line,
                        "field": "barcode",
                        "code": "duplicate_barcode",
                        "detail": f"Barcode {barcode} already exists.",
                    }
                )
                continue
            if barcode:
                barcodes_seen.add(barcode)
            key = (category.id, brand.id if brand else None, row["product"].lower())
            product = products.get(key)
            if product is None:
                product = Product.objects.create(
                    category=category,
                    brand=brand,
                    name=row["product"],
                    name_ar=row.get("product_ar", ""),
                    description=row.get("description", ""),
                    image_url=row.get("image_url", ""),
                    attributes=p_attrs,
                )
                products[key] = product
                created_products += 1
            Variant.objects.create(
                product=product,
                attributes=v_attrs,
                barcode=barcode,
                name=row.get("variant") or " · ".join(str(v) for v in v_attrs.values()),
            )
            created_variants += 1
        if errors or dry_run:
            transaction.set_rollback(True)

    return {
        "dry_run": dry_run,
        "created_products": created_products if not errors else 0,
        "created_variants": created_variants if not errors else 0,
        "errors": errors,
    }


def _parse(value: str):
    if value.lower() in {"true", "oui", "yes"}:
        return True
    if value.lower() in {"false", "non", "no"}:
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return value
