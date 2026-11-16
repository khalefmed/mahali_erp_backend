from calendar import monthrange
from datetime import date, timedelta

from django.db import transaction

from apps.core.exceptions import ApiError
from apps.sales import services as sales_services
from apps.sales.models import Expense, PaymentMethod

from .models import (
    ExpenseBudget,
    Frequency,
    MoneyTransfer,
    RecurringExpense,
    SupplierPayment,
)


def record_supplier_payment(request, **data) -> SupplierPayment:
    """Same rule as expenses: a cash payment comes out of my open till."""
    session = sales_services.my_open_session(request.store, request.user)
    if data["method"] == PaymentMethod.CASH:
        session = sales_services.require_session(request.store, request.user, session)
    return SupplierPayment.objects.create(
        store=request.store, cash_session=session, created_by=request.user, **data
    )


def transfer_money(request, **data) -> MoneyTransfer:
    if data["from_account"] == data["to_account"]:
        raise ApiError(
            "same_account", "Choose two different accounts.", extra={"field": "to_account"}
        )
    return MoneyTransfer.objects.create(store=request.store, created_by=request.user, **data)


def add_recurring_expense(request, **data) -> RecurringExpense:
    return RecurringExpense.objects.create(store=request.store, created_by=request.user, **data)


@transaction.atomic
def set_budgets(store, budgets: list[dict]) -> list[ExpenseBudget]:
    """Replace the monthly budgets: a category left out has no budget any more."""
    ExpenseBudget.objects.all().delete()
    return [ExpenseBudget.objects.create(store=store, **budget) for budget in budgets]


def _next(day: date, frequency: str) -> date:
    months = {Frequency.MONTHLY: 1, Frequency.QUARTERLY: 3}.get(frequency)
    if not months:
        return day + timedelta(weeks=1)
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


@transaction.atomic
def post_due_recurring(today: date) -> int:
    """Record the fixed charges due by `today` (runs in a store context). Variable bills
    (`variable_amount`) are left for the owner to type with the real amount; their date
    still moves on. Cash ones aren't tied to a till: nobody counted them out of it."""
    posted = 0
    due = RecurringExpense.objects.select_for_update().filter(next_date__lte=today)
    for charge in due:
        while charge.next_date <= today:
            if not charge.variable_amount:
                Expense.objects.create(
                    store_id=charge.store_id,
                    category=charge.category,
                    amount=charge.amount,
                    method=charge.method,
                    note=charge.label[:255],
                    created_by_id=charge.created_by_id,
                )
                posted += 1
            charge.next_date = _next(charge.next_date, charge.frequency)
        charge.save(update_fields=["next_date", "updated_at"])
    return posted
