"""Marketplace v1: shop window priced from the cheapest store + margin, customer orders
split per store, stores accept / reject / ready, Mahali delivers or cancels."""

import re

import pytest
from django.core import mail
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import UserSession
from apps.console.models import PlatformSettings
from apps.core.tenancy import marketplace_read, store_context
from apps.inventory.models import SerialUnit, StoreProduct
from apps.marketplace.models import StoreOrder
from apps.sales.models import Customer
from apps.stores.models import StoreStatus
from apps.stores.roles import Role
from conftest import add_member, api, client_for, make_store, make_user

from .helpers import PUBLIC, order_payload, quantity_of, stock, store_client

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------- isolation


def test_marketplace_read_widens_selects_only(two_shops):
    assert StoreProduct.objects.count() == 0  # no store, no flag: nothing
    with marketplace_read():
        assert StoreProduct.objects.count() == 3
        with pytest.raises(DatabaseError), transaction.atomic():
            Customer.objects.create(store=two_shops["cheap"], name="Intrus")


# ---------------------------------------------------------------- shop window


def test_shop_shows_cheapest_store_price_plus_margin_and_never_the_store(two_shops, phone_variant):
    response = APIClient().get(f"{PUBLIC}/products")
    assert response.status_code == 200
    phone = next(p for p in response.data["results"] if p["id"] == str(phone_variant.product_id))
    assert phone["price"] == 15950  # 14 500 + 10 %
    assert "store" not in str(response.data).lower()

    detail = APIClient().get(f"{PUBLIC}/products/{phone_variant.product_id}").data
    variant = detail["variants"][0]
    assert (variant["price"], variant["available"], variant["max_quantity"]) == (
        15950,
        True,
        "2.000",
    )


def test_shop_hides_out_of_stock_inactive_stores_and_used_items(margin, phone_variant):
    pending = make_store(make_user("p@example.com"), name="P", status=StoreStatus.PENDING_APPROVAL)
    stock(pending, phone_variant, 10000, 1, ["444444444444444"])
    active = make_store(make_user("a@example.com"), name="A")
    with store_context(active.id):
        StoreProduct.objects.create(store=active, variant=phone_variant, sale_price=9000)
    assert APIClient().get(f"{PUBLIC}/products").data["count"] == 0
    categories = APIClient().get(f"{PUBLIC}/categories").data
    assert all(c["product_count"] == 0 for c in categories)


def test_margin_is_set_in_the_console(two_shops, staff_client, phone_variant):
    response = staff_client.patch(
        "/api/v1/console/settings", {"marketplace_margin_percent": "5"}, format="json"
    )
    assert response.status_code == 200, response.data
    detail = APIClient().get(f"{PUBLIC}/products/{phone_variant.product_id}").data
    assert detail["variants"][0]["price"] == 15225


def test_filters_and_price_bounds(two_shops):
    assert APIClient().get(f"{PUBLIC}/products", {"max_price": 300}).data["count"] == 1
    assert APIClient().get(f"{PUBLIC}/products", {"search": "galaxy"}).data["count"] == 1
    assert APIClient().get(f"{PUBLIC}/products", {"trade": "pharmacie"}).data["count"] == 0


