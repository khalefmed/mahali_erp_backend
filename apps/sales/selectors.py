"""Complex reads of the sales app. Run under the store's RLS context."""

from collections import Counter
from datetime import date

from django.db.models import Max, Sum
from django.db.models.functions import Coalesce

from .models import Credit, Customer, Payment, PaymentMethod


def _total(queryset, field="amount") -> int:
    return int(queryset.aggregate(t=Coalesce(Sum(field), 0))["t"])


def customer_statement(customer: Customer, date_from: date, date_to: date) -> dict:
    """Account statement: invoices on account (credits) and their repayments."""
    credits = Credit.objects.filter(customer=customer).select_related("sale")
    repayments = Payment.objects.filter(
        kind=Payment.Kind.CREDIT_REPAYMENT, credit__customer=customer
    ).select_related("credit")

    opening = _total(credits.filter(created_at__date__lt=date_from)) - _total(
        repayments.filter(created_at__date__lt=date_from)
    )
    in_period = {"created_at__date__gte": date_from, "created_at__date__lte": date_to}
    movements = [
        {
            "date": credit.created_at.date(),
            "reference": credit.sale.number,
            "label": credit.number,
            "kind": "invoice",
            "amount": credit.amount,
            "credit": credit.id,
        }
        for credit in credits.filter(**in_period)
    ] + [
        {
            "date": payment.created_at.date(),
            "reference": payment.reference or payment.credit.number,
            "label": PaymentMethod(payment.method).label,
            "kind": "payment",
            "amount": payment.amount,
            "credit": payment.credit_id,
        }
        for payment in repayments.filter(**in_period)
    ]
    movements.sort(key=lambda m: (m["date"], m["kind"] != "invoice"))

    year = {"created_at__date__gte": date(date_to.year, 1, 1), "created_at__date__lte": date_to}
    settled = credits.filter(status=Credit.Status.SETTLED).annotate(
        paid_at=Max("repayments__created_at")
    )
    delays = [(c.paid_at - c.created_at).days for c in settled if c.paid_at]
    methods = Counter(repayments.values_list("method", flat=True))
    usual = methods.most_common(1)[0][0] if methods else None
    return {
        "from": date_from,
        "to": date_to,
        "opening_balance": opening,
        "movements": movements,
        "year_invoiced": _total(credits.filter(**year)),
        "year_paid": _total(repayments.filter(**year)),
        "average_days_to_pay": round(sum(delays) / len(delays)) if delays else None,
        "usual_payment": PaymentMethod(usual).label if usual else "",
        "terms": None,
    }
