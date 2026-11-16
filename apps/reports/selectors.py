from datetime import date, timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

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


DORMANT_DAYS = 60


def details(date_from: date, date_to: date) -> dict:
    """What the summary doesn't give: sales by category, dormant stock, supplier debts."""
    from apps.finance.selectors import supplier_payables

    lines = SaleLine.objects.filter(
        sale__created_at__date__gte=date_from, sale__created_at__date__lte=date_to
    )
    category = "store_product__variant__product__category"
    by_category = [
        {
            "category": row[f"{category}__slug"],
            "name": row[f"{category}__name"] or "",
            "revenue": int(row["revenue"]),
        }
        for row in lines.values(f"{category}__slug", f"{category}__name")
        .annotate(revenue=Sum(F("line_total") - F("vat_amount")))
        .order_by("-revenue")
    ]
    since = timezone.now() - timedelta(days=DORMANT_DAYS)
    sold_lately = SaleLine.objects.filter(sale__created_at__gte=since).values("store_product")
    dormant = (
        StoreProduct.objects.filter(quantity__gt=0, is_active=True)
        .exclude(id__in=sold_lately)
        .count()
    )
    return {
        "sales_by_category": by_category,
        "dormant_products": dormant,
        "dormant_days": DORMANT_DAYS,
        "supplier_payables": supplier_payables(),
    }


ONLINE_MINUTES = 5


def member_activity(store) -> list[dict]:
    """Presence of each active member: last merchant session seen, open till."""
    from apps.accounts.models import UserSession
    from apps.sales.models import CashSession

    memberships = store.memberships.filter(is_active=True).select_related("user")
    users = [membership.user for membership in memberships]
    seen = {
        row["user"]: row["last"]
        for row in UserSession.objects.filter(
            user__in=users, realm=UserSession.Realm.MERCHANT, revoked_at__isnull=True
        )
        .values("user")
        .annotate(last=Max("last_seen_at"))
    }
    tills = set(
        CashSession.objects.filter(status=CashSession.Status.OPEN).values_list(
            "opened_by", flat=True
        )
    )
    online_since = timezone.now() - timedelta(minutes=ONLINE_MINUTES)
    return [
        {
            "user": user.id,
            "phone": user.phone or None,
            "last_seen_at": seen.get(user.id),
            "online": bool(seen.get(user.id) and seen[user.id] >= online_since),
            "till_open": user.id in tills,
        }
        for user in users
    ]


def seller_performance(store, user, month: date) -> dict:
    """My month in this store: collected sales and the store's sellers ranking.
    No commission or target is configured yet: rate 0, target and bonus null."""
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    sales = Sale.objects.filter(created_at__date__gte=start, created_at__date__lt=end)
    rows = (
        sales.values("seller", "seller__full_name")
        .annotate(revenue=Coalesce(Sum("paid_total"), 0), count=Count("id"))
        .order_by("-revenue")
    )
    mine = sales.filter(seller=user)
    revenue = _sum(mine, "paid_total")
    return {
        "month": start.strftime("%Y-%m"),
        "revenue": revenue,
        "sales_count": mine.count(),
        "commission_rate": 0,
        "commission": 0,
        "target": None,
        "bonus": None,
        "stores_count": user.memberships.filter(is_active=True).count(),
        "leaderboard": [
            {
                "user": row["seller"],
                "name": row["seller__full_name"],
                "store_name": store.name,
                "revenue": int(row["revenue"]),
                "is_me": row["seller"] == user.id,
            }
            for row in rows
        ],
    }
