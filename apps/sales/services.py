"""Till, sales, credits and credit notes. All amounts are integer MRU, VAT included."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import ApiError, Conflict, Forbidden
from apps.core.sequences import next_number
from apps.inventory.models import MovementKind, SerialStatus, SerialUnit
from apps.inventory.services import lock_products, move
from apps.stores.access import has_perm
from apps.stores.roles import Perm

from .models import (
    CashSession,
    Credit,
    CreditNote,
    CreditNoteLine,
    Expense,
    Payment,
    PaymentMethod,
    Sale,
    SaleLine,
)

DEFAULT_CREDIT_DAYS = 30


def _vat(store, amount: int) -> int:
    if not store.vat_enabled or amount <= 0:
        return 0
    return round(amount * store.vat_rate / (100 + store.vat_rate))


# --- Cash sessions --------------------------------------------------------


def open_session(store, user, opening_float: int) -> CashSession:
    try:
        with transaction.atomic():
            return CashSession.objects.create(
                store=store, opened_by=user, opening_float=opening_float
            )
    except IntegrityError as exc:
        raise Conflict("cash_session_already_open", "You already have an open till.") from exc


def my_open_session(store, user) -> CashSession | None:
    return CashSession.objects.filter(
        store=store, opened_by=user, status=CashSession.Status.OPEN
    ).first()


def require_session(store, user, session: CashSession | None = None) -> CashSession:
    session = session or my_open_session(store, user)
    if session is None or session.status != CashSession.Status.OPEN:
        raise Conflict("no_open_cash_session", "Open a till first.")
    return session


def session_totals(session: CashSession) -> dict:
    payments = Payment.objects.filter(cash_session=session)
    by_method = {m: 0 for m in PaymentMethod.values}
    for row in payments.values("method").annotate(total=Sum("amount")):
        by_method[row["method"]] = row["total"]

    def total(queryset, field="amount"):
        return queryset.aggregate(t=Sum(field))["t"] or 0

    sales = Sale.objects.filter(cash_session=session)
    expenses = Expense.objects.filter(cash_session=session)
    cash_expenses = total(expenses.filter(method=PaymentMethod.CASH))
    return {
        "sales_count": sales.count(),
        "sales_total": total(sales, "total"),
        "discount_total": total(sales, "discount_total"),
        "vat_total": total(sales, "vat_total"),
        "credit_issued": total(sales, "credit_total"),
        "credit_repayments": total(payments.filter(kind=Payment.Kind.CREDIT_REPAYMENT)),
        "refunds": -total(payments.filter(kind=Payment.Kind.REFUND)),
        "expenses": total(expenses),
        "payments_by_method": by_method,
        "expected_cash": session.opening_float + by_method[PaymentMethod.CASH] - cash_expenses,
    }


@transaction.atomic
def close_session(request, session: CashSession, counted_cash: int, note: str = "") -> CashSession:
    session = CashSession.objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.OPEN:
        raise Conflict("cash_session_closed", "This till is already closed.")
    if session.opened_by_id != request.user.id and request.store_role not in {"owner", "manager"}:
        raise Forbidden("permission_denied", "Only the cashier or a manager can close this till.")
    totals = session_totals(session)
    session.number = next_number(session.store_id, "Z")
    session.status = CashSession.Status.CLOSED
    session.closed_by = request.user
    session.closed_at = timezone.now()
    session.expected_cash = totals["expected_cash"]
    session.counted_cash = counted_cash
    session.difference = counted_cash - totals["expected_cash"]
    session.totals = totals
    session.closing_note = note
    session.save()
    audit.record(
        request,
        "cash_session.closed",
        target=session,
        store=request.store,
        difference=session.difference,
    )
    return session


# --- Sales ----------------------------------------------------------------


@transaction.atomic
def create_sale(
    request,
    *,
    lines: list[dict],
    payments: list[dict],
    customer=None,
    cash_session=None,
    due_date=None,
    note: str = "",
) -> Sale:
    store, user = request.store, request.user
    session = require_session(store, user, cash_session)
    products = lock_products(line["store_product"].id for line in lines)

    sale = Sale(
        store=store,
        number=next_number(store.id, "V", monthly=True),
        cash_session=session,
        customer=customer,
        seller=user,
        note=note,
        subtotal=0,
        total=0,
    )
    prepared = []
    for index, line in enumerate(lines):
        product = products[line["store_product"].id]
        if not product.is_active:
            raise ApiError(
                "product_inactive",
                "This product is not for sale.",
                extra={"field": f"lines.{index}.store_product"},
            )
        quantity: Decimal = line["quantity"]
        serial_unit = None
        unit_cost = product.avg_cost
        if product.tracks_serial:
            serial = (line.get("serial") or "").strip()
            if not serial or quantity != 1:
                raise ApiError(
                    "serial_required",
                    "Scan the IMEI / serial number (1 unit per line).",
                    extra={"field": f"lines.{index}.serial"},
                )
            serial_unit = (
                SerialUnit.objects.select_for_update()
                .filter(store_product=product, serial=serial, status=SerialStatus.IN_STOCK)
                .first()
            )
            if serial_unit is None:
                raise Conflict(
                    "serial_not_in_stock",
                    f"{serial} is not in stock for this product.",
                    extra={"field": f"lines.{index}.serial", "serial": serial},
                )
            unit_cost = serial_unit.unit_cost
        elif line.get("serial"):
            raise ApiError(
                "serials_not_tracked",
                "This product does not track serial numbers.",
                extra={"field": f"lines.{index}.serial"},
            )
        gross = round(quantity * product.sale_price)
        discount = line.get("discount", 0)
        if discount > gross:
            raise ApiError(
                "discount_too_high",
                "Discount is larger than the line.",
                extra={"field": f"lines.{index}.discount"},
            )
        prepared.append((product, quantity, serial_unit, unit_cost, gross, discount))
        sale.subtotal += gross
        sale.discount_total += discount

    over_limit = sale.discount_total * 100 > sale.subtotal * store.max_discount_percent
    if over_limit and not has_perm(request, Perm.SALES_DISCOUNT_OVERRIDE):
        raise Forbidden(
            "discount_requires_approval",
            f"Discounts above {store.max_discount_percent}% need a manager.",
            extra={"max_discount_percent": store.max_discount_percent},
        )

    sale.total = sale.subtotal - sale.discount_total
    paid = sum(p["amount"] for p in payments)
    if paid > sale.total:
        raise ApiError(
            "overpaid",
            "Payments exceed the total. Record the change, not the cash handed over.",
            extra={"total": sale.total},
        )
    sale.paid_total = paid
    sale.credit_total = sale.total - paid
    if sale.credit_total and customer is None:
        raise ApiError("customer_required_for_credit", "Choose a customer to sell on credit.")
    sale.save()

    for product, quantity, serial_unit, unit_cost, gross, discount in prepared:
        line_total = gross - discount
        sale_line = SaleLine.objects.create(
            store=store,
            sale=sale,
            store_product=product,
            serial_unit=serial_unit,
            description=product.variant.full_name
            + (" (occasion)" if product.condition == "used" else ""),
            quantity=quantity,
            unit_price=product.sale_price,
            discount=discount,
            line_total=line_total,
            vat_amount=_vat(store, line_total),
            unit_cost=unit_cost,
            warranty_months=product.warranty_months,
        )
        sale.vat_total += sale_line.vat_amount
        sale.cost_total += round(unit_cost * quantity)
        if serial_unit:
            serial_unit.status = SerialStatus.SOLD
            serial_unit.save(update_fields=["status", "updated_at"])
        move(
            product,
            kind=MovementKind.SALE,
            quantity=-quantity,
            user=user,
            unit_cost=unit_cost,
            reference=sale.number,
            source_id=sale.id,
            serial=serial_unit.serial if serial_unit else "",
        )
    sale.save(update_fields=["vat_total", "cost_total"])

    for payment in payments:
        Payment.objects.create(
            store=store,
            kind=Payment.Kind.SALE,
            sale=sale,
            cash_session=session,
            created_by=user,
            **payment,
        )
    if sale.credit_total:
        Credit.objects.create(
            store=store,
            number=next_number(store.id, "CR"),
            sale=sale,
            customer=customer,
            amount=sale.credit_total,
            balance=sale.credit_total,
            due_date=due_date or (timezone.localdate() + timedelta(days=DEFAULT_CREDIT_DAYS)),
        )
    return sale


@transaction.atomic
def repay_credit(
    request, credit: Credit, *, amount: int, method: str, reference: str = ""
) -> Payment:
    credit = Credit.objects.select_for_update().get(pk=credit.pk)
    if amount > credit.balance:
        raise ApiError(
            "overpaid", "Amount is more than what is owed.", extra={"balance": credit.balance}
        )
    session = my_open_session(request.store, request.user)
    if method == PaymentMethod.CASH:
        session = require_session(request.store, request.user, session)
    payment = Payment.objects.create(
        store=request.store,
        kind=Payment.Kind.CREDIT_REPAYMENT,
        credit=credit,
        sale=credit.sale,
        method=method,
        amount=amount,
        reference=reference,
        cash_session=session,
        created_by=request.user,
    )
    credit.balance -= amount
    if credit.balance == 0:
        credit.status = Credit.Status.SETTLED
    credit.save(update_fields=["balance", "status", "updated_at"])
    return payment


@transaction.atomic
def create_credit_note(
    request, *, sale: Sale, lines: list[dict], refund_method: str, reason: str, restock: bool = True
) -> CreditNote:
    store, user = request.store, request.user
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    sale_lines = {sl.id: sl for sl in SaleLine.objects.select_for_update().filter(sale=sale)}
    products = lock_products(
        sale_lines[line["sale_line"].id].store_product_id
        for line in lines
        if line["sale_line"].id in sale_lines
    )
    note = CreditNote.objects.create(
        store=store,
        number=next_number(store.id, "AV", monthly=True),
        sale=sale,
        total=0,
        refund_method=refund_method,
        reason=reason,
        restock=restock,
        created_by=user,
    )
    total = 0
    for index, line in enumerate(lines):
        sale_line = sale_lines.get(line["sale_line"].id)
        if sale_line is None:
            raise ApiError(
                "line_not_in_sale",
                "This line is not part of the sale.",
                extra={"field": f"lines.{index}.sale_line"},
            )
        quantity: Decimal = line["quantity"]
        if quantity > sale_line.quantity - sale_line.refunded_quantity:
            raise ApiError(
                "refund_exceeds_sold",
                "More than what is left to return.",
                extra={"field": f"lines.{index}.quantity"},
            )
        amount = round(sale_line.line_total * quantity / sale_line.quantity)
        CreditNoteLine.objects.create(
            store=store, credit_note=note, sale_line=sale_line, quantity=quantity, amount=amount
        )
        sale_line.refunded_quantity += quantity
        sale_line.save(update_fields=["refunded_quantity", "updated_at"])
        total += amount
        if restock:
            serial = ""
            if sale_line.serial_unit_id:
                SerialUnit.objects.filter(pk=sale_line.serial_unit_id).update(
                    status=SerialStatus.IN_STOCK
                )
                serial = sale_line.serial_unit.serial
            move(
                products[sale_line.store_product_id],
                kind=MovementKind.RETURN,
                quantity=quantity,
                unit_cost=sale_line.unit_cost,
                user=user,
                reference=note.number,
                source_id=note.id,
                serial=serial,
            )

    if refund_method == "credit":
        credit = Credit.objects.select_for_update().filter(sale=sale).first()
        if credit is None or credit.balance < total:
            raise ApiError("credit_too_small", "The customer owes less than this credit note.")
        credit.balance -= total
        credit.status = Credit.Status.SETTLED if credit.balance == 0 else credit.status
        credit.save(update_fields=["balance", "status", "updated_at"])
    else:
        session = my_open_session(store, user)
        if refund_method == PaymentMethod.CASH:
            session = require_session(store, user, session)
        Payment.objects.create(
            store=store,
            kind=Payment.Kind.REFUND,
            sale=sale,
            credit_note=note,
            method=refund_method,
            amount=-total,
            cash_session=session,
            created_by=user,
        )
    note.total = total
    note.save(update_fields=["total"])
    sale.refunded_total += total
    fully = all(sl.refunded_quantity >= sl.quantity for sl in sale_lines.values())
    sale.status = Sale.Status.REFUNDED if fully else Sale.Status.PARTIALLY_REFUNDED
    sale.save(update_fields=["refunded_total", "status", "updated_at"])
    audit.record(
        request,
        "sale.credit_note",
        target=note,
        store=store,
        sale=sale.number,
        total=total,
        reason=reason,
    )
    return note


def record_expense(request, **data) -> Expense:
    session = my_open_session(request.store, request.user)
    if data["method"] == PaymentMethod.CASH:
        session = require_session(request.store, request.user, session)
    return Expense.objects.create(
        store=request.store, cash_session=session, created_by=request.user, **data
    )
