"""Meysara, Infinity's pay-in-4 on the marketplace (Figma "Spécifications — Meysara").

Who may pay in instalments, and how much, is decided here, never by the apps:

1. at least `meysara_required_orders` (3) orders delivered and paid;
2. no instalment more than `LATE_DAYS` (7) days late;
3. one plan at a time;
4. order total ≥ `meysara_min_total` (3 000 MRU);
5. financed share ≤ `meysara_max_financed` (60 000 MRU).

The first failing rule is the reason. Ceiling: 50 % (choices 25/50), then 100 % (50/100)
once the latest plan was paid off without an instalment more than 7 days late.

Amounts are whole MRU: financed = floor(total * percent / 100), the rest is paid on delivery;
instalment = floor(financed / 4) and the remainder goes to the first instalments. They
fall due every 14 days from the delivery day.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.console.models import PlatformSettings
from apps.core.exceptions import ApiError, Conflict

from .models import (
    MeysaraInstalment,
    MeysaraPlan,
    MeysaraPlanStatus,
    Order,
    OrderStatus,
)

INSTALMENTS = 4
INTERVAL_DAYS = 14
LATE_DAYS = 7
OPEN_PLANS = {MeysaraPlanStatus.RESERVED, MeysaraPlanStatus.ACTIVE}


class Reason:
    DISABLED = "meysara_disabled"
    HISTORY = "meysara_history_insufficient"
    OVERDUE = "meysara_overdue"
    PLAN_IN_PROGRESS = "meysara_plan_in_progress"
    AMOUNT_TOO_LOW = "meysara_amount_too_low"
    LIMIT_EXCEEDED = "meysara_limit_exceeded"

    ALL = [DISABLED, HISTORY, OVERDUE, PLAN_IN_PROGRESS, AMOUNT_TOO_LOW, LIMIT_EXCEEDED]


@dataclass
class Offer:
    eligible: bool
    reason: str | None
    max_percent: int | None
    choices: list[int] = field(default_factory=list)
    paid_orders: int = 0
    required_orders: int = 0
    min_total: int = 0
    max_financed: int = 0


def financed(total: int, percent: int) -> int:
    return total * percent // 100


def split(amount: int, count: int = INSTALMENTS) -> list[int]:
    """21 398 → [5350, 5350, 5349, 5349]"""
    base, remainder = divmod(amount, count)
    return [base + (1 if i < remainder else 0) for i in range(count)]


def paid_orders(customer) -> int:
    """Delivered orders, Meysara ones counting only once their plan is paid off."""
    return (
        Order.objects.filter(customer=customer, status=OrderStatus.DELIVERED)
        .exclude(meysara_plan__status__in=OPEN_PLANS)
        .count()
    )


def _late_since(today: date) -> date:
    return today - timedelta(days=LATE_DAYS)


def is_overdue(customer, today: date) -> bool:
    return MeysaraInstalment.objects.filter(
        plan__customer=customer,
        plan__status=MeysaraPlanStatus.ACTIVE,
        paid_at__isnull=True,
        due_date__lt=_late_since(today),
    ).exists()


def _paid_on_time(plan: MeysaraPlan) -> bool:
    return all(
        i.paid_at and i.due_date and i.paid_at.date() <= i.due_date + timedelta(days=LATE_DAYS)
        for i in plan.instalments.all()
    )


def max_percent(customer) -> int:
    latest = (
        MeysaraPlan.objects.filter(customer=customer, status=MeysaraPlanStatus.PAID)
        .prefetch_related("instalments")
        .order_by("-closed_at")
        .first()
    )
    return 100 if latest and _paid_on_time(latest) else 50


def offer(customer, total: int, today: date | None = None) -> Offer:
    today = today or timezone.localdate()
    settings = PlatformSettings.load()
    base = {
        "required_orders": settings.meysara_required_orders,
        "min_total": settings.meysara_min_total,
        "max_financed": settings.meysara_max_financed,
    }

    def no(reason: str, paid: int = 0) -> Offer:
        return Offer(False, reason, None, [], paid_orders=paid, **base)

    if not settings.meysara_enabled:
        return no(Reason.DISABLED)
    paid = paid_orders(customer)
    if paid < settings.meysara_required_orders:
        return no(Reason.HISTORY, paid)
    if is_overdue(customer, today):
        return no(Reason.OVERDUE, paid)
    if MeysaraPlan.objects.filter(customer=customer, status__in=OPEN_PLANS).exists():
        return no(Reason.PLAN_IN_PROGRESS, paid)
    if total < settings.meysara_min_total:
        return no(Reason.AMOUNT_TOO_LOW, paid)
    ceiling = max_percent(customer)
    choices = [50, 100] if ceiling == 100 else [25, 50]
    if financed(total, choices[0]) > settings.meysara_max_financed:
        return no(Reason.LIMIT_EXCEEDED, paid)
    return Offer(True, None, ceiling, choices, paid_orders=paid, **base)


def reserve(order: Order, percent: int) -> MeysaraPlan:
    """At checkout, inside the order transaction. Raises `meysara_not_allowed`."""
    current = offer(order.customer, order.total)
    if not current.eligible or percent not in current.choices:
        raise Conflict(
            "meysara_not_allowed",
            "Meysara is not available for this order.",
            extra={
                "field": "meysara_percent",
                "reason": current.reason,
                "choices": current.choices,
            },
        )
    part = financed(order.total, percent)
    plan = MeysaraPlan.objects.create(
        order=order,
        customer=order.customer,
        percent=percent,
        financed=part,
        on_delivery=order.total - part,
    )
    MeysaraInstalment.objects.bulk_create(
        MeysaraInstalment(plan=plan, number=n, amount=amount)
        for n, amount in enumerate(split(part), start=1)
    )
    return plan


def activate(order: Order, delivered_on: date) -> None:
    """The order was delivered: instalments fall due every 14 days from today."""
    plan = MeysaraPlan.objects.filter(order=order, status=MeysaraPlanStatus.RESERVED).first()
    if not plan:
        return
    for instalment in plan.instalments.all():
        instalment.due_date = delivered_on + timedelta(days=INTERVAL_DAYS * instalment.number)
        instalment.save(update_fields=["due_date", "updated_at"])
    plan.status = MeysaraPlanStatus.ACTIVE
    plan.activated_at = timezone.now()
    plan.save(update_fields=["status", "activated_at", "updated_at"])


def cancel(order: Order) -> None:
    MeysaraPlan.objects.filter(order=order, status__in=OPEN_PLANS).update(
        status=MeysaraPlanStatus.CANCELLED, closed_at=timezone.now(), updated_at=timezone.now()
    )


@transaction.atomic
def pay(order: Order, *, number: int, via: str, actor) -> MeysaraPlan:
    """Mahali records an instalment the shopper paid (mobile money or cash)."""
    plan = MeysaraPlan.objects.select_for_update().filter(order=order).first()
    if not plan:
        raise ApiError("not_a_meysara_order", "This order is not paid with Meysara.")
    if plan.status != MeysaraPlanStatus.ACTIVE:
        raise Conflict(
            "meysara_plan_not_active",
            "Instalments are paid once the order is delivered.",
            extra={"status": plan.status},
        )
    instalment = plan.instalments.filter(number=number).first()
    if not instalment:
        raise ApiError("invalid_instalment", "No such instalment.", extra={"field": "number"})
    if instalment.paid_at:
        raise Conflict("instalment_already_paid", "This instalment is already paid.")
    instalment.paid_at = timezone.now()
    instalment.paid_via = via
    instalment.recorded_by = actor
    instalment.save(update_fields=["paid_at", "paid_via", "recorded_by", "updated_at"])
    if not plan.instalments.filter(paid_at__isnull=True).exists():
        plan.status = MeysaraPlanStatus.PAID
        plan.closed_at = timezone.now()
        plan.save(update_fields=["status", "closed_at", "updated_at"])
    return plan


def instalment_status(instalment: MeysaraInstalment, today: date | None = None) -> str:
    """paid · waiting_delivery (no date yet) · upcoming · due (today or late) · overdue (> 7 d)."""
    today = today or timezone.localdate()
    if instalment.paid_at:
        return "paid"
    if not instalment.due_date:
        return "waiting_delivery"
    if instalment.due_date < _late_since(today):
        return "overdue"
    if instalment.due_date <= today:
        return "due"
    return "upcoming"
