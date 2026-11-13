import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import Product, Variant

pytestmark = pytest.mark.django_db


def test_console_creates_product_with_validated_attributes(staff_client, phone_variant):
    category = phone_variant.product.category
    bad = staff_client.post(
        "/api/v1/console/catalog/products",
        {
            "category": category.id,
            "name": "Galaxy S24",
            "variants": [{"attributes": {"storage": "1 To"}}],
        },
    )
    assert bad.status_code == 400
    assert bad.data["errors"][0]["field"] == "variants.0.attributes.storage"
    good = staff_client.post(
        "/api/v1/console/catalog/products",
        {
            "category": category.id,
            "name": "Galaxy S24",
            "variants": [{"attributes": {"storage": "256 Go"}, "barcode": "880000000777"}],
        },
    )
    assert good.status_code == 201, good.data
    assert good.data["variants"][0]["name"] == "256 Go"


def test_csv_import_is_all_or_nothing(staff_client, phone_variant):
    csv = (
        "category,brand,product,variant,barcode,v:storage\n"
        "smartphones,Tecno,Spark 20,,880000000100,128 Go\n"
        "smartphones,Tecno,Spark 20,,880000000101,256 Go\n"
        "unknown,Tecno,X,,,\n"
    )

    def send(content, dry_run):
        return staff_client.post(
            "/api/v1/console/catalog/products/import",
            {"file": SimpleUploadedFile("c.csv", content.encode()), "dry_run": dry_run},
            format="multipart",
        ).data

    result = send(csv, False)
    assert result["errors"][0]["code"] == "unknown_category"
    assert Product.objects.filter(name="Spark 20").count() == 0
    ok = send(csv.rsplit("\n", 2)[0] + "\n", False)
    assert ok["created_products"] == 1
    assert ok["created_variants"] == 2
    assert Variant.objects.filter(product__name="Spark 20").count() == 2


def test_merchant_searches_catalog_ignoring_accents(owner_client, earbuds_variant):
    found = owner_client.get("/api/v1/catalog/products?search=ecouteurs").data["results"]
    assert [p["name"] for p in found] == ["Écouteurs filaires"]
    by_barcode = owner_client.get("/api/v1/catalog/products?barcode=880000000002")
    assert by_barcode.data["count"] == 1


def test_product_request_flow(store, owner_client, staff_client, phone_variant):
    created = owner_client.post(
        f"/api/v1/stores/{store.id}/product-requests",
        {"name": "Redmi Note 14", "brand_name": "Xiaomi", "barcode": "690000000001"},
    )
    assert created.status_code == 201
    request_id = created.data["id"]
    decided = staff_client.post(
        f"/api/v1/console/product-requests/{request_id}/decide",
        {"approve": True, "variant": phone_variant.id},
    )
    assert decided.data["status"] == "approved"
    mine = owner_client.get(f"/api/v1/stores/{store.id}/product-requests").data["results"]
    assert mine[0]["variant"]["id"] == str(phone_variant.id)
