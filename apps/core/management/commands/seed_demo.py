"""Demo data for the 16 Nov 2026 demo: Téléphones catalog, accounts, an active phone shop
with stock, IMEIs and sales, and a store waiting for review in the console.

    uv run python manage.py seed_demo --password '<demo password>'
"""

import random
import secrets
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.catalog.models import Brand, Category, Product, Variant
from apps.console.models import PlatformStaff
from apps.core.tenancy import store_context
from apps.inventory import services as inventory
from apps.inventory.models import Condition, StoreProduct, Supplier
from apps.sales import services as sales
from apps.sales.models import Customer, Payment, Sale
from apps.stores.models import DocumentKind, Membership, Store, StoreDocument, StoreStatus, Trade
from apps.stores.roles import Role

STORAGE = ["32 Go", "64 Go", "128 Go", "256 Go", "512 Go", "1 To"]
RAM = ["2 Go", "4 Go", "6 Go", "8 Go", "12 Go", "16 Go"]

CATEGORIES = [
    # slug, name, name_ar, tracks_serial, warranty, schema
    (
        "smartphones",
        "Smartphones",
        "هواتف ذكية",
        True,
        12,
        [
            {
                "key": "storage",
                "label": "Stockage",
                "label_ar": "السعة",
                "type": "choice",
                "options": STORAGE,
                "required": True,
                "level": "variant",
            },
            {
                "key": "color",
                "label": "Couleur",
                "label_ar": "اللون",
                "type": "text",
                "level": "variant",
            },
            {"key": "ram", "label": "RAM", "type": "choice", "options": RAM, "level": "product"},
            {"key": "dual_sim", "label": "Double SIM", "type": "boolean", "level": "product"},
        ],
    ),
    (
        "telephones-simples",
        "Téléphones simples",
        "هواتف عادية",
        True,
        6,
        [
            {"key": "color", "label": "Couleur", "type": "text", "level": "variant"},
            {"key": "dual_sim", "label": "Double SIM", "type": "boolean", "level": "product"},
        ],
    ),
    (
        "tablettes",
        "Tablettes",
        "أجهزة لوحية",
        True,
        12,
        [
            {
                "key": "storage",
                "label": "Stockage",
                "type": "choice",
                "options": STORAGE,
                "required": True,
                "level": "variant",
            },
            {"key": "color", "label": "Couleur", "type": "text", "level": "variant"},
        ],
    ),
    (
        "ordinateurs-portables",
        "Ordinateurs portables",
        "حواسيب محمولة",
        True,
        12,
        [
            {
                "key": "processor",
                "label": "Processeur",
                "type": "text",
                "required": True,
                "level": "product",
            },
            {"key": "ram", "label": "RAM", "type": "choice", "options": RAM, "level": "product"},
            {
                "key": "storage",
                "label": "Stockage",
                "type": "choice",
                "options": STORAGE,
                "required": True,
                "level": "variant",
            },
        ],
    ),
    (
        "consoles",
        "Consoles de jeux",
        "أجهزة ألعاب",
        True,
        12,
        [
            {
                "key": "edition",
                "label": "Édition",
                "type": "choice",
                "options": ["Standard", "Digital", "OLED"],
                "level": "variant",
            },
            {
                "key": "storage",
                "label": "Stockage",
                "type": "choice",
                "options": STORAGE,
                "level": "variant",
            },
        ],
    ),
    (
        "montres-connectees",
        "Montres connectées",
        "ساعات ذكية",
        True,
        12,
        [
            {"key": "size", "label": "Taille", "type": "text", "level": "variant"},
        ],
    ),
    (
        "audio",
        "Écouteurs & audio",
        "سماعات",
        False,
        3,
        [
            {"key": "color", "label": "Couleur", "type": "text", "level": "variant"},
            {"key": "wireless", "label": "Sans fil", "type": "boolean", "level": "product"},
        ],
    ),
    (
        "chargeurs-cables",
        "Chargeurs & câbles",
        "شواحن وكابلات",
        False,
        3,
        [
            {
                "key": "connector",
                "label": "Connecteur",
                "type": "choice",
                "options": ["USB-C", "Lightning", "Micro-USB"],
                "level": "product",
            },
            {"key": "power_w", "label": "Puissance (W)", "type": "number", "level": "product"},
        ],
    ),
    (
        "coques-protections",
        "Coques & protections",
        "أغطية وحماية",
        False,
        0,
        [
            {
                "key": "compatible_with",
                "label": "Compatible avec",
                "type": "text",
                "level": "product",
            },
        ],
    ),
]

