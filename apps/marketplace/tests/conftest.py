"""Marketplace test fixtures (shared by test_marketplace and test_meysara)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import UserSession
from apps.console.models import PlatformSettings
from conftest import client_for, make_store, make_user

from .helpers import stock


@pytest.fixture
def margin():
    settings = PlatformSettings.load()
    settings.marketplace_margin_percent = Decimal(10)
    settings.save()
    return settings


@pytest.fixture
def two_shops(margin, phone_variant, earbuds_variant):
    cheap = make_store(make_user("cheap@example.com"), name="Cheap")
    dear = make_store(make_user("dear@example.com"), name="Dear")
    return {
        "cheap": cheap,
        "dear": dear,
        "cheap_phone": stock(
            cheap, phone_variant, 14500, 2, ["111111111111111", "222222222222222"]
        ),
        "dear_phone": stock(dear, phone_variant, 15000, 1, ["333333333333333"]),
        "dear_earbuds": stock(dear, earbuds_variant, 250, 10),
    }


# What a shopper gives when signing up (the e-KYC then proves it).
PROFILE = {
    "full_name": "Aicha Mint Ahmed",
    "phone": "+22236000000",
    "nni": "2012345678",
    "birth_date": date(1995, 3, 14),
}


@pytest.fixture
def shopper():
    user = make_user("client@example.com", **PROFILE)
    return user, client_for(user, UserSession.Realm.CUSTOMER)


@pytest.fixture
def rules(margin):
    """Small amounts so the earbuds (275 MRU each with the margin) can use Meysara."""
    settings = PlatformSettings.load()
    settings.meysara_min_total = 1000
    settings.meysara_max_financed = 60000
    settings.save()
    return settings
