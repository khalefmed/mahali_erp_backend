"""Stock rules. Every quantity change goes through `move()`:
- the store product row is locked (SELECT … FOR UPDATE), so two tills cannot oversell;
- stock can never go below zero (also enforced by a DB constraint);
- incoming goods with a cost update the weighted average cost.
"""

from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import ApiError, Conflict
from apps.core.sequences import next_number

from .models import (
    AdjustmentReason,
    MovementKind,
    Receipt,
    ReceiptLine,
    SerialStatus,
    SerialUnit,
    StockAdjustment,
    StockMovement,
    StoreProduct,
)


def lock_products(ids) -> dict:
    """Locks rows in a stable order (by id) to avoid deadlocks between tills."""
    products = (
        StoreProduct.objects.select_for_update(of=("self",))
        .select_related("variant__product__category")
        .filter(id__in=set(ids))
        .order_by("id")
    )
    return {p.id: p for p in products}


def move(
    product: StoreProduct,
    *,
    kind: str,
    quantity: Decimal,
    user,
    unit_cost: int | None = None,
    reference: str = "",
    source_id=None,
    serial: str = "",
    note: str = "",
) -> StockMovement:
    """`product` must come from `lock_products()` (row locked in this transaction)."""
    quantity = Decimal(quantity)
    new_quantity = product.quantity + quantity
    if new_quantity < 0:
        raise Conflict(
            "insufficient_stock",
            f"Only {product.quantity} in stock.",
            extra={"store_product": str(product.id), "available": str(product.quantity)},
        )
    if (
        quantity > 0
        and unit_cost is not None
        and kind in {MovementKind.RECEIPT, MovementKind.ADJUSTMENT}
    ):
        total_value = product.avg_cost * product.quantity + unit_cost * quantity
        product.avg_cost = round(total_value / new_quantity) if new_quantity else unit_cost
    product.quantity = new_quantity
    product.save(update_fields=["quantity", "avg_cost", "updated_at"])
    return StockMovement.objects.create(
        store_id=product.store_id,
        store_product=product,
        kind=kind,
        quantity=quantity,
        unit_cost=product.avg_cost if unit_cost is None else unit_cost,
        balance_after=new_quantity,
        reference=reference,
        source_id=source_id,
        serial=serial,
        note=note,
        created_by=user,
    )


def _check_serials(product: StoreProduct, quantity: Decimal, serials: list[str], field: str):
    if product.tracks_serial:
        if quantity != int(quantity) or len(serials) != int(quantity):
            raise ApiError(
                "serials_required",
                "Enter one serial number / IMEI per unit for this product.",
                extra={"field": field},
            )
        if len(set(serials)) != len(serials):
            raise ApiError(
                "duplicate_serial", "The same serial number appears twice.", extra={"field": field}
            )
    elif serials:
        raise ApiError(
            "serials_not_tracked",
            "This product does not track serial numbers.",
            extra={"field": field},
        )


@transaction.atomic
def receive(
    store, user, *, lines: list[dict], supplier=None, supplier_reference: str = "", note: str = ""
) -> Receipt:
    products = lock_products(line["store_product"].id for line in lines)
    receipt = Receipt.objects.create(
        store=store,
        number=next_number(store.id, "BR", monthly=True),
        supplier=supplier,
        supplier_reference=supplier_reference,
        note=note,
        created_by=user,
    )
    total = 0
    for index, line in enumerate(lines):
        product = products[line["store_product"].id]
        quantity, cost = line["quantity"], line["unit_cost"]
        serials = [s.strip() for s in line.get("serials", []) if s.strip()]
        _check_serials(product, quantity, serials, f"lines.{index}.serials")
        line_total = round(quantity * cost)
        receipt_line = ReceiptLine.objects.create(
            store=store,
            receipt=receipt,
            store_product=product,
            quantity=quantity,
            unit_cost=cost,
            line_total=line_total,
        )
        total += line_total
        if serials:
            taken = set(
                SerialUnit.objects.filter(store=store, serial__in=serials).values_list(
                    "serial", flat=True
                )
            )
            if taken:
                raise Conflict(
                    "serial_exists",
                    "Some serial numbers are already registered.",
                    extra={"serials": sorted(taken)},
                )
            SerialUnit.objects.bulk_create(
                SerialUnit(
                    store=store,
                    store_product=product,
                    serial=s,
                    unit_cost=cost,
                    receipt_line=receipt_line,
                )
                for s in serials
            )
        move(
            product,
            kind=MovementKind.RECEIPT,
            quantity=quantity,
            unit_cost=cost,
            user=user,
            reference=receipt.number,
            source_id=receipt.id,
        )
    receipt.total_cost = total
    receipt.save(update_fields=["total_cost"])
    return receipt


@transaction.atomic
def adjust(
    store,
    user,
    *,
    store_product: StoreProduct,
    reason: str,
    note: str = "",
    quantity_delta: Decimal | None = None,
    counted_quantity: Decimal | None = None,
    unit_cost: int | None = None,
    serials: list[str] | None = None,
) -> StockAdjustment:
    product = lock_products([store_product.id])[store_product.id]
    if counted_quantity is not None:
        quantity_delta = Decimal(counted_quantity) - product.quantity
    if not quantity_delta:
        raise ApiError("no_change", "The quantity does not change.")
    serials = [s.strip() for s in (serials or []) if s.strip()]
    _check_serials(product, abs(quantity_delta), serials, "serials")
    if quantity_delta > 0 and reason not in {
        AdjustmentReason.INITIAL,
        AdjustmentReason.INVENTORY_COUNT,
        AdjustmentReason.OTHER,
    }:
        raise ApiError("invalid_reason", "This reason can only remove stock.")
    cost = unit_cost if (quantity_delta > 0 and unit_cost is not None) else product.avg_cost
    adjustment = StockAdjustment.objects.create(
        store=store,
        number=next_number(store.id, "AJ", monthly=True),
        store_product=product,
        quantity_delta=quantity_delta,
        unit_cost=cost,
        reason=reason,
        note=note,
        serials=serials,
        created_by=user,
    )
    if serials and quantity_delta > 0:
        taken = set(
            SerialUnit.objects.filter(store=store, serial__in=serials).values_list(
                "serial", flat=True
            )
        )
        if taken:
            raise Conflict(
                "serial_exists",
                "Some serial numbers are already registered.",
                extra={"serials": sorted(taken)},
            )
        SerialUnit.objects.bulk_create(
            SerialUnit(store=store, store_product=product, serial=s, unit_cost=cost)
            for s in serials
        )
    elif serials:
        units = SerialUnit.objects.filter(
            store=store, store_product=product, serial__in=serials, status=SerialStatus.IN_STOCK
        )
        if units.count() != len(serials):
            raise Conflict("serial_not_in_stock", "Some serial numbers are not in stock.")
        units.update(status=SerialStatus.LOST)
    move(
        product,
        kind=MovementKind.ADJUSTMENT,
        quantity=quantity_delta,
        unit_cost=cost if quantity_delta > 0 else None,
        user=user,
        reference=adjustment.number,
        source_id=adjustment.id,
        note=note,
    )
    return adjustment
