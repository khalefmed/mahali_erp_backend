"""The books, derived from what the shop already records (sales, payments, credit
notes, expenses, receipts, supplier payments). Nothing is typed twice: each document
posts one journal entry, SYSCOHADA accounts. Runs under the store's RLS context."""

from datetime import date, timedelta

from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.inventory.models import Receipt
from apps.sales.models import (
    CashSession,
    CreditNote,
    Expense,
    ExpenseCategory,
    Payment,
    PaymentMethod,
    Sale,
)

from .models import SupplierPayment

CUSTOMERS = ("411", "Clients")
SUPPLIERS = ("401", "Fournisseurs")
SALES = ("701", "Ventes de marchandises")
VAT_COLLECTED = ("4431", "TVA facturée sur ventes")
DISCOUNTS = ("709", "Rabais, remises et ristournes accordés")
PURCHASES = ("601", "Achats de marchandises")

METHOD_ACCOUNTS = {
    PaymentMethod.CASH: ("571", "Caisse"),
    PaymentMethod.BANKILY: ("551", "Monnaie électronique · Bankily"),
    PaymentMethod.MASRVI: ("551", "Monnaie électronique · Masrvi"),
    PaymentMethod.SEDAD: ("551", "Monnaie électronique · Sedad"),
    PaymentMethod.BANK_TRANSFER: ("521", "Banque"),
}
EXPENSE_ACCOUNTS = {
    ExpenseCategory.RENT: ("622", "Locations"),
    ExpenseCategory.SALARIES: ("661", "Rémunérations du personnel"),
    ExpenseCategory.TRANSPORT: ("618", "Transports"),
    ExpenseCategory.UTILITIES: ("605", "Eau, électricité, télécommunications"),
    ExpenseCategory.SUPPLIES: ("604", "Fournitures"),
    ExpenseCategory.OTHER: ("658", "Charges diverses"),
}


def _line(account, label, debit=0, credit=0):
    number, name = account
    return {
        "account": number,
        "account_name": name,
        "label": label,
        "debit": int(debit),
        "credit": int(credit),
    }


def _money_journal(method) -> str:
    return "cash" if method == PaymentMethod.CASH else "bank"


def _method_account(method):
    return METHOD_ACCOUNTS.get(method, ("521", "Banque"))


