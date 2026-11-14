from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.catalog.attributes import validate_attributes
from apps.core.management.commands.seed_trades import CATEGORIES, PRODUCTS
from apps.core.tenancy import store_context
from apps.inventory.models import SerialUnit, StoreProduct
from apps.sales.models import Sale, SaleLine
from apps.stores.models import Store, StoreStatus, Trade


def seed(**options):
    call_command("seed_trades", stdout=StringIO(), **options)


def test_catalog_data_matches_category_schemas():
    schemas = {slug: schema for _, slug, _, _, _, _, schema in CATEGORIES}
    for slug, _, name, attrs, rows, *_ in PRODUCTS:
        validate_attributes(schemas[slug], attrs, "product", name)
        for variant_attrs, price, cost in rows:
            validate_attributes(schemas[slug], variant_attrs, "variant", name)
            assert 0 < cost < price, name


@pytest.mark.django_db
def test_one_active_store_per_trade_with_stock_and_sales(owner):
    seed(owner=owner.email)

    stores = {s.trade: s for s in Store.objects.filter(owner=owner)}
    assert set(stores) == {Trade.APPLIANCES, Trade.PHARMACY, Trade.HARDWARE}
    for store in stores.values():
        assert store.status == StoreStatus.ACTIVE
        assert store.memberships.get(user=owner).role == "owner"
        with store_context(store.id):
            assert StoreProduct.objects.filter(quantity__gt=0).exists()
            assert not StoreProduct.objects.filter(quantity__lt=0).exists()
            assert Sale.objects.count() >= 7
            assert all(
                p.variant.product.category.trade == store.trade for p in StoreProduct.objects.all()
            )

    with store_context(stores[Trade.APPLIANCES].id):
        assert SerialUnit.objects.filter(status="sold").exists()
    with store_context(stores[Trade.HARDWARE].id):
        assert any(line.quantity % 1 for line in SaleLine.objects.all())


@pytest.mark.django_db
def test_running_twice_does_not_duplicate(owner):
    seed(owner=owner.email, trades=[Trade.PHARMACY])
    seed(owner=owner.email, trades=[Trade.PHARMACY])
    assert Store.objects.filter(owner=owner, trade=Trade.PHARMACY).count() == 1


@pytest.mark.django_db
def test_creates_a_verified_owner_when_missing():
    seed(owner="new@example.com", password="Another-secret-42", trades=[Trade.HARDWARE])
    user = User.objects.get(email="new@example.com")
    assert user.check_password("Another-secret-42")
    assert user.email_verified_at is not None
