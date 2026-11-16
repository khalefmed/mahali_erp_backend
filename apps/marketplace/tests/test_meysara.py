"""Marketplace v2: Meysara (pay in 4), listing facets, shoppers' password reset link."""

import re
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.console.models import PlatformSettings
from apps.marketplace import meysara
from apps.marketplace.models import MeysaraInstalment, MeysaraPlan, Order
from conftest import api, make_user

from .helpers import PUBLIC, order_payload, store_client, verify_identity

pytestmark = pytest.mark.django_db
CONSOLE = "/api/v1/console/marketplace/orders"


@pytest.fixture
def rules(margin):
    """Small amounts so the earbuds (275 MRU each with the margin) can use Meysara."""
    settings = PlatformSettings.load()
    settings.meysara_min_total = 1000
    settings.meysara_max_financed = 60000
    settings.save()
    return settings


def ready(user):
    """Three delivered orders and a verified identity: Meysara is open."""
    past_orders(user, 3)
    verify_identity(user)


def past_orders(user, count, status="delivered"):
    for _ in range(count):
        Order.objects.create(
            number=f"MP-T-{uuid4().hex[:10]}",
            customer=user,
            status=status,
            margin_percent=10,
            subtotal=1000,
            total=1000,
            delivery_name="Aicha",
            delivery_phone="+22236000000",
            delivery_city="Nouakchott",
            delivery_address="Ksar",
        )


def offer(client, total):
    return client.get(f"{PUBLIC}/meysara/offer", {"total": total})


def meysara_order(client, variant, quantity="5", percent=50):
    payload = {
        **order_payload((variant, quantity)),
        "payment_method": "meysara",
        "meysara_percent": percent,
    }
    return client.post(f"{PUBLIC}/orders", payload, format="json")


def deliver(order_id, store, staff_client):
    merchant = store_client(store)
    part = merchant.get(api(store, "marketplace-orders")).data["results"][0]
    accepted = merchant.post(
        api(store, f"marketplace-orders/{part['id']}/accept"), {}, format="json"
    )
    assert accepted.status_code == 200, accepted.data
    merchant.post(api(store, f"marketplace-orders/{part['id']}/ready"))
    delivered = staff_client.post(f"{CONSOLE}/{order_id}/deliver")
    assert delivered.status_code == 200, delivered.data
    return delivered.data


# ---------------------------------------------------------------- rules


def test_split_puts_the_remainder_on_the_first_instalments():
    assert meysara.split(21398) == [5350, 5350, 5349, 5349]
    assert meysara.split(10699) == [2675, 2675, 2675, 2674]
    assert meysara.financed(17490, 25) == 4372


def test_offer_opens_after_three_delivered_orders(rules, shopper):
    user, client = shopper
    closed = offer(client, 5000)
    assert closed.status_code == 200, closed.data
    assert closed.data | {"min_total": None} == {
        "eligible": False,
        "reason": "meysara_history_insufficient",
        "max_percent": None,
        "choices": [],
        "paid_orders": 0,
        "required_orders": 3,
        "min_total": None,
        "max_financed": 60000,
        "identity_verified": False,
        "regulatory_max_financed": 60000,
    }
    past_orders(user, 2)
    past_orders(user, 1, status="cancelled")  # cancelled orders don't count
    assert offer(client, 5000).data["paid_orders"] == 2

    past_orders(user, 1)
    assert offer(client, 5000).data["reason"] == "meysara_identity_unverified"

    verify_identity(user)
    opened = offer(client, 5000).data
    assert (opened["eligible"], opened["max_percent"], opened["choices"]) == (True, 50, [25, 50])


def test_offer_reasons_in_the_spec_order(rules, shopper):
    user, client = shopper
    ready(user)
    assert offer(client, 999).data["reason"] == "meysara_amount_too_low"
    rules.meysara_max_financed = 1000
    rules.save()
    assert offer(client, 5000).data["reason"] == "meysara_limit_exceeded"  # 25 % = 1 250
    rules.meysara_enabled = False
    rules.save()
    assert offer(client, 5000).data["reason"] == "meysara_disabled"


