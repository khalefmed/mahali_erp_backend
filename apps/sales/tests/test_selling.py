"""End-to-end till flow for a phone shop: receive IMEIs, sell, credit, return, close Z."""

import pytest
from django.utils import timezone

from apps.stores.roles import Role
from conftest import add_member, api, client_for

pytestmark = pytest.mark.django_db
IMEIS = ["356789100000011", "356789100000029", "356789100000037"]


@pytest.fixture
def shop(store, owner_client, phone_variant, earbuds_variant):
    phone = owner_client.post(
        api(store, "products"), {"variant_id": phone_variant.id, "sale_price": 15900}
    ).data
    earbuds = owner_client.post(
        api(store, "products"), {"variant_id": earbuds_variant.id, "sale_price": 250}
    ).data
    receipt = owner_client.post(
        api(store, "receipts"),
        {
            "supplier_reference": "FAC-889",
            "lines": [
                {
                    "store_product": phone["id"],
                    "quantity": "3",
                    "unit_cost": 13000,
                    "serials": IMEIS,
                },
                {"store_product": earbuds["id"], "quantity": "10", "unit_cost": 120},
            ],
        },
    )
    assert receipt.status_code == 201, receipt.data
    owner_client.post(api(store, "cash-sessions"), {"opening_float": 2000})
    return {"phone": phone["id"], "earbuds": earbuds["id"], "receipt": receipt.data}


def sell(client, store, lines, payments, **extra):
    return client.post(api(store, "sales"), {"lines": lines, "payments": payments, **extra})


def test_receipt_numbers_stock_and_average_cost(store, owner_client, shop):
    yymm = timezone.localdate().strftime("%y%m")
    assert shop["receipt"]["number"] == f"BR-{yymm}-0001"
    assert shop["receipt"]["total_cost"] == 3 * 13000 + 10 * 120
    phone = owner_client.get(api(store, f"products/{shop['phone']}")).data
    assert phone["quantity"] == "3.000"
    assert phone["avg_cost"] == 13000
    assert phone["warranty_months"] == 12  # category default


def test_sell_a_phone_by_imei(store, owner_client, shop):
    sale = sell(
        owner_client,
        store,
        [
            {"store_product": shop["phone"], "quantity": "1", "serial": IMEIS[0]},
            {"store_product": shop["earbuds"], "quantity": "2", "discount": 50},
        ],
        [{"method": "bankily", "amount": 16350, "reference": "BK-77812"}],
    )
    assert sale.status_code == 201, sale.data
    assert sale.data["number"] == f"V-{timezone.localdate():%y%m}-0001"
    assert sale.data["total"] == 15900 + 500 - 50
    assert sale.data["lines"][0]["serial"] == IMEIS[0]
    assert sale.data["lines"][0]["warranty_months"] == 12

    lookup = owner_client.get(api(store, f"serials?serial={IMEIS[0]}")).data["results"][0]
    assert lookup["status"] == "sold"
    again = sell(
        owner_client,
        store,
        [{"store_product": shop["phone"], "quantity": "1", "serial": IMEIS[0]}],
        [{"method": "cash", "amount": 15900}],
    )
    assert again.status_code == 409
    assert again.data["code"] == "serial_not_in_stock"


def test_tracked_product_requires_imei(store, owner_client, shop):
    response = sell(
        owner_client,
        store,
        [{"store_product": shop["phone"], "quantity": "1"}],
        [{"method": "cash", "amount": 15900}],
    )
    assert response.data["code"] == "serial_required"


def test_stock_can_never_go_negative(store, owner_client, shop):
    response = sell(
        owner_client,
        store,
        [{"store_product": shop["earbuds"], "quantity": "11"}],
        [{"method": "cash", "amount": 2750}],
    )
    assert response.status_code == 409
    assert response.data["code"] == "insufficient_stock"
    assert response.data["available"] == "10.000"


def test_sale_needs_an_open_till(store, shop):
    seller = client_for(add_member(store, Role.SELLER, "seller@example.com"))
    response = sell(
        seller,
        store,
        [{"store_product": shop["earbuds"], "quantity": "1"}],
        [{"method": "cash", "amount": 250}],
    )
    assert response.data["code"] == "no_open_cash_session"


def test_big_discount_needs_a_manager(store, shop):
    cashier = client_for(add_member(store, Role.CASHIER, "cashier@example.com"))
    cashier.post(api(store, "cash-sessions"), {"opening_float": 0})
    response = sell(
        cashier,
        store,
        [{"store_product": shop["earbuds"], "quantity": "1", "discount": 100}],
        [{"method": "cash", "amount": 150}],
    )
    assert response.status_code == 403
    assert response.data["code"] == "discount_requires_approval"


