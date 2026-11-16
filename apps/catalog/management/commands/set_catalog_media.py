"""Photos and Arabic names of the Mahali catalog, from `apps/catalog/catalog_media.json`.

Each entry names a product (`name` + `brand`, as in the catalog), its photo (a file in
`apps/catalog/static/catalog/products/`, served by WhiteNoise), its Arabic name and the
photo's credit (author, licence, source: CC BY / BY-SA ask for it). Idempotent; products
not in the file are left alone. An Arabic name already set is kept unless `--force`.

    uv run python manage.py set_catalog_media --base-url https://mahali-api-staging.infinity.mr
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Product

MEDIA_FILE = Path(__file__).resolve().parents[2] / "catalog_media.json"
PHOTOS_DIR = Path(__file__).resolve().parents[2] / "static" / "catalog" / "products"


class Command(BaseCommand):
    help = "Set catalog product photos (image_url) and Arabic names from catalog_media.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            required=True,
            help="Public origin of this API, e.g. https://mahali-api-staging.infinity.mr",
        )
        parser.add_argument("--force", action="store_true", help="Overwrite Arabic names")

    @transaction.atomic
    def handle(self, *args, base_url, force, **options):
        entries = json.loads(MEDIA_FILE.read_text(encoding="utf-8"))
        prefix = f"{base_url.rstrip('/')}/{settings.STATIC_URL.strip('/')}/catalog/products/"
        updated, missing = 0, []
        for entry in entries:
            if not (PHOTOS_DIR / entry["image"]).is_file():
                raise CommandError(f"Missing photo file: {entry['image']}")
            products = Product.objects.filter(name=entry["name"])
            products = (
                products.filter(brand__name=entry["brand"])
                if entry.get("brand")
                else products.filter(brand__isnull=True)
            )
            if not products.exists():
                missing.append(entry["name"])
                continue
            for product in products:
                product.image_url = prefix + entry["image"]
                if entry.get("name_ar") and (force or not product.name_ar):
                    product.name_ar = entry["name_ar"]
                product.save(update_fields=["image_url", "name_ar", "updated_at"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"{updated} products updated"))
        if missing:
            self.stdout.write(f"Not in this catalog ({len(missing)}): {', '.join(missing)}")