def test_offer_needs_a_shopper_token(rules, owner_client):
    assert APIClient().get(f"{PUBLIC}/meysara/offer", {"total": 5000}).status_code == 401
    assert offer(owner_client, 5000).status_code in (401, 403)


# ---------------------------------------------------------------- checkout


def test_meysara_order_reserves_a_plan(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    response = meysara_order(client, earbuds_variant)  # 5 x 275 = 1 375
    assert response.status_code == 201, response.data
    assert response.data["payment_method"] == "meysara"
    plan = response.data["meysara"]
    assert (plan["percent"], plan["financed"], plan["on_delivery"], plan["status"]) == (
        50,
        687,
        688,
        "reserved",
    )
    assert [(i["amount"], i["due_date"], i["status"]) for i in plan["instalments"]] == [
        (172, None, "waiting_delivery"),
        (172, None, "waiting_delivery"),
        (172, None, "waiting_delivery"),
        (171, None, "waiting_delivery"),
    ]

    # One plan at a time.
    again = meysara_order(client, earbuds_variant, quantity="4")
    assert (again.status_code, again.data["code"]) == (409, "meysara_not_allowed")
    assert again.data["reason"] == "meysara_plan_in_progress"
    assert Order.objects.filter(customer=user).count() == 4  # 3 past + 1, nothing half-made


def test_meysara_needs_an_allowed_share(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    payload = {**order_payload((earbuds_variant, "5")), "payment_method": "meysara"}
    missing = client.post(f"{PUBLIC}/orders", payload, format="json")
    assert missing.data["code"] == "meysara_percent_required"

    refused = meysara_order(client, earbuds_variant)  # no history yet
    assert refused.data["reason"] == "meysara_history_insufficient"
    ready(user)
    too_much = meysara_order(client, earbuds_variant, percent=100)  # ceiling is 50 %
    assert (too_much.data["code"], too_much.data["choices"]) == ("meysara_not_allowed", [25, 50])
    assert not MeysaraPlan.objects.exists()


def test_cash_orders_are_unchanged(two_shops, shopper, earbuds_variant):
    _, client = shopper
    response = client.post(f"{PUBLIC}/orders", order_payload((earbuds_variant, "2")), format="json")
    assert response.status_code == 201
    assert (response.data["payment_method"], response.data["meysara"]) == (
        "cash_on_delivery",
        None,
    )


def test_cancelling_the_order_cancels_the_plan(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    order = meysara_order(client, earbuds_variant).data
    cancelled = client.post(f"{PUBLIC}/orders/{order['id']}/cancel")
    assert cancelled.data["meysara"]["status"] == "cancelled"
    assert offer(client, 5000).data["eligible"] is True  # free to start another plan


# ---------------------------------------------------------------- after delivery


def test_delivery_starts_the_schedule_and_mahali_records_payments(
    rules, two_shops, shopper, staff_client, earbuds_variant
):
    user, client = shopper
    ready(user)
    order = meysara_order(client, earbuds_variant).data
    early = staff_client.post(
        f"{CONSOLE}/{order['id']}/meysara/pay", {"number": 1, "via": "bankily"}, format="json"
    )
    assert (early.status_code, early.data["code"]) == (409, "meysara_plan_not_active")

    delivered = deliver(order["id"], two_shops["dear"], staff_client)
    today = timezone.localdate()
    plan = delivered["meysara"]
    assert plan["status"] == "active"
    assert [i["due_date"] for i in plan["instalments"]] == [
        str(today + timedelta(days=14 * n)) for n in (1, 2, 3, 4)
    ]
    assert offer(client, 5000).data["reason"] == "meysara_plan_in_progress"

    for number, via in [(1, "bankily"), (2, "cash"), (3, "sedad")]:
        paid = staff_client.post(
            f"{CONSOLE}/{order['id']}/meysara/pay", {"number": number, "via": via}, format="json"
        )
        assert paid.status_code == 200, paid.data
    twice = staff_client.post(
        f"{CONSOLE}/{order['id']}/meysara/pay", {"number": 1, "via": "bankily"}, format="json"
    )
    assert twice.data["code"] == "instalment_already_paid"

    last = staff_client.post(
        f"{CONSOLE}/{order['id']}/meysara/pay", {"number": 4, "via": "masrvi"}, format="json"
    )
    assert last.data["meysara"]["status"] == "paid"
    mine = client.get(f"{PUBLIC}/orders/{order['id']}").data["meysara"]
    assert [i["status"] for i in mine["instalments"]] == ["paid"] * 4

    # Paid off on time: the next plan may cover the whole order.
    reopened = offer(client, 5000).data
    assert (reopened["max_percent"], reopened["choices"]) == (100, [50, 100])


def test_an_instalment_more_than_7_days_late_closes_meysara(
    rules, two_shops, shopper, staff_client, earbuds_variant
):
    user, client = shopper
    ready(user)
    order = meysara_order(client, earbuds_variant).data
    deliver(order["id"], two_shops["dear"], staff_client)
    MeysaraInstalment.objects.filter(number=1).update(
        due_date=timezone.localdate() - timedelta(days=8)
    )
    assert offer(client, 5000).data["reason"] == "meysara_overdue"
    statuses = [
        i["status"]
        for i in client.get(f"{PUBLIC}/orders/{order['id']}").data["meysara"]["instalments"]
    ]
    assert statuses == ["overdue", "upcoming", "upcoming", "upcoming"]


def test_late_payment_keeps_the_ceiling_at_50(
    rules, two_shops, shopper, staff_client, earbuds_variant
):
    user, client = shopper
    ready(user)
    order = meysara_order(client, earbuds_variant).data
    deliver(order["id"], two_shops["dear"], staff_client)
    for number in (1, 2, 3, 4):
        staff_client.post(
            f"{CONSOLE}/{order['id']}/meysara/pay", {"number": number, "via": "cash"}, format="json"
        )
    MeysaraInstalment.objects.filter(number=2).update(
        due_date=timezone.localdate() - timedelta(days=10)
    )
    assert offer(client, 5000).data["max_percent"] == 50


# ---------------------------------------------------------------- facets


def test_facets_list_brands_and_price_bounds(margin, two_shops, phone_variant, earbuds_variant):
    facets = APIClient().get(f"{PUBLIC}/products/facets", {"trade": "telephones"})
    assert facets.status_code == 200, facets.data
    assert facets.data["count"] == 2
    assert (facets.data["min_price"], facets.data["max_price"]) == (275, 15950)
    assert facets.data["brands"] == [{"slug": "samsung", "name": "Samsung", "count": 1}]

    # The brand filter narrows the prices, not the brand list.
    narrowed = APIClient().get(f"{PUBLIC}/products/facets", {"brand": "samsung"}).data
    assert (narrowed["count"], narrowed["min_price"]) == (1, 15950)
    assert [b["slug"] for b in narrowed["brands"]] == ["samsung"]


# ---------------------------------------------------------------- password reset


@override_settings(MARKETPLACE_URL="https://shop.example.mr")
def test_shoppers_reset_link_opens_the_marketplace(db, django_capture_on_commit_callbacks):
    make_user("client@example.com", language="ar")
    with django_capture_on_commit_callbacks(execute=True):
        response = APIClient().post(
            f"{PUBLIC}/auth/password/forgot", {"email": "client@example.com"}, format="json"
        )
    assert response.status_code == 202
    link = re.search(r"https://\S+", mail.outbox[-1].body).group(0)
    assert link.startswith("https://shop.example.mr/ar/mot-de-passe/nouveau?uid=")
    assert "token=" in link

    nobody = APIClient().post(
        f"{PUBLIC}/auth/password/forgot", {"email": "nobody@example.com"}, format="json"
    )
    assert nobody.status_code == 202  # no account enumeration
