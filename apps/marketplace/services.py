"""Marketplace writes: pricing a cart, placing an order, and the order's life in the
stores (accept, reject, ready) and at Mahali (deliver, cancel).

Lifecycle::

    Order       pending ──(every store accepted)──> confirmed ──(every store ready)──> ready
                   │                                                                   │
                   └──── cancelled <── (customer, Mahali, or a store rejects) ─────────┤
                                                                        delivered <────┘
    StoreOrder  pending ─> accepted ─> ready ─> picked_up       (or rejected / cancelled)

Stock leaves the store when the store accepts (it picks the serial numbers), and comes
back if the order is cancelled afterwards.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApiError, Conflict
from apps.core.notifications import notify
from apps.core.tenancy import marketplace_read, store_context
from apps.inventory.models import MovementKind, SerialStatus, SerialUnit, StoreProduct
from apps.inventory.services import lock_products, move
from apps.stores.models import Store

from . import contract, meysara, selectors
from .models import (
    Order,
    OrderLine,
    OrderStatus,
    PaymentMethod,
    StoreOrder,
    StoreOrderLine,
    StoreOrderStatus,
)

OPEN_STORE_STATUSES = {StoreOrderStatus.PENDING, StoreOrderStatus.ACCEPTED, StoreOrderStatus.READY}
STOCK_OUT_STATUSES = {StoreOrderStatus.ACCEPTED, StoreOrderStatus.READY}


@dataclass
class PricedLine:
    variant_id: object
    quantity: Decimal
    offer: StoreProduct | None
    unit_price: int | None
    max_quantity: Decimal
    description: str = ""
    image_url: str = ""

    @property
    def available(self) -> bool:
        return self.offer is not None

    @property
    def line_total(self) -> int | None:
        return None if self.unit_price is None else round(self.quantity * self.unit_price)


def _merge(lines: list[dict]) -> list[tuple]:
    merged: dict = {}
    for line in lines:
        key = line["variant"].id
        merged[key] = (line["variant"], merged.get(key, (None, Decimal(0)))[1] + line["quantity"])
    return list(merged.values())


def _check_quantity(variant, quantity: Decimal, index: int) -> None:
    if quantity <= 0:
        raise ApiError(
            "invalid_quantity",
            "Quantity must be positive.",
            extra={"field": f"lines.{index}.quantity"},
        )
    if variant.product.category.tracks_serial and quantity != quantity.to_integral_value():
        raise ApiError(
            "whole_quantity_required",
            "This product is sold by the unit.",
            extra={"field": f"lines.{index}.quantity"},
        )


def price_lines(lines: list[dict], *, strict: bool) -> tuple[list[PricedLine], int]:
    """Prices a cart at the cheapest store able to serve each line. With `strict`, an
    unavailable line raises `insufficient_stock`; otherwise it comes back unavailable."""
    margin = selectors.margin_percent()
    priced = []
    with marketplace_read():
        for index, (variant, quantity) in enumerate(_merge(lines)):
            _check_quantity(variant, quantity, index)
            offer = selectors.best_offer(variant.id, quantity)
            if offer is None and strict:
                raise Conflict(
                    "insufficient_stock",
                    "Not enough stock for this product.",
                    extra={
                        "field": f"lines.{index}.quantity",
                        "variant": str(variant.id),
                        "available": str(selectors.largest_stock(variant.id)),
                    },
                )
            priced.append(
                PricedLine(
                    variant_id=variant.id,
                    quantity=quantity,
                    offer=offer,
                    unit_price=selectors.customer_price(offer.sale_price, margin)
                    if offer
                    else None,
                    max_quantity=selectors.largest_stock(variant.id),
                    description=_description(variant),
                    image_url=variant.product.image_url,
                )
            )
    total = sum(line.line_total or 0 for line in priced)
    return priced, total


def _description(variant) -> str:
    brand = variant.product.brand.name if variant.product.brand_id else ""
    return " ".join(part for part in [brand, variant.full_name] if part)


@transaction.atomic
def place_order(
    customer,
    *,
    lines: list[dict],
    delivery: dict,
    note: str = "",
    payment_method: str = PaymentMethod.CASH_ON_DELIVERY,
    meysara_percent: int | None = None,
    meysara_contract: dict | None = None,
    request=None,
) -> Order:
    if not lines:
        raise ApiError("empty_cart", "Add at least one product.", extra={"field": "lines"})
    if payment_method == PaymentMethod.MEYSARA:
        if meysara_percent is None:
            raise ApiError(
                "meysara_percent_required",
                "Choose the share paid with Meysara.",
                extra={"field": "meysara_percent"},
            )
        if not (meysara_contract or {}).get("accepted"):
            raise ApiError(
                "meysara_contract_required",
                "Read and accept the Meysara contract first.",
                extra={"field": "meysara_contract"},
            )
        # One checkout at a time per shopper: the "one plan" rule must hold.
        type(customer).objects.select_for_update().get(pk=customer.pk)
    priced, total = price_lines(lines, strict=True)
    order = Order.objects.create(
        payment_method=payment_method,
        number=selectors.next_order_number(),
        customer=customer,
        margin_percent=selectors.margin_percent(),
        subtotal=total,
        total=total,
        note=note,
        **delivery,
    )
    by_store = defaultdict(list)
    for line in priced:
        order_line = OrderLine.objects.create(
            order=order,
            variant_id=line.variant_id,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            line_total=line.line_total,
        )
        by_store[line.offer.store_id].append((line, order_line))
    signed = None
    if payment_method == PaymentMethod.MEYSARA:
        plan = meysara.reserve(order, meysara_percent)
        signed = contract.sign(order, plan, meysara_contract, request)

    for store_id, items in by_store.items():
        with store_context(store_id):
            store_order = StoreOrder.objects.create(
                store_id=store_id,
                order=order,
                total=sum(round(line.quantity * line.offer.sale_price) for line, _ in items),
            )
            StoreOrderLine.objects.bulk_create(
                StoreOrderLine(
                    store_id=store_id,
                    store_order=store_order,
                    order_line=order_line,
                    store_product=line.offer,
                    quantity=line.quantity,
                    unit_price=line.offer.sale_price,
                    line_total=round(line.quantity * line.offer.sale_price),
                )
                for line, order_line in items
            )
        store = Store.objects.select_related("owner").get(pk=store_id)
        notify(
            store.owner,
            "marketplace_new_order",
            {"store": store, "order": order, "total": store_order.total, "lines": len(items)},
        )
    notify(customer, "marketplace_order_placed", {"order": order, "user": customer})
    if signed:
        notify(
            customer,
            "marketplace_meysara_contract",
            {"order": order, "user": customer, "contract": signed, "terms": signed.terms},
            language=signed.language,
        )
    return order


def _locked_store_order(store_order_id) -> StoreOrder:
    return StoreOrder.objects.select_for_update().select_related("order").get(pk=store_order_id)


def _refresh_order(order: Order) -> None:
    """Derives the order status from its store orders (read across stores)."""
    if order.status in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}:
        return
    with marketplace_read():
        statuses = set(StoreOrder.objects.filter(order=order).values_list("status", flat=True))
    now = timezone.now()
    if statuses == {StoreOrderStatus.READY}:
        order.status = OrderStatus.READY
        order.ready_at = order.ready_at or now
        order.confirmed_at = order.confirmed_at or now
    elif statuses and statuses <= STOCK_OUT_STATUSES:
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = order.confirmed_at or now
    else:
        order.status = OrderStatus.PENDING
    order.save(update_fields=["status", "confirmed_at", "ready_at", "updated_at"])


@transaction.atomic
def accept(request, store_order: StoreOrder, serials: dict) -> StoreOrder:
    """Takes the goods out of stock. `serials` = {store order line id: [serial, …]} for
    products that track serial numbers (one per unit)."""
    store_order = _locked_store_order(store_order.pk)
    if store_order.status != StoreOrderStatus.PENDING:
        raise Conflict(
            "store_order_not_pending",
            "This order was already handled.",
            extra={"status": store_order.status},
        )
    order = Order.objects.select_for_update().get(pk=store_order.order_id)
    if order.status == OrderStatus.CANCELLED:
        raise Conflict("order_cancelled", "The customer's order was cancelled.")
    lines = list(store_order.lines.order_by("id"))
    products = lock_products(line.store_product_id for line in lines)
    for index, line in enumerate(lines):
        product = products[line.store_product_id]
        if product.tracks_serial:
            line.serials = _take_serials(
                product, line, serials.get(line.id, []), index, order, request
            )
            line.save(update_fields=["serials", "updated_at"])
        else:
            move(
                product,
                kind=MovementKind.MARKETPLACE,
                quantity=-line.quantity,
                user=request.user,
                reference=order.number,
                source_id=store_order.id,
            )
    store_order.status = StoreOrderStatus.ACCEPTED
    store_order.accepted_at = timezone.now()
    store_order.decided_by = request.user
    store_order.save(update_fields=["status", "accepted_at", "decided_by", "updated_at"])
    _refresh_order(order)
    return store_order


def _take_serials(product, line, given: list[str], index: int, order, request) -> list[str]:
    field = f"lines.{index}.serials"
    wanted = [s.strip() for s in given if s.strip()]
    if len(wanted) != int(line.quantity) or len(set(wanted)) != len(wanted):
        raise ApiError(
            "serials_required",
            "Scan one serial number per unit.",
            extra={"field": field, "expected": int(line.quantity)},
        )
    units = {
        unit.serial: unit
        for unit in SerialUnit.objects.select_for_update().filter(
            store_product=product, serial__in=wanted, status=SerialStatus.IN_STOCK
        )
    }
    missing = [s for s in wanted if s not in units]
    if missing:
        raise Conflict(
            "serial_not_in_stock",
            "Some serial numbers are not in stock for this product.",
            extra={"field": field, "missing": missing},
        )
    for serial in wanted:
        unit = units[serial]
        unit.status = SerialStatus.SOLD
        unit.save(update_fields=["status", "updated_at"])
        move(
            product,
            kind=MovementKind.MARKETPLACE,
            quantity=Decimal(-1),
            user=request.user,
            unit_cost=unit.unit_cost,
            reference=order.number,
            source_id=line.store_order_id,
            serial=serial,
        )
    return wanted


@transaction.atomic
def mark_ready(request, store_order: StoreOrder) -> StoreOrder:
    store_order = _locked_store_order(store_order.pk)
    if store_order.status != StoreOrderStatus.ACCEPTED:
        raise Conflict(
            "store_order_not_accepted",
            "Accept the order first.",
            extra={"status": store_order.status},
        )
    store_order.status = StoreOrderStatus.READY
    store_order.ready_at = timezone.now()
    store_order.save(update_fields=["status", "ready_at", "updated_at"])
    _refresh_order(Order.objects.select_for_update().get(pk=store_order.order_id))
    return store_order


@transaction.atomic
def reject(request, store_order: StoreOrder, reason: str) -> StoreOrder:
    """A store that cannot serve its part cancels the whole order (v1: no reallocation)."""
    store_order = _locked_store_order(store_order.pk)
    if store_order.status != StoreOrderStatus.PENDING:
        raise Conflict(
            "store_order_not_pending",
            "This order was already handled.",
            extra={"status": store_order.status},
        )
    store_order.status = StoreOrderStatus.REJECTED
    store_order.reject_reason = reason
    store_order.closed_at = timezone.now()
    store_order.decided_by = request.user
    store_order.save(
        update_fields=["status", "reject_reason", "closed_at", "decided_by", "updated_at"]
    )
    cancel_order(store_order.order, reason="rejected_by_store", actor=request.user)
    return store_order


@transaction.atomic
def cancel_order(order: Order, *, reason: str, actor) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}:
        raise Conflict(
            "order_not_cancellable",
            "This order can no longer be cancelled.",
            extra={"status": order.status},
        )
    with marketplace_read():
        parts = list(StoreOrder.objects.filter(order=order).values_list("id", "store_id"))
    for store_order_id, store_id in parts:
        with store_context(store_id):
            store_order = _locked_store_order(store_order_id)
            if store_order.status not in OPEN_STORE_STATUSES:
                continue
            had_stock_out = store_order.status in STOCK_OUT_STATUSES
            if had_stock_out:
                _restock(store_order, actor)
            store_order.status = StoreOrderStatus.CANCELLED
            store_order.closed_at = timezone.now()
            store_order.save(update_fields=["status", "closed_at", "updated_at"])
            if had_stock_out:
                store = Store.objects.select_related("owner").get(pk=store_id)
                notify(
                    store.owner,
                    "marketplace_store_order_cancelled",
                    {"store": store, "order": order},
                )
    meysara.cancel(order)
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = reason
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancel_reason", "cancelled_at", "updated_at"])
    notify(order.customer, "marketplace_order_cancelled", {"order": order, "user": order.customer})
    return order


def _restock(store_order: StoreOrder, actor) -> None:
    lines = list(store_order.lines.order_by("id"))
    products = lock_products(line.store_product_id for line in lines)
    for line in lines:
        product = products[line.store_product_id]
        common = {
            "kind": MovementKind.MARKETPLACE,
            "user": actor,
            "reference": store_order.order.number,
            "source_id": store_order.id,
            "note": "Annulation commande marketplace",
        }
        if line.serials:
            units = SerialUnit.objects.select_for_update().filter(
                store_product=product, serial__in=line.serials
            )
            for unit in units:
                unit.status = SerialStatus.IN_STOCK
                unit.save(update_fields=["status", "updated_at"])
                move(
                    product,
                    quantity=Decimal(1),
                    unit_cost=unit.unit_cost,
                    serial=unit.serial,
                    **common,
                )
        else:
            move(product, quantity=line.quantity, **common)


def cancel_by_customer(order: Order) -> Order:
    if order.status not in {OrderStatus.PENDING, OrderStatus.CONFIRMED}:
        raise Conflict(
            "order_not_cancellable",
            "This order can no longer be cancelled.",
            extra={"status": order.status},
        )
    return cancel_order(order, reason="cancelled_by_customer", actor=order.customer)


@transaction.atomic
def deliver(order: Order, actor) -> Order:
    """Mahali collected every store's part and handed the order to the customer."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != OrderStatus.READY:
        raise Conflict(
            "order_not_ready",
            "Every store must mark its part ready first.",
            extra={"status": order.status},
        )
    now = timezone.now()
    with marketplace_read():
        parts = list(StoreOrder.objects.filter(order=order).values_list("id", "store_id"))
    for store_order_id, store_id in parts:
        with store_context(store_id):
            StoreOrder.objects.filter(pk=store_order_id, status=StoreOrderStatus.READY).update(
                status=StoreOrderStatus.PICKED_UP, picked_up_at=now, updated_at=now
            )
    order.status = OrderStatus.DELIVERED
    order.delivered_at = now
    order.save(update_fields=["status", "delivered_at", "updated_at"])
    meysara.activate(order, timezone.localdate())
    return order
