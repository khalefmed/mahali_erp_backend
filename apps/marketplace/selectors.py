"""Marketplace reads. Every function here reads across stores, so it must run with
`apps.core.tenancy.enable_marketplace_read()` active (views do it in `initial`)."""

from decimal import ROUND_CEILING, Decimal

from django.db import connection
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Ceil
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductStatus, Variant
from apps.console.models import PlatformSettings
from apps.inventory.models import Condition, StoreProduct
from apps.stores.models import StoreStatus

from .models import OrderSequence


def margin_percent() -> Decimal:
    return PlatformSettings.load().marketplace_margin_percent


def customer_price(store_price: int, margin: Decimal) -> int:
    """Store price + margin, rounded up to the MRU (the customer never pays less)."""
    value = Decimal(store_price) * (100 + margin) / 100
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _price_expression(field: str, margin: Decimal):
    factor = (100 + margin) / 100
    return Ceil(
        ExpressionWrapper(
            F(field) * Value(factor, output_field=DecimalField(max_digits=7, decimal_places=4)),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        )
    )


def offers() -> QuerySet[StoreProduct]:
    """What the marketplace may sell: new, active items in stock in an active store."""
    return StoreProduct.objects.filter(
        condition=Condition.NEW,
        is_active=True,
        quantity__gt=0,
        store__status=StoreStatus.ACTIVE,
        variant__is_active=True,
        variant__product__status=ProductStatus.ACTIVE,
    )


def _cheapest(filter_field: str, value_field: str):
    return Subquery(
        offers()
        .filter(**{filter_field: OuterRef("pk")})
        .order_by("sale_price", "created_at")
        .values(value_field)[:1]
    )


def products(margin: Decimal) -> QuerySet[Product]:
    """Product cards: only products with at least one offer, priced from the cheapest."""
    return (
        Product.objects.filter(category__is_active=True)
        .annotate(min_store_price=_cheapest("variant__product", "sale_price"))
        .filter(min_store_price__isnull=False)
        .annotate(price=_price_expression("min_store_price", margin))
        .select_related("brand", "category")
    )


def variants_of(product: Product, margin: Decimal) -> list[Variant]:
    largest_stock = Subquery(
        offers().filter(variant=OuterRef("pk")).order_by("-quantity").values("quantity")[:1]
    )
    rows = (
        product.variants.filter(is_active=True)
        .annotate(
            min_store_price=_cheapest("variant", "sale_price"),
            warranty=_cheapest("variant", "warranty_months"),
            max_quantity=largest_stock,
        )
        .order_by("name")
    )
    for variant in rows:
        variant.price = (
            customer_price(variant.min_store_price, margin)
            if variant.min_store_price is not None
            else None
        )
    return list(rows)


def categories() -> QuerySet[Category]:
    in_stock = Q(products__variants__in=Variant.objects.filter(pk__in=offers().values("variant")))
    return (
        Category.objects.filter(is_active=True)
        .annotate(product_count=Count("products", filter=in_stock, distinct=True))
        .order_by("trade", "sort_order", "name")
    )


def best_offer(variant_id, quantity: Decimal) -> StoreProduct | None:
    """The cheapest store that can serve the whole quantity on its own."""
    return (
        offers()
        .filter(variant_id=variant_id, quantity__gte=quantity)
        .select_related("variant__product__category", "variant__product__brand")
        .order_by("sale_price", "created_at")
        .first()
    )


def largest_stock(variant_id) -> Decimal:
    offer = offers().filter(variant_id=variant_id).order_by("-quantity").first()
    return offer.quantity if offer else Decimal(0)


def next_order_number() -> str:
    """Gapless, monthly: MP-2611-0001. The counter row stays locked until commit."""
    series = f"MP-{timezone.localdate():%y%m}"
    table = OrderSequence._meta.db_table  # a model constant; values are parameters
    sql = (
        f"INSERT INTO {table} (series, last_value) VALUES (%s, 1) "  # noqa: S608  # nosec B608
        f"ON CONFLICT (series) DO UPDATE SET last_value = {table}.last_value + 1 "
        "RETURNING last_value"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [series])
        value = cursor.fetchone()[0]
    return f"{series}-{value:04d}"