# category, brand, product, product attrs, [(variant attrs, price MRU, cost MRU)]
PRODUCTS = [
    (
        "smartphones",
        "Apple",
        "iPhone 15",
        {"ram": "6 Go", "dual_sim": True},
        [
            ({"storage": "128 Go", "color": "Noir"}, 34000, 30500),
            ({"storage": "128 Go", "color": "Bleu"}, 34000, 30500),
            ({"storage": "256 Go", "color": "Noir"}, 39000, 35200),
        ],
    ),
    (
        "smartphones",
        "Apple",
        "iPhone 14",
        {"ram": "6 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Minuit"}, 27500, 24600)],
    ),
    (
        "smartphones",
        "Apple",
        "iPhone 13",
        {"ram": "4 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Minuit"}, 22000, 19500)],
    ),
    (
        "smartphones",
        "Samsung",
        "Galaxy S24",
        {"ram": "8 Go", "dual_sim": True},
        [({"storage": "256 Go", "color": "Noir"}, 33000, 29400)],
    ),
    (
        "smartphones",
        "Samsung",
        "Galaxy A55",
        {"ram": "8 Go", "dual_sim": True},
        [
            ({"storage": "128 Go", "color": "Bleu nuit"}, 15900, 13800),
            ({"storage": "256 Go", "color": "Bleu nuit"}, 17900, 15600),
        ],
    ),
    (
        "smartphones",
        "Samsung",
        "Galaxy A25",
        {"ram": "6 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Noir"}, 9900, 8500)],
    ),
    (
        "smartphones",
        "Samsung",
        "Galaxy A15",
        {"ram": "4 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Bleu"}, 6900, 5900)],
    ),
    (
        "smartphones",
        "Tecno",
        "Spark 20",
        {"ram": "8 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Gris"}, 4200, 3500)],
    ),
    (
        "smartphones",
        "Tecno",
        "Camon 30",
        {"ram": "8 Go", "dual_sim": True},
        [({"storage": "256 Go", "color": "Noir"}, 7900, 6800)],
    ),
    (
        "smartphones",
        "Infinix",
        "Hot 40i",
        {"ram": "4 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Vert"}, 3900, 3200)],
    ),
    (
        "smartphones",
        "Infinix",
        "Note 40",
        {"ram": "8 Go", "dual_sim": True},
        [({"storage": "256 Go", "color": "Noir"}, 7200, 6200)],
    ),
    (
        "smartphones",
        "Xiaomi",
        "Redmi Note 13",
        {"ram": "8 Go", "dual_sim": True},
        [
            ({"storage": "128 Go", "color": "Noir"}, 6500, 5600),
            ({"storage": "256 Go", "color": "Noir"}, 7400, 6400),
        ],
    ),
    (
        "smartphones",
        "Xiaomi",
        "Redmi 13C",
        {"ram": "4 Go", "dual_sim": True},
        [({"storage": "128 Go", "color": "Bleu"}, 3600, 3000)],
    ),
    (
        "smartphones",
        "itel",
        "A70",
        {"ram": "4 Go", "dual_sim": True},
        [({"storage": "64 Go", "color": "Noir"}, 2400, 1950)],
    ),
    ("telephones-simples", "Nokia", "105", {"dual_sim": True}, [({"color": "Noir"}, 650, 480)]),
    ("telephones-simples", "Nokia", "110 4G", {"dual_sim": True}, [({"color": "Bleu"}, 950, 720)]),
    (
        "tablettes",
        "Apple",
        "iPad 10e génération",
        {},
        [({"storage": "64 Go", "color": "Argent"}, 17500, 15400)],
    ),
    (
        "tablettes",
        "Samsung",
        "Galaxy Tab A9",
        {},
        [({"storage": "64 Go", "color": "Gris"}, 6500, 5500)],
    ),
    (
        "ordinateurs-portables",
        "HP",
        "250 G9",
        {"processor": "Intel Core i5", "ram": "8 Go"},
        [({"storage": "512 Go"}, 22000, 19000)],
    ),
    (
        "ordinateurs-portables",
        "Lenovo",
        "IdeaPad 3",
        {"processor": "Intel Core i3", "ram": "8 Go"},
        [({"storage": "256 Go"}, 16500, 14200)],
    ),
    (
        "ordinateurs-portables",
        "Apple",
        "MacBook Air M2",
        {"processor": "Apple M2", "ram": "8 Go"},
        [({"storage": "256 Go"}, 42000, 37500)],
    ),
    (
        "consoles",
        "Sony",
        "PlayStation 5 Slim",
        {},
        [
            ({"edition": "Standard", "storage": "1 To"}, 23000, 20200),
            ({"edition": "Digital", "storage": "1 To"}, 19900, 17500),
        ],
    ),
    (
        "consoles",
        "Sony",
        "PlayStation 4 Slim",
        {},
        [({"edition": "Standard", "storage": "512 Go"}, 9500, 8000)],
    ),
    (
        "consoles",
        "Microsoft",
        "Xbox Series S",
        {},
        [({"edition": "Digital", "storage": "512 Go"}, 13500, 11800)],
    ),
    (
        "consoles",
        "Nintendo",
        "Switch",
        {},
        [({"edition": "OLED", "storage": "64 Go"}, 14000, 12100)],
    ),
    ("montres-connectees", "Apple", "Watch SE", {}, [({"size": "40 mm"}, 11000, 9600)]),
    ("montres-connectees", "Samsung", "Galaxy Watch6", {}, [({"size": "44 mm"}, 9900, 8400)]),
    ("montres-connectees", "Oraimo", "Watch 2 Pro", {}, [({"size": "1,85 pouce"}, 1400, 1000)]),
    ("audio", "Apple", "AirPods Pro 2", {"wireless": True}, [({"color": "Blanc"}, 9500, 8200)]),
    ("audio", "Apple", "AirPods 3", {"wireless": True}, [({"color": "Blanc"}, 6800, 5800)]),
    (
        "audio",
        "Samsung",
        "Galaxy Buds FE",
        {"wireless": True},
        [({"color": "Graphite"}, 3200, 2600)],
    ),
    ("audio", "Oraimo", "FreePods 4", {"wireless": True}, [({"color": "Noir"}, 1200, 850)]),
    (
        "audio",
        "JBL",
        "Tune 520BT",
        {"wireless": True},
        [({"color": "Noir"}, 2200, 1750), ({"color": "Bleu"}, 2200, 1750)],
    ),
    (
        "audio",
        "Oraimo",
        "Écouteurs filaires Halo",
        {"wireless": False},
        [({"color": "Blanc"}, 250, 140)],
    ),
    (
        "chargeurs-cables",
        "Apple",
        "Chargeur 20W",
        {"connector": "USB-C", "power_w": 20},
        [({}, 900, 650)],
    ),
    (
        "chargeurs-cables",
        "Samsung",
        "Chargeur rapide 25W",
        {"connector": "USB-C", "power_w": 25},
        [({}, 750, 520)],
    ),
    ("chargeurs-cables", "Oraimo", "Câble USB-C 1 m", {"connector": "USB-C"}, [({}, 150, 80)]),
    (
        "chargeurs-cables",
        "Oraimo",
        "Câble Lightning 1 m",
        {"connector": "Lightning"},
        [({}, 200, 110)],
    ),
    (
        "chargeurs-cables",
        "Oraimo",
        "Power bank 20 000 mAh",
        {"connector": "USB-C"},
        [({}, 950, 690)],
    ),
    (
        "coques-protections",
        "Generic",
        "Coque silicone iPhone 15",
        {"compatible_with": "iPhone 15"},
        [({}, 350, 120)],
    ),
    (
        "coques-protections",
        "Generic",
        "Verre trempé Galaxy A55",
        {"compatible_with": "Galaxy A55"},
        [({}, 150, 40)],
    ),
    (
        "coques-protections",
        "Generic",
        "Verre trempé iPhone 15",
        {"compatible_with": "iPhone 15"},
        [({}, 200, 50)],
    ),
]

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


