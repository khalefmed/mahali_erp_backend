"""ERP web back-office routes (lot 1): books, supplier payments, report details,
customer statement, team activity, seller performance. One small shop day."""

import pytest
from django.utils import timezone

from apps.stores.roles import Role
from conftest import add_member, api, client_for

pytestmark = pytest.mark.django_db

IMEIS = ["356789100000011", "356789100000029"]


@pytest.fixture
def day(store, owner_client, phone_variant, earbuds_variant):
    supplier = owner_client.post(api(store, "suppliers"), {"name": "Dubaï Mobiles"}).data
    phone = owner_client.post(
        api(store, "products"), {"variant_id": phone_variant.id, "sale_price": 15900}
    ).data
    earbuds = owner_client.post(
        api(store, "products"), {"variant_id": earbuds_variant.id, "sale_price": 250}
    ).data
    receipt = owner_client.post(
        api(store, "receipts"),
        {
            "supplier": supplier["id"],
            "supplier_reference": "FAC-889",
            "lines": [
                {
                    "store_product": phone["id"],
                    "quantity": "2",
                    "unit_cost": 13000,
                    "serials": IMEIS,
                },
                {"store_product": earbuds["id"], "quantity": "10", "unit_cost": 120},
            ],
        },
    )
    assert receipt.status_code == 201, receipt.data
    owner_client.post(api(store, "cash-sessions"), {"opening_float": 2000})
    customer = owner_client.post(api(store, "customers"), {"name": "Sidi Mohamed"}).data
    sale = owner_client.post(
        api(store, "sales"),
        {
            "lines": [{"store_product": phone["id"], "quantity": "1", "serial": IMEIS[0]}],
            "payments": [{"method": "cash", "amount": 5900}],
            "customer": customer["id"],
        },
    ).data
    credit = owner_client.get(api(store, "credits")).data["results"][0]
    owner_client.post(
        api(store, f"credits/{credit['id']}/repay"), {"amount": 4000, "method": "masrvi"}
    )
    owner_client.post(
        api(store, "expenses"), {"category": "transport", "amount": 300, "method": "cash"}
    )
    return {"supplier": supplier, "customer": customer, "sale": sale, "credit": credit}


def test_supplier_payment_lowers_payables_and_the_till(store, owner_client, day):
    payment = owner_client.post(
        api(store, "supplier-payments"),
        {"supplier": day["supplier"]["id"], "amount": 10000, "method": "cash"},
    )
    assert payment.status_code == 201, payment.data
    assert payment.data["supplier_name"] == "Dubaï Mobiles"
    listing = owner_client.get(api(store, "supplier-payments")).data
    assert listing["count"] == 1
    assert listing["results"][0]["amount"] == 10000

    details = owner_client.get(api(store, "reports/details")).data
    assert details["supplier_payables"] == 2 * 13000 + 10 * 120 - 10000
    assert details["sales_by_category"][0]["category"] == "smartphones"
    assert details["sales_by_category"][0]["revenue"] == 15900
    assert details["dormant_products"] == 1  # earbuds, never sold

    session = owner_client.get(api(store, "cash-sessions/current")).data
    # float + cash sale - cash expense - cash supplier payment
    assert session["totals"]["expected_cash"] == 2000 + 5900 - 300 - 10000


def test_journal_entries_are_balanced(store, owner_client, day):
    owner_client.post(
        api(store, "supplier-payments"),
        {"supplier": day["supplier"]["id"], "amount": 5000, "method": "bank_transfer"},
    )
    journal = owner_client.get(
        api(store, "accounting/journal"), {"date": timezone.localdate().isoformat()}
    ).data
    journals = [entry["journal"] for entry in journal["entries"]]
    assert {"sales", "purchases", "cash", "bank"} <= set(journals)
    for entry in journal["entries"]:
        assert len(entry["lines"]) >= 2
        assert sum(line["debit"] for line in entry["lines"]) == sum(
            line["credit"] for line in entry["lines"]
        ), entry
    sale = next(e for e in journal["entries"] if e["journal"] == "sales")
    assert sale["reference"] == day["sale"]["number"]
    assert sale["lines"][0] == {
        "account": "411",
        "account_name": "Clients",
        "label": "Sidi Mohamed",
        "debit": 15900,
        "credit": 0,
    }


def test_closing_checklist(store, owner_client, day):
    closing = owner_client.get(api(store, "accounting/closing")).data
    checks = {check["code"]: check for check in closing["checks"]}
    assert checks["tills_closed"]["done"] is False  # the till is still open
    assert checks["expense_receipts"]["count"] == 1
    assert checks["purchases_matched"]["done"] is True
    assert closing["declaration"]["status"] == "to_file"
    assert closing["declaration"]["due_date"].endswith("-15")


def test_customer_statement(store, owner_client, day):
    statement = owner_client.get(api(store, f"customers/{day['customer']['id']}/statement")).data
    assert statement["opening_balance"] == 0
    kinds = [(m["kind"], m["amount"]) for m in statement["movements"]]
    assert kinds == [("invoice", 10000), ("payment", 4000)]
    assert statement["movements"][0]["reference"] == day["sale"]["number"]
    assert statement["year_invoiced"] == 10000
    assert statement["year_paid"] == 4000
    assert statement["usual_payment"] == "Masrvi"
    assert statement["average_days_to_pay"] is None  # not settled yet
    assert owner_client.get(api(store, "customer-advances")).data == {"results": []}


def test_team_activity_and_seller_performance(store, owner, owner_client, day):
    seller = add_member(store, Role.SELLER, "vendeur@example.com")
    activity = owner_client.get(api(store, "member-activity")).data["results"]
    me = next(row for row in activity if row["user"] == str(owner.id))
    assert me["till_open"] is True
    assert len(activity) == 2

    mine = owner_client.get(api(store, "seller-performance/me")).data
    assert mine["revenue"] == 5900  # collected, the rest is on credit
    assert mine["sales_count"] == 1
    assert mine["leaderboard"][0]["is_me"] is True
    assert mine["commission_rate"] == 0

    seller_view = client_for(seller).get(api(store, "seller-performance/me")).data
    assert seller_view["revenue"] == 0
    # A seller can't see the team's presence.
    assert client_for(seller).get(api(store, "member-activity")).status_code == 403
