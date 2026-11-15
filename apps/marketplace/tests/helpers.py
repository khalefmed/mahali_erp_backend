"""Shared by the marketplace tests."""

from decimal import Decimal

from apps.core.tenancy import store_context
from apps.inventory import services as inventory
from apps.inventory.models import StoreProduct
from conftest import client_for

PUBLIC = "/api/v1/marketplace"


def stock(store, variant, price, quantity, serials=()):
    with store_context(store.id):
        product = StoreProduct.objects.create(store=store, variant=variant, sale_price=price)
        inventory.receive(
            store,
            store.owner,
            lines=[
                {
                    "store_product": product,
                    "quantity": Decimal(quantity),
                    "unit_cost": price // 2,
                    "serials": list(serials),
                }
            ],
        )
    return product


def quantity_of(product):
    with store_context(product.store_id):
        return StoreProduct.objects.get(pk=product.pk).quantity


def order_payload(*lines):
    return {
        "lines": [{"variant": str(v.id), "quantity": q} for v, q in lines],
        "delivery_name": "Aicha",
        "delivery_phone": "+22236000000",
        "delivery_city": "Nouakchott",
        "delivery_address": "Tevragh Zeina, lot 12",
    }


def store_client(store):
    return client_for(store.owner)
