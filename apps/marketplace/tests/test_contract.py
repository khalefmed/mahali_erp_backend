"""Meysara's electronic contract: shown, accepted (ticked box), kept, readable afterwards."""

import pytest
from django.core import mail

from apps.accounts.models import UserSession
from apps.marketplace import contract
from apps.marketplace.models import MeysaraContract, MeysaraPlan
from conftest import client_for, make_user

from .helpers import PUBLIC, order_payload
from .test_meysara import accepted_contract, meysara_order, ready

pytestmark = pytest.mark.django_db


def show(client, variant, quantity="5", percent=50, language="fr"):
    return client.post(
        f"{PUBLIC}/meysara/contract",
        {
            "lines": [{"variant": str(variant.id), "quantity": quantity}],
            "meysara_percent": percent,
            "language": language,
        },
        format="json",
    )


def test_the_contract_shows_parties_schedule_and_clauses(
    rules, two_shops, shopper, earbuds_variant
):
    user, client = shopper
    ready(user)
    response = show(client, earbuds_variant)  # 5 x 275 = 1 375, 50 %
    assert response.status_code == 200, response.data
    terms = response.data
    assert (terms["version"], terms["language"], len(terms["digest"])) == (
        contract.VERSION,
        "fr",
        64,
    )
    assert terms["buyer"] == {
        "full_name": "Aicha Mint Ahmed",
        "nni": "•••• 5678",
        "phone": "+22236000000",
    }
    assert terms["seller"]["name"] == "Meysara, par Infinity Solutions"
    assert (terms["total"], terms["percent"], terms["financed"], terms["on_delivery"]) == (
        1375,
        50,
        687,
        688,
    )
    assert [(i["amount"], i["days_after_delivery"]) for i in terms["instalments"]] == [
        (172, 14),
        (172, 28),
        (172, 42),
        (171, 56),
    ]
    assert (terms["interest"], terms["fees"], terms["late_fees"]) == (0, 0, 0)
    assert [c["key"] for c in terms["clauses"]][:2] == ["no_interest", "sale"]
    assert terms["lines"][0]["line_total"] == 1375


def test_every_language_has_the_same_clauses():
    keys = {lang: [key for key, _, _ in clauses] for lang, clauses in contract.CLAUSES.items()}
    assert set(keys) == set(contract.LANGUAGES)
    assert keys["fr"] == keys["ar"] == keys["en"]


def test_the_language_changes_the_text_not_the_digest(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    fr, ar = show(client, earbuds_variant).data, show(client, earbuds_variant, language="ar").data
    assert fr["digest"] == ar["digest"]
    assert ar["clauses"][0]["title"] == "لا فوائد ولا رسوم"


def test_the_contract_follows_the_offer(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    refused = show(client, earbuds_variant)
    assert (refused.status_code, refused.data["code"]) == (409, "meysara_not_allowed")
    assert refused.data["reason"] == "meysara_history_insufficient"
    ready(user)
    too_much = show(client, earbuds_variant, percent=100)
    assert too_much.data["code"] == "meysara_not_allowed"


def test_no_order_without_an_accepted_contract(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    payload = {
        **order_payload((earbuds_variant, "5")),
        "payment_method": "meysara",
        "meysara_percent": 50,
    }
    missing = client.post(f"{PUBLIC}/orders", payload, format="json")
    assert (missing.status_code, missing.data["code"]) == (400, "meysara_contract_required")
    not_ticked = {**accepted_contract(client, earbuds_variant), "accepted": False}
    unticked = client.post(
        f"{PUBLIC}/orders", {**payload, "meysara_contract": not_ticked}, format="json"
    )
    assert unticked.data["code"] == "meysara_contract_required"
    assert not MeysaraPlan.objects.exists()


def test_a_contract_read_for_other_amounts_is_refused(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    read_for_four = accepted_contract(client, earbuds_variant, quantity="4")
    payload = {
        **order_payload((earbuds_variant, "5")),
        "payment_method": "meysara",
        "meysara_percent": 50,
        "meysara_contract": read_for_four,
    }
    response = client.post(f"{PUBLIC}/orders", payload, format="json")
    assert (response.status_code, response.data["code"]) == (409, "meysara_contract_outdated")
    old_text = {**accepted_contract(client, earbuds_variant), "version": "0.9"}
    response = client.post(
        f"{PUBLIC}/orders", {**payload, "meysara_contract": old_text}, format="json"
    )
    assert response.data["code"] == "meysara_contract_outdated"
    assert not MeysaraPlan.objects.exists()


def test_the_signed_contract_is_kept_and_emailed(
    rules, two_shops, shopper, earbuds_variant, django_capture_on_commit_callbacks
):
    user, client = shopper
    ready(user)
    with django_capture_on_commit_callbacks(execute=True):
        order = meysara_order(client, earbuds_variant, quantity="5")
    assert order.status_code == 201, order.data
    summary = order.data["meysara"]["contract"]
    number = order.data["number"].removeprefix("MP-")
    assert (summary["number"], summary["version"], summary["language"]) == (
        f"MEY-{number}",
        contract.VERSION,
        "fr",
    )
    signed = MeysaraContract.objects.get()
    assert signed.terms["total"] == 1375 and signed.accepted_at
    assert signed.ip == "127.0.0.1"

    read = client.get(f"{PUBLIC}/orders/{order.data['id']}/meysara/contract")
    assert read.status_code == 200, read.data
    assert read.data["terms"]["digest"] == signed.digest

    copy = [m for m in mail.outbox if "contrat Meysara" in m.subject]
    assert len(copy) == 1 and "Aucun intérêt, aucun frais" in copy[0].body


def test_only_the_buyer_reads_the_contract(rules, two_shops, shopper, earbuds_variant):
    user, client = shopper
    ready(user)
    order = meysara_order(client, earbuds_variant)
    other = client_for(make_user("other@example.com"), UserSession.Realm.CUSTOMER)
    assert other.get(f"{PUBLIC}/orders/{order.data['id']}/meysara/contract").status_code == 404


def test_cash_orders_have_no_contract(two_shops, shopper, earbuds_variant):
    _, client = shopper
    order = client.post(f"{PUBLIC}/orders", order_payload((earbuds_variant, "1")), format="json")
    read = client.get(f"{PUBLIC}/orders/{order.data['id']}/meysara/contract")
    assert (read.status_code, read.data["code"]) == (404, "no_meysara_contract")