def journal(day: date) -> dict:
    """Entries of one day, in the order they happened."""
    on_day = {"created_at__date": day}
    entries: list[tuple] = []

    for sale in Sale.objects.filter(**on_day).select_related("customer"):
        if not sale.total:
            continue
        party = sale.customer.name if sale.customer_id else ""
        lines = [
            _line(CUSTOMERS, party, debit=sale.total),
            _line(SALES, "", credit=sale.total - sale.vat_total),
        ]
        if sale.vat_total:
            lines.append(_line(VAT_COLLECTED, "", credit=sale.vat_total))
        entries.append((sale.created_at, f"sale-{sale.id}", "sales", sale.number, lines))

    for note in CreditNote.objects.filter(**on_day).select_related("sale__customer"):
        if not note.total:
            continue
        customer = note.sale.customer
        party = customer.name if customer else ""
        lines = [_line(DISCOUNTS, "", debit=note.total), _line(CUSTOMERS, party, credit=note.total)]
        entries.append((note.created_at, f"creditnote-{note.id}", "sales", note.number, lines))

    payments = Payment.objects.filter(**on_day).select_related(
        "sale__customer", "credit__customer", "credit_note"
    )
    for payment in payments:
        if not payment.amount:
            continue
        customer = (payment.credit and payment.credit.customer) or (
            payment.sale and payment.sale.customer
        )
        party = customer.name if customer else ""
        reference = (
            payment.reference
            or (payment.credit and payment.credit.number)
            or (payment.credit_note and payment.credit_note.number)
            or (payment.sale and payment.sale.number)
            or ""
        )
        money = _method_account(payment.method)
        amount = abs(payment.amount)
        if payment.amount > 0:
            lines = [_line(money, party, debit=amount), _line(CUSTOMERS, party, credit=amount)]
        else:  # refund
            lines = [_line(CUSTOMERS, party, debit=amount), _line(money, party, credit=amount)]
        entries.append(
            (
                payment.created_at,
                f"payment-{payment.id}",
                _money_journal(payment.method),
                reference,
                lines,
            )
        )

    for expense in Expense.objects.filter(**on_day):
        account = EXPENSE_ACCOUNTS.get(expense.category, EXPENSE_ACCOUNTS[ExpenseCategory.OTHER])
        lines = [
            _line(account, expense.note, debit=expense.amount),
            _line(_method_account(expense.method), expense.note, credit=expense.amount),
        ]
        entries.append(
            (expense.created_at, f"expense-{expense.id}", _money_journal(expense.method), "", lines)
        )

    for receipt in Receipt.objects.filter(**on_day).select_related("supplier"):
        if not receipt.total_cost:
            continue
        party = receipt.supplier.name if receipt.supplier_id else ""
        lines = [
            _line(PURCHASES, party, debit=receipt.total_cost),
            _line(SUPPLIERS, party, credit=receipt.total_cost),
        ]
        reference = receipt.supplier_reference or receipt.number
        entries.append((receipt.created_at, f"receipt-{receipt.id}", "purchases", reference, lines))

    for paid in SupplierPayment.objects.filter(**on_day).select_related("supplier"):
        party = paid.supplier.name
        lines = [
            _line(SUPPLIERS, party, debit=paid.amount),
            _line(_method_account(paid.method), party, credit=paid.amount),
        ]
        entries.append(
            (
                paid.created_at,
                f"supplierpayment-{paid.id}",
                _money_journal(paid.method),
                paid.reference,
                lines,
            )
        )

    entries.sort(key=lambda entry: entry[0])
    return {
        "date": day,
        "entries": [
            {"id": entry_id, "journal": code, "reference": reference, "lines": lines}
            for _, entry_id, code, reference, lines in entries
        ],
    }


def _vat_due_date(date_to: date) -> date:
    """VAT of a month is declared by the 15th of the next month."""
    first_next = (date_to.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first_next.replace(day=15)


def closing(date_from: date, date_to: date) -> dict:
    """What the period's closing needs. Purchase VAT and bank statements are not
    recorded yet: deductible VAT is 0 and the bank is never marked reconciled."""
    period = {"created_at__date__gte": date_from, "created_at__date__lte": date_to}
    receipts = Receipt.objects.filter(**period)
    open_tills = CashSession.objects.filter(
        status=CashSession.Status.OPEN, created_at__date__lte=date_to
    )
    gaps = (
        CashSession.objects.filter(closed_at__date__gte=date_from, closed_at__date__lte=date_to)
        .exclude(difference=0)
        .exclude(difference__isnull=True)
        .order_by("closed_at")
    )
    first_gap = gaps.first()
    expenses = Expense.objects.filter(**period).count()  # receipts (photos) aren't stored yet
    return {
        "vat_deductible": 0,
        "declaration": {"status": "to_file", "due_date": _vat_due_date(date_to)},
        "checks": [
            {"code": "sales_posted", "done": True},
            {
                "code": "purchases_matched",
                "done": not receipts.filter(supplier__isnull=True).exists(),
            },
            {"code": "bank_reconciled", "done": False, "date": None, "account": None},
            {"code": "tills_closed", "done": not open_tills.exists()},
            {"code": "expense_receipts", "done": expenses == 0, "count": expenses},
            {
                "code": "cash_gaps",
                "done": first_gap is None,
                "date": first_gap.closed_at.date() if first_gap else None,
            },
        ],
    }


def supplier_payables() -> int:
    """What the shop owes its suppliers: received goods minus supplier payments."""
    received = Receipt.objects.filter(supplier__isnull=False).aggregate(
        t=Coalesce(Sum("total_cost"), 0)
    )["t"]
    paid = SupplierPayment.objects.aggregate(t=Coalesce(Sum("amount"), 0))["t"]
    return int(received) - int(paid)
