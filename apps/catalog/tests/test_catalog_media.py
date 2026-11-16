from django.core.management import call_command

from apps.catalog.models import Product


def test_set_catalog_media_sets_photo_and_arabic_name(phone_variant):
    product = phone_variant.product  # Samsung Galaxy A55, also in catalog_media.json
    call_command("set_catalog_media", base_url="https://api.example.com/")
    product.refresh_from_db()
    assert product.image_url == (
        "https://api.example.com/static/catalog/products/samsung-galaxy-a55.jpg"
    )
    assert product.name_ar == "هاتف Galaxy A55"

    # Idempotent, and an Arabic name set by the Mahali team is kept.
    Product.objects.filter(pk=product.pk).update(name_ar="غالاكسي A55")
    call_command("set_catalog_media", base_url="https://api.example.com")
    product.refresh_from_db()
    assert product.name_ar == "غالاكسي A55"
