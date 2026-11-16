"""ERP web back-office routes (lot 2): store preferences, role policies, treasury,
recurring expenses and budgets."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.tenancy import store_context
from apps.sales.models import Expense
from apps.stores.roles import Role
from conftest import add_member, api, client_for

pytestmark = pytest.mark.django_db


def test_store_preferences(store, owner_client):
    assert owner_client.get(api(store, "payment-settings")).data == {
        "cash": True,
        "mobile_money": True,
        "bank_transfer": True,
        "customer_credit": True,
    }
    patched = owner_client.patch(api(store, "payment-settings"), {"customer_credit": False})
    assert patched.data["customer_credit"] is False
    assert patched.data["cash"] is True

    policy = owner_client.patch(
        api(store, "credit-policy"), {"block_after_days": 30, "guarantor_above": 50000}
    ).data
    assert policy == {"block_after_days": 30, "guarantor_above": 50000, "deposit_deducted": True}

    reminders = owner_client.patch(
        api(store, "reminder-settings"), {"overdue_weekly": False, "before_due_days": 9}
    ).data
    assert reminders == {"before_due": True, "before_due_days": 3, "overdue_weekly": False}

    setup = owner_client.get(api(store, "setup")).data
    assert setup == {"trades": ["telephones"], "modules": [], "blank": False, "completed_at": None}
    done = owner_client.patch(api(store, "setup"), {"completed": True}).data
    assert done["completed_at"] is not None


def test_only_the_owner_changes_preferences(store):
    cashier = client_for(add_member(store, Role.CASHIER, "caisse@example.com"))
    assert cashier.get(api(store, "credit-policy")).status_code == 200  # read at the till
    assert cashier.patch(api(store, "credit-policy"), {"block_after_days": 1}).status_code == 403


def test_role_policies(store, owner_client):
    policies = owner_client.get(api(store, "role-policies")).data["results"]
    assert [p["role"] for p in policies] == ["manager", "cashier", "seller", "stock_keeper"]
    cashier = policies[1]
    assert cashier["max_discount_percent"] == store.max_discount_percent
    assert cashier["see_daily_takings"] is False

    patched = owner_client.patch(
        api(store, "role-policies/cashier"), {"see_daily_takings": True, "cash_tolerance": 500}
    ).data
    assert patched["see_daily_takings"] is True
    assert patched["cash_tolerance"] == 500
    assert owner_client.get(api(store, "role-policies")).data["results"][1] == patched

    unknown = owner_client.patch(api(store, "role-policies/owner"), {"see_daily_takings": True})
    assert unknown.status_code == 404
    assert unknown.data["code"] == "invalid_role"


def test_treasury_accounts_movements_and_transfers(store, owner_client, earbuds_variant):
    earbuds = owner_client.post(
        api(store, "products"), {"variant_id": earbuds_variant.id, "sale_price": 250}
    ).data
    owner_client.post(
        api(store, "receipts"),
        {"lines": [{"store_product": earbuds["id"], "quantity": "10", "unit_cost": 120}]},
    )
    owner_client.post(api(store, "cash-sessions"), {"opening_float": 1000})
    owner_client.post(
        api(store, "sales"),
        {
            "lines": [{"store_product": earbuds["id"], "quantity": "4"}],
            "payments": [
                {"method": "cash", "amount": 600},
                {"method": "bankily", "amount": 400, "reference": "BK-1"},
            ],
        },
    )
    owner_client.post(
        api(store, "expenses"), {"category": "transport", "amount": 100, "method": "cash"}
    )
    today = timezone.localdate().isoformat()
    same = owner_client.post(
        api(store, "money-transfers"),
        {"from_account": "cash", "to_account": "cash", "amount": 10, "date": today, "note": ""},
    )
    assert same.data["code"] == "same_account"
    moved = owner_client.post(
        api(store, "money-transfers"),
        {"from_account": "cash", "to_account": "bank_transfer", "amount": 300, "date": today},
    )
    assert moved.status_code == 201, moved.data

    accounts = {a["id"]: a for a in owner_client.get(api(store, "money-accounts")).data["results"]}
    assert accounts["cash"]["balance"] == 600 - 100 - 300
    assert accounts["cash"]["is_store_till"] is True
    assert accounts["cash"]["opened_by_name"]
    assert accounts["bankily"]["balance"] == 400
    assert accounts["bankily"]["kind"] == "mobile_money"
    assert accounts["bankily"]["operations_today"] == 1
    assert accounts["bank_transfer"]["balance"] == 300

    movements = owner_client.get(api(store, "money-movements"), {"date": today}).data["results"]
    kinds = sorted(m["kind"] for m in movements)
    assert kinds == ["expense", "sale", "sale", "transfer", "transfer"]
    assert sum(m["amount"] for m in movements) == 600 + 400 - 100  # transfers net to 0

    journal = owner_client.get(api(store, "accounting/journal"), {"date": today}).data
    transfer = next(e for e in journal["entries"] if e["journal"] == "misc")
    assert [line["account"] for line in transfer["lines"]] == ["521", "571"]


def test_recurring_expenses_and_budgets(store, owner, owner_client):
    yesterday = timezone.localdate() - timedelta(days=1)
    rent = owner_client.post(
        api(store, "recurring-expenses"),
        {
            "label": "Loyer boutique",
            "category": "rent",
            "amount": 30000,
            "method": "bank_transfer",
            "frequency": "monthly",
            "next_date": yesterday.isoformat(),
            "variable_amount": False,
        },
    )
    assert rent.status_code == 201, rent.data
    bill = owner_client.post(
        api(store, "recurring-expenses"),
        {
            "label": "Électricité",
            "category": "utilities",
            "amount": 4000,
            "method": "cash",
            "frequency": "monthly",
            "next_date": yesterday.isoformat(),
            "variable_amount": True,
        },
    ).data
    listing = owner_client.get(api(store, "recurring-expenses")).data["results"]
    assert len(listing) == 2

    call_command("post_recurring_expenses", stdout=open("/dev/null", "w"))  # noqa: SIM115
    with store_context(store.id):
        assert list(Expense.objects.values_list("note", "amount")) == [("Loyer boutique", 30000)]
    after = {
        r["label"]: r for r in owner_client.get(api(store, "recurring-expenses")).data["results"]
    }
    assert after["Loyer boutique"]["next_date"] > timezone.localdate().isoformat()
    assert after["Électricité"]["next_date"] > timezone.localdate().isoformat()  # moved, not posted

    assert owner_client.delete(api(store, f"recurring-expenses/{bill['id']}")).status_code == 204

    budgets = owner_client.put(
        api(store, "expense-budgets"),
        {
            "results": [
                {"category": "rent", "amount": 30000},
                {"category": "transport", "amount": 5000},
            ]
        },
        format="json",
    )
    assert budgets.status_code == 200, budgets.data
    assert owner_client.get(api(store, "expense-budgets")).data["results"] == [
        {"category": "rent", "amount": 30000},
        {"category": "transport", "amount": 5000},
    ]
    twice = owner_client.put(
        api(store, "expense-budgets"),
        {"results": [{"category": "rent", "amount": 1}, {"category": "rent", "amount": 2}]},
        format="json",
    )
    assert twice.status_code == 400