def test_quote_marks_unavailable_lines(two_shops, phone_variant, earbuds_variant):
    response = APIClient().post(
        f"{PUBLIC}/cart/quote",
        {
            "lines": [
                {"variant": str(phone_variant.id), "quantity": "5"},
                {"variant": str(earbuds_variant.id), "quantity": "2"},
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    phone, earbuds = response.data["lines"]
    assert (phone["available"], phone["max_quantity"]) == (False, "2.000")
    assert (earbuds["unit_price"], earbuds["line_total"]) == (275, 550)
    assert response.data["total"] == 550


# ---------------------------------------------------------------- customer accounts


def test_shopper_signs_up_even_when_merchant_signups_are_closed(
    db, django_capture_on_commit_callbacks
):
    settings = PlatformSettings.load()
    settings.signups_open = False
    settings.save()
    client = APIClient()
    payload = {"email": "new@example.com", "password": "Very-secret-pass-42", "full_name": "Sidi"}
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"{PUBLIC}/auth/register", payload).status_code == 202
    code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
    response = client.post(
        f"{PUBLIC}/auth/verify-email", {"email": "new@example.com", "code": code}
    )
    assert response.status_code == 200, response.data
    shopper = APIClient()
    shopper.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert shopper.get(f"{PUBLIC}/orders").status_code == 200
    assert shopper.get("/api/v1/me/stores").status_code == 401  # not a merchant token
    assert client.post("/api/v1/auth/register", payload).data["code"] == "signups_closed"


def test_merchant_token_cannot_order(owner_client):
    assert owner_client.get(f"{PUBLIC}/orders").status_code == 401


# ---------------------------------------------------------------- orders


def test_order_is_split_per_cheapest_store_and_each_store_sees_only_its_part(
    two_shops, shopper, phone_variant, earbuds_variant
):
    _, client = shopper
    response = client.post(
        f"{PUBLIC}/orders",
        order_payload((phone_variant, "1"), (earbuds_variant, "2")),
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["total"] == 15950 + 550
    assert response.data["status"] == "pending"

    cheap, dear = two_shops["cheap"], two_shops["dear"]
    cheap_view = store_client(cheap).get(api(cheap, "marketplace-orders")).data["results"]
    dear_view = store_client(dear).get(api(dear, "marketplace-orders")).data["results"]
    assert [line["description"] for line in cheap_view[0]["lines"]] == ["Samsung Galaxy A55 128 Go"]
    assert cheap_view[0]["total"] == 14500  # store price, not customer price
    assert dear_view[0]["total"] == 500
    assert "client@example.com" not in str(cheap_view)
    assert quantity_of(two_shops["cheap_phone"]) == 2  # nothing leaves stock before accepting


def test_full_flow_accept_ready_deliver(two_shops, shopper, staff_client, phone_variant):
    _, client = shopper
    order = client.post(f"{PUBLIC}/orders", order_payload((phone_variant, "1")), format="json").data
    cheap = two_shops["cheap"]
    merchant = store_client(cheap)
    part = merchant.get(api(cheap, "marketplace-orders")).data["results"][0]

    missing = merchant.post(
        api(cheap, f"marketplace-orders/{part['id']}/accept"), {}, format="json"
    )
    assert (missing.status_code, missing.data["code"]) == (400, "serials_required")

    accepted = merchant.post(
        api(cheap, f"marketplace-orders/{part['id']}/accept"),
        {"lines": [{"id": part["lines"][0]["id"], "serials": ["111111111111111"]}]},
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    assert quantity_of(two_shops["cheap_phone"]) == 1
    with store_context(cheap.id):
        assert SerialUnit.objects.get(serial="111111111111111").status == "sold"
    assert client.get(f"{PUBLIC}/orders/{order['id']}").data["status"] == "confirmed"

    too_early = staff_client.post(f"/api/v1/console/marketplace/orders/{order['id']}/deliver")
    assert too_early.data["code"] == "order_not_ready"
    merchant.post(api(cheap, f"marketplace-orders/{part['id']}/ready"))
    assert client.get(f"{PUBLIC}/orders/{order['id']}").data["status"] == "ready"

    console = staff_client.get(f"/api/v1/console/marketplace/orders/{order['id']}").data
    assert console["store_orders"][0]["store"]["name"] == "Cheap"
    delivered = staff_client.post(f"/api/v1/console/marketplace/orders/{order['id']}/deliver")
    assert delivered.status_code == 200, delivered.data
    assert delivered.data["status"] == "delivered"
    assert delivered.data["store_orders"][0]["status"] == "picked_up"


def test_a_rejection_cancels_the_order_and_restocks_the_other_stores(
    two_shops, shopper, phone_variant, earbuds_variant
):
    _, client = shopper
    order = client.post(
        f"{PUBLIC}/orders",
        order_payload((phone_variant, "1"), (earbuds_variant, "3")),
        format="json",
    ).data
    cheap, dear = two_shops["cheap"], two_shops["dear"]
    dear_part = store_client(dear).get(api(dear, "marketplace-orders")).data["results"][0]
    store_client(dear).post(
        api(dear, f"marketplace-orders/{dear_part['id']}/accept"), {}, format="json"
    )
    assert quantity_of(two_shops["dear_earbuds"]) == 7

    cheap_part = store_client(cheap).get(api(cheap, "marketplace-orders")).data["results"][0]
    rejected = store_client(cheap).post(
        api(cheap, f"marketplace-orders/{cheap_part['id']}/reject"), {"reason": "Rayé"}
    )
    assert rejected.status_code == 200, rejected.data

    assert client.get(f"{PUBLIC}/orders/{order['id']}").data["status"] == "cancelled"
    assert quantity_of(two_shops["dear_earbuds"]) == 10
    with store_context(dear.id):
        assert StoreOrder.objects.get().status == "cancelled"


def test_customer_cancels_after_acceptance_and_serials_come_back(two_shops, shopper, phone_variant):
    _, client = shopper
    order = client.post(f"{PUBLIC}/orders", order_payload((phone_variant, "2")), format="json").data
    cheap = two_shops["cheap"]
    part = store_client(cheap).get(api(cheap, "marketplace-orders")).data["results"][0]
    store_client(cheap).post(
        api(cheap, f"marketplace-orders/{part['id']}/accept"),
        {
            "lines": [
                {"id": part["lines"][0]["id"], "serials": ["111111111111111", "222222222222222"]}
            ]
        },
        format="json",
    )
    assert quantity_of(two_shops["cheap_phone"]) == 0

    cancelled = client.post(f"{PUBLIC}/orders/{order['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.data
    assert quantity_of(two_shops["cheap_phone"]) == 2
    with store_context(cheap.id):
        assert set(SerialUnit.objects.values_list("status", flat=True)) == {"in_stock"}
    again = client.post(f"{PUBLIC}/orders/{order['id']}/cancel")
    assert (again.status_code, again.data["code"]) == (409, "order_not_cancellable")


def test_no_single_store_can_serve_the_quantity(two_shops, shopper, phone_variant):
    _, client = shopper
    response = client.post(f"{PUBLIC}/orders", order_payload((phone_variant, "3")), format="json")
    assert response.status_code == 409
    assert (response.data["code"], response.data["available"]) == ("insufficient_stock", "2.000")


def test_phones_are_sold_by_the_unit(two_shops, shopper, phone_variant):
    _, client = shopper
    response = client.post(f"{PUBLIC}/orders", order_payload((phone_variant, "1.5")), format="json")
    assert response.data["code"] == "whole_quantity_required"


def test_a_shopper_only_sees_their_orders(two_shops, shopper, earbuds_variant):
    _, client = shopper
    order = client.post(
        f"{PUBLIC}/orders", order_payload((earbuds_variant, "1")), format="json"
    ).data
    other = client_for(make_user("other@example.com"), UserSession.Realm.CUSTOMER)
    assert other.get(f"{PUBLIC}/orders/{order['id']}").status_code == 404


def test_cashiers_do_not_handle_marketplace_orders(two_shops):
    dear = two_shops["dear"]
    cashier = client_for(add_member(dear, Role.CASHIER, "caisse@example.com"))
    response = cashier.get(api(dear, "marketplace-orders"))
    assert (response.status_code, response.data["code"]) == (403, "permission_denied")