def imei(rng: random.Random) -> str:
    """15 digits with a valid Luhn check digit."""
    body = "35" + "".join(str(rng.randint(0, 9)) for _ in range(12))
    total = 0
    for index, char in enumerate(reversed(body)):
        digit = int(char) * (2 if index % 2 == 0 else 1)
        total += digit - 9 if digit > 9 else digit
    return body + str((10 - total % 10) % 10)


class Command(BaseCommand):
    help = "Load the Téléphones demo (catalog, accounts, an active shop with sales)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for every demo account")

    def handle(self, *args, **options):
        if Store.objects.filter(name="Sahel Phones").exists():
            self.stdout.write(self.style.WARNING("Demo already loaded."))
            return
        password = options["password"] or secrets.token_urlsafe(12)
        with transaction.atomic():
            variants = self.catalog()
            accounts = self.accounts(password)
            self.shop(accounts, variants)
            self.pending_store(password)
        self.stdout.write(self.style.SUCCESS("Demo loaded. Accounts (same password):"))
        for label, email in [
            ("Console super-admin", "admin@mahali.infinity.mr"),
            ("Propriétaire Sahel Phones", "demo@mahali.infinity.mr"),
            ("Caissier", "caisse@mahali.infinity.mr"),
            ("Magasinier", "stock@mahali.infinity.mr"),
            ("Boutique en attente (Nouadhibou)", "attente@mahali.infinity.mr"),
        ]:
            self.stdout.write(f"  {label:34} {email}")
        self.stdout.write(f"  password: {password}")

    def catalog(self) -> dict:
        categories = {}
        for order, (slug, name, name_ar, serial, warranty, schema) in enumerate(CATEGORIES):
            categories[slug], _ = Category.objects.update_or_create(
                slug=slug,
                defaults={
                    "trade": Trade.TELEPHONES,
                    "name": name,
                    "name_ar": name_ar,
                    "tracks_serial": serial,
                    "default_warranty_months": warranty,
                    "attribute_schema": schema,
                    "sort_order": order,
                },
            )
        variants = {}
        barcode = 6290000000000
        for slug, brand_name, name, attrs, rows in PRODUCTS:
            brand, _ = Brand.objects.get_or_create(
                slug=slugify(brand_name), defaults={"name": brand_name, "trades": ["telephones"]}
            )
            product, _ = Product.objects.get_or_create(
                category=categories[slug], brand=brand, name=name, defaults={"attributes": attrs}
            )
            for variant_attrs, price, cost in rows:
                barcode += 1
                label = " · ".join(str(v) for v in variant_attrs.values())
                variant, _ = Variant.objects.get_or_create(
                    product=product,
                    name=label,
                    defaults={"attributes": variant_attrs, "barcode": str(barcode)},
                )
                variants[f"{name} {label}".strip()] = (variant, price, cost)
        return variants

    def accounts(self, password) -> dict:
        def user(email, name, phone=""):
            obj = User.objects.filter(email=email).first() or User.objects.create_user(
                email=email,
                password=password,
                full_name=name,
                phone=phone,
                email_verified_at=timezone.now(),
            )
            return obj

        admin = user("admin@mahali.infinity.mr", "Équipe Mahali")
        PlatformStaff.objects.get_or_create(user=admin, defaults={"role": "super_admin"})
        owner = user("demo@mahali.infinity.mr", "Mohamed Lemine Ould Ahmed", "+22236112233")
        owner.identity_verified_at = timezone.now()
        owner.save(update_fields=["identity_verified_at"])
        return {
            "owner": owner,
            "cashier": user("caisse@mahali.infinity.mr", "Mariem Mint Sidi"),
            "stock": user("stock@mahali.infinity.mr", "Cheikh Ould Brahim"),
        }

    def shop(self, accounts, variants):
        owner = accounts["owner"]
        now = timezone.now()
        store = Store.objects.create(
            owner=owner,
            name="Sahel Phones",
            trade=Trade.TELEPHONES,
            status=StoreStatus.ACTIVE,
            city="Nouakchott",
            address="Avenue Gamal Abdel Nasser, Capitale",
            phone="+22236112233",
            submitted_at=now - timedelta(days=12),
            approved_at=now - timedelta(days=11),
            decided_at=now - timedelta(days=11),
        )
        Membership.objects.create(store=store, user=owner, role=Role.OWNER)
        Membership.objects.create(store=store, user=accounts["cashier"], role=Role.CASHIER)
        Membership.objects.create(store=store, user=accounts["stock"], role=Role.STOCK_KEEPER)

        rng = random.Random(16112026)  # noqa: S311  # nosec B311
        request = SimpleNamespace(
            store=store,
            user=owner,
            store_role=Role.OWNER,
            client_ip=None,
            auth_realm="merchant",
            headers={},
        )
        with store_context(store.id):
            supplier = Supplier.objects.create(
                store=store, name="Dubai Mobile Trading", phone="+971501234567"
            )
            Supplier.objects.create(store=store, name="Oraimo Mauritanie", phone="+22245250000")
            for name, phone in [
                ("Sidi Mohamed Ould Cheikh", "+22236000101"),
                ("Aïchetou Mint Ahmed", "+22246000202"),
                ("Entreprise Al Baraka", "+22245000303"),
            ]:
                Customer.objects.create(store=store, name=name, phone=phone)

            products, lines = {}, []
            for label, (variant, price, cost) in variants.items():
                store_product = StoreProduct.objects.create(
                    store=store,
                    variant=variant,
                    sale_price=price,
                    warranty_months=variant.product.category.default_warranty_months,
                    reorder_level=2 if variant.product.category.tracks_serial else 5,
                )
                products[label] = store_product
                quantity = (
                    rng.randint(2, 6)
                    if variant.product.category.tracks_serial
                    else rng.randint(8, 30)
                )
                lines.append(
                    {
                        "store_product": store_product,
                        "quantity": Decimal(quantity),
                        "unit_cost": cost,
                        "serials": (
                            [imei(rng) for _ in range(quantity)]
                            if variant.product.category.tracks_serial
                            else []
                        ),
                    }
                )
            inventory.receive(
                store, owner, lines=lines, supplier=supplier, supplier_reference="DMT-2026-1104"
            )

            used_variant = products["iPhone 13 128 Go · Minuit"].variant
            used = StoreProduct.objects.create(
                store=store,
                variant=used_variant,
                condition=Condition.USED,
                sale_price=16500,
                warranty_months=3,
            )
            inventory.receive(
                store,
                owner,
                lines=[
                    {
                        "store_product": used,
                        "quantity": Decimal(2),
                        "unit_cost": 13500,
                        "serials": [imei(rng), imei(rng)],
                    }
                ],
                supplier_reference="Rachat clients",
            )

            sales.open_session(store, owner, 5000)
            customers = list(Customer.objects.all())
            catalogue = list(products.values())
            for day in range(6, -1, -1):
                for _ in range(rng.randint(3, 6)):
                    picks = rng.sample(catalogue, rng.randint(1, 2))
                    sale_lines = []
                    for product in picks:
                        product.refresh_from_db()
                        if product.quantity < 1:
                            continue
                        line = {"store_product": product, "quantity": Decimal(1)}
                        if product.tracks_serial:
                            unit = product.serial_units.filter(status="in_stock").first()
                            line["serial"] = unit.serial
                        sale_lines.append(line)
                    if not sale_lines:
                        continue
                    total = sum(p.sale_price for p in picks if p.quantity >= 1)
                    on_credit = rng.random() < 0.15
                    paid = total // 2 if on_credit else total
                    method = rng.choice(["cash", "cash", "bankily", "masrvi", "sedad"])
                    sale = sales.create_sale(
                        request,
                        lines=sale_lines,
                        payments=[
                            {
                                "method": method,
                                "amount": paid,
                                "reference": ""
                                if method == "cash"
                                else f"TX{rng.randint(100000, 999999)}",
                            }
                        ],
                        customer=rng.choice(customers) if on_credit else None,
                    )
                    if day:
                        when = timezone.now() - timedelta(days=day, hours=rng.randint(0, 6))
                        Sale.objects.filter(pk=sale.pk).update(created_at=when)
                        Payment.objects.filter(sale=sale).update(created_at=when)
            sales.record_expense(
                request,
                category="transport",
                amount=300,
                method="cash",
                note="Livraison fournisseur",
            )

    def pending_store(self, password):
        owner = User.objects.create_user(
            email="attente@mahali.infinity.mr",
            password=password,
            full_name="Ahmedou Ould Mohamed Vall",
            phone="+22222334455",
            email_verified_at=timezone.now(),
        )
        store = Store.objects.create(
            owner=owner,
            name="Galaxy Center Nouadhibou",
            trade=Trade.TELEPHONES,
            status=StoreStatus.PENDING_APPROVAL,
            city="Nouadhibou",
            address="Rue du Marché central",
            submitted_at=timezone.now() - timedelta(hours=5),
        )
        Membership.objects.create(store=store, user=owner, role=Role.OWNER)
        for kind in (DocumentKind.ID_FRONT, DocumentKind.ID_BACK, DocumentKind.STOREFRONT):
            doc = StoreDocument(
                store=store,
                kind=kind,
                original_name=f"{kind}.png",
                content_type="image/png",
                size=len(TINY_PNG),
                uploaded_by=owner,
            )
            doc.extension = ".png"
            doc.file.save(f"{kind}.png", ContentFile(TINY_PNG), save=False)
            doc.save()