def test_credit_sale_repayment_and_credit_note(store, owner_client, shop):
    customer = owner_client.post(
        api(store, "customers"), {"name": "Sidi Mohamed", "phone": "+22236000000"}
    ).data
    no_customer = sell(
        owner_client,
        store,
        [{"store_product": shop["phone"], "quantity": "1", "serial": IMEIS[1]}],
        [{"method": "cash", "amount": 5900}],
    )
    assert no_customer.data["code"] == "customer_required_for_credit"

    sale = sell(
        owner_client,
        store,
        [{"store_product": shop["phone"], "quantity": "1", "serial": IMEIS[1]}],
        [{"method": "cash", "amount": 5900}],
        customer=customer["id"],
    ).data
    assert sale["credit_total"] == 10000
    assert sale["credit_number"] == "CR-0001"
    credit = owner_client.get(api(store, "credits")).data["results"][0]
    repaid = owner_client.post(
        api(store, f"credits/{credit['id']}/repay"), {"amount": 4000, "method": "masrvi"}
    )
    assert repaid.status_code == 201
    assert (
        owner_client.get(api(store, f"customers/{customer['id']}")).data["credit_balance"] == 6000
    )

    note = owner_client.post(
        api(store, "credit-notes"),
        {
            "sale": sale["id"],
            "lines": [{"sale_line": sale["lines"][0]["id"], "quantity": "1"}],
            "refund_method": "cash",
            "reason": "Écran défectueux",
        },
    )
    assert note.status_code == 201, note.data
    assert note.data["total"] == 15900
    phone = owner_client.get(api(store, f"products/{shop['phone']}")).data
    assert phone["quantity"] == "3.000"
    unit = owner_client.get(api(store, f"serials?serial={IMEIS[1]}")).data["results"][0]
    assert unit["status"] == "in_stock"
    assert owner_client.get(api(store, f"sales/{sale['id']}")).data["status"] == "refunded"


def test_close_till_z_report(store, owner_client, shop):
    sell(
        owner_client,
        store,
        [{"store_product": shop["earbuds"], "quantity": "2"}],
        [{"method": "cash", "amount": 500}],
    )
    owner_client.post(
        api(store, "expenses"), {"category": "transport", "amount": 100, "method": "cash"}
    )
    session = owner_client.get(api(store, "cash-sessions/current")).data
    assert session["totals"]["expected_cash"] == 2000 + 500 - 100
    closed = owner_client.post(
        api(store, f"cash-sessions/{session['id']}/close"), {"counted_cash": 2350}
    )
    assert closed.data["number"] == "Z-0001"
    assert closed.data["difference"] == -50
    assert owner_client.get(api(store, "cash-sessions/current")).data is None


def test_report_summary(store, owner_client, shop):
    sell(
        owner_client,
        store,
        [{"store_product": shop["phone"], "quantity": "1", "serial": IMEIS[2]}],
        [{"method": "cash", "amount": 15900}],
    )
    report = owner_client.get(api(store, "reports/summary")).data
    assert report["sales_count"] == 1
    assert report["revenue"] == 15900
    assert report["gross_margin"] == 2900
    assert report["payments_by_method"]["cash"] == 15900
    assert report["top_products"][0]["revenue"] == 15900


def test_cashier_cannot_receive_stock_or_see_costs(store, shop):
    cashier = client_for(add_member(store, Role.CASHIER, "cashier@example.com"))
    response = cashier.post(api(store, "receipts"), {"lines": []})
    assert response.status_code == 403
    assert response.data["permission"] == "stock.receive"
    product = cashier.get(api(store, f"products/{shop['phone']}")).data
    assert product["avg_cost"] is None
    assert product["stock_value"] is None


def test_store_products_are_per_store(store, owner_client, shop, phone_variant):
    duplicate = owner_client.post(
        api(store, "products"), {"variant_id": phone_variant.id, "sale_price": 1}
    )
    assert duplicate.data["code"] == "product_already_added"


def test_impersonation_is_read_only(store, staff_client, shop):
    token = staff_client.post(
        f"/api/v1/console/stores/{store.id}/impersonate", {"reason": "Ticket #42"}
    ).data["access"]
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get(api(store, "products")).status_code == 200
    blocked = client.post(api(store, "customers"), {"name": "X"})
    assert blocked.status_code == 403
    assert blocked.data["code"] == "read_only_session"


def test_suspended_store_is_read_only(store, owner_client, staff_client, shop):
    staff_client.post(f"/api/v1/console/stores/{store.id}/suspend", {"message": "Fraude"})
    assert owner_client.get(api(store, "products")).status_code == 200
    blocked = owner_client.post(api(store, "customers"), {"name": "X"})
    assert blocked.data["code"] == "store_read_only"
