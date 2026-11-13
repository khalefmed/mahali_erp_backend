from datetime import date

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDate

from apps.inventory.models import StoreProduct
from apps.sales.models import Credit, Expense, Payment, PaymentMethod, Sale, SaleLine


def _sum(queryset, field) -> int:
    return int(queryset.aggregate(t=Coalesce(Sum(field), 0))["t"])


def summary(date_from: date, date_to: date) -> dict:
    """Store activity between two dates (inclusive). Runs under the store's RLS context."""
    sales = Sale.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    payments = Payment.objects.filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to
    )
    expenses = Expense.objects.filter(
        created_at__date__gte=date_from, created_at__date__lte=date_to
    )
    revenue = _sum(sales, "total")
    refunds = _sum(sales, "refunded_total")
    cost = _sum(sales, "cost_total")

    by_method = {m: 0 for m in PaymentMethod.values}
    for row in payments.values("method").annotate(total=Sum("amount")):
        by_method[row["method"]] = int(row["total"])

    daily = [
        {"date": row["day"], "sales_count": row["count"], "revenue": int(row["revenue"])}
        for row in sales.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"), revenue=Sum("total"))
        .order_by("day")
    ]
    top_products = [
        {
            "store_product": row["store_product"],
            "name": row["description"],
            "quantity": row["quantity"],
            "revenue": int(row["revenue"]),
        }
        for row in SaleLine.objects.filter(sale__in=sales)
        .values("store_product", "description")
        .annotate(quantity=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-revenue")[:10]
    ]
    stock_value = StoreProduct.objects.aggregate(
        v=Coalesce(
            Sum(ExpressionWrapper(F("avg_cost") * F("quantity"), output_field=DecimalField())),
            Value(0),
            output_field=DecimalField(),
        )
    )["v"]
    expenses_total = _sum(expenses, "amount")
    return {
        "date_from": date_from,
        "date_to": date_to,
        "sales_count": sales.count(),
        "revenue": revenue,
        "discounts": _sum(sales, "discount_total"),
        "refunds": refunds,
        "net_revenue": revenue - refunds,
        "cost_of_goods": cost,
        "gross_margin": revenue - refunds - cost,
        "vat_collected": _sum(sales, "vat_total"),
        "expenses": expenses_total,
        "credit_issued": _sum(sales, "credit_total"),
        "credit_collected": _sum(payments.filter(kind=Payment.Kind.CREDIT_REPAYMENT), "amount"),
        "credit_outstanding": _sum(Credit.objects.filter(status=Credit.Status.OPEN), "balance"),
        "credit_overdue": _sum(
            Credit.objects.filter(status=Credit.Status.OPEN, due_date__lt=date_to), "balance"
        ),
        "payments_by_method": by_method,
        "stock_value": int(stock_value),
        "low_stock_count": StoreProduct.objects.filter(
            is_active=True, quantity__lte=F("reorder_level")
        ).count(),
        "out_of_stock_count": StoreProduct.objects.filter(is_active=True, quantity=0).count(),
        "daily": daily,
        "top_products": top_products,
        "by_seller": [
            {
                "seller": row["seller__full_name"],
                "sales_count": row["count"],
                "revenue": int(row["revenue"]),
            }
            for row in sales.values("seller__full_name")
            .annotate(count=Count("id"), revenue=Sum("total"))
            .order_by("-revenue")
        ],
    }
