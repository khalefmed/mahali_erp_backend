"""Test data for the other trades: Électroménager, Pharmacie, Quincaillerie.

For each trade: the Mahali catalog (categories, brands, products, variants) and one
active store owned by `--owner`, with suppliers, customers, received stock (serial numbers
where the category tracks them), 7 days of sales and an expense. Idempotent: a trade for
which the owner already has a store is skipped. Does not touch `seed_demo` data.

    uv run python manage.py seed_trades --owner dev@example.com [--password '<pwd>']
"""

import random
import secrets
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.catalog.models import Brand, Category, Product, Variant
from apps.core.tenancy import store_context
from apps.inventory import services as inventory
from apps.inventory.models import StoreProduct, Supplier
from apps.sales import services as sales
from apps.sales.models import Customer, Payment, Sale
from apps.stores.models import Membership, Store, StoreStatus, Trade
from apps.stores.roles import Role


def attr(key, label, kind="text", level="product", options=None, required=False, label_ar=""):
    definition = {"key": key, "label": label, "type": kind, "level": level}
    if label_ar:
        definition["label_ar"] = label_ar
    if options:
        definition["options"] = options
    if required:
        definition["required"] = True
    return definition


# trade, slug, name, name_ar, tracks_serial, warranty months, attribute schema
CATEGORIES = [
    # Électroménager
    (
        Trade.APPLIANCES,
        "refrigerateurs",
        "Réfrigérateurs & congélateurs",
        "ثلاجات ومجمدات",
        True,
        24,
        [
            attr("capacity_l", "Capacité (L)", "number", required=True, label_ar="السعة (لتر)"),
            attr("energy_class", "Classe énergétique", "choice", options=["A+++", "A++", "A+"]),
            attr("color", "Couleur", level="variant", label_ar="اللون"),
        ],
    ),
    (
        Trade.APPLIANCES,
        "climatiseurs",
        "Climatiseurs",
        "مكيفات",
        True,
        24,
        [
            attr(
                "btu",
                "Puissance",
                "choice",
                "variant",
                ["9000 BTU", "12000 BTU", "18000 BTU", "24000 BTU"],
                required=True,
                label_ar="القدرة",
            ),
            attr("type", "Type", "choice", options=["Split", "Fenêtre", "Portable"]),
            attr("inverter", "Inverter", "boolean"),
        ],
    ),
    (
        Trade.APPLIANCES,
        "televiseurs",
        "Téléviseurs",
        "تلفزيونات",
        True,
        12,
        [
            attr(
                "screen",
                "Taille d'écran",
                "choice",
                "variant",
                ["32 pouces", "43 pouces", "50 pouces", "55 pouces", "65 pouces"],
                required=True,
                label_ar="حجم الشاشة",
            ),
            attr("smart", "Smart TV", "boolean"),
        ],
    ),
    (
        Trade.APPLIANCES,
        "machines-a-laver",
        "Machines à laver",
        "غسالات",
        True,
        24,
        [
            attr(
                "capacity_kg",
                "Capacité",
                "choice",
                "variant",
                ["7 kg", "8 kg", "9 kg", "10 kg", "12 kg"],
                required=True,
                label_ar="السعة",
            ),
            attr("loading", "Chargement", "choice", options=["Frontal", "Par le dessus"]),
        ],
    ),
    (
        Trade.APPLIANCES,
        "petit-electromenager",
        "Petit électroménager",
        "أجهزة منزلية صغيرة",
        False,
        12,
        [attr("power_w", "Puissance (W)", "number"), attr("color", "Couleur", level="variant")],
    ),
    (
        Trade.APPLIANCES,
        "ventilateurs",
        "Ventilateurs",
        "مراوح",
        False,
        6,
        [attr("type", "Type", "choice", options=["Sur pied", "De table", "Plafond"])],
    ),
    # Pharmacie (sans ordonnances ni CNAM en v1)
    (
        Trade.PHARMACY,
        "medicaments",
        "Médicaments sans ordonnance",
        "أدوية بدون وصفة",
        False,
        0,
        [
            attr(
                "form",
                "Forme",
                "choice",
                options=["Comprimé", "Comprimé effervescent", "Gélule", "Sirop", "Sachet", "Crème"],
                required=True,
                label_ar="الشكل",
            ),
            attr("dosage", "Dosage", label_ar="الجرعة"),
            attr("pack", "Conditionnement", level="variant", required=True, label_ar="العبوة"),
        ],
    ),
    (
        Trade.PHARMACY,
        "dermo-cosmetique",
        "Dermo-cosmétique",
        "مستحضرات العناية بالبشرة",
        False,
        0,
        [
            attr("skin", "Type de peau", "choice", options=["Tous", "Sèche", "Sensible", "Grasse"]),
            attr("volume", "Contenance", level="variant", required=True, label_ar="الحجم"),
        ],
    ),
    (
        Trade.PHARMACY,
        "bebe",
        "Bébé & maman",
        "الأم والطفل",
        False,
        0,
        [attr("size", "Taille / âge", level="variant", required=True, label_ar="المقاس")],
    ),
    (
        Trade.PHARMACY,
        "hygiene",
        "Hygiène",
        "النظافة",
        False,
        0,
        [attr("volume", "Contenance", level="variant")],
    ),
    (
        Trade.PHARMACY,
        "autotest",
        "Tensiomètres & glucomètres",
        "أجهزة قياس الضغط والسكر",
        True,
        24,
        [attr("measure", "Mesure", "choice", options=["Tension", "Glycémie"], required=True)],
    ),
    (
        Trade.PHARMACY,
        "materiel-soins",
        "Matériel de soins",
        "مستلزمات العلاج",
        False,
        0,
        [],
    ),
    # Quincaillerie
    (
        Trade.HARDWARE,
        "outillage-electroportatif",
        "Outillage électroportatif",
        "أدوات كهربائية",
        True,
        12,
        [
            attr("power_w", "Puissance (W)", "number", label_ar="القدرة"),
            attr("cordless", "Sans fil", "boolean"),
        ],
    ),
    (
        Trade.HARDWARE,
        "outillage-main",
        "Outillage à main",
        "أدوات يدوية",
        False,
        0,
        [attr("size", "Dimension", level="variant")],
    ),
    (
        Trade.HARDWARE,
        "plomberie",
        "Plomberie",
        "سباكة",
        False,
        0,
        [
            attr(
                "diameter",
                "Diamètre",
                "choice",
                "variant",
                ["20 mm", "25 mm", "32 mm", "50 mm", "110 mm"],
                label_ar="القطر",
            )
        ],
    ),
    (
        Trade.HARDWARE,
        "electricite",
        "Électricité",
        "كهرباء",
        False,
        0,
        [
            attr(
                "section",
                "Section",
                "choice",
                "variant",
                ["1,5 mm²", "2,5 mm²", "4 mm²", "6 mm²"],
                label_ar="المقطع",
            )
        ],
    ),
    (
        Trade.HARDWARE,
        "peinture",
        "Peinture",
        "دهانات",
        False,
        0,
        [
            attr("finish", "Finition", "choice", options=["Mat", "Satiné", "Brillant"]),
            attr("volume", "Contenance", "choice", "variant", ["1 L", "4 L", "20 L"]),
        ],
    ),
    (
        Trade.HARDWARE,
        "visserie-fixation",
        "Visserie & fixation",
        "براغي ومسامير",
        False,
        0,
        [],
    ),
    (
        Trade.HARDWARE,
        "materiaux",
        "Matériaux de construction",
        "مواد البناء",
        False,
        0,
        [attr("diameter", "Diamètre", "choice", "variant", ["8 mm", "10 mm", "12 mm"])],
    ),
]

# Decimal quantities (hardware sold by the metre or the kilo): stock received and what a
# customer typically buys. Every other product is received by units and sold one at a time.
METRE = {"stock": Decimal(500), "sell": [Decimal(5), Decimal("12.5"), Decimal(25), Decimal(50)]}
KILO = {"stock": Decimal(80), "sell": [Decimal("0.5"), Decimal(1), Decimal("2.5"), Decimal(5)]}

# category, brand (None = unbranded), product, product attrs,
# [(variant attrs, price MRU, cost MRU)], quantities (optional)
PRODUCTS = [
    # Électroménager
    (
        "refrigerateurs",
        "Samsung",
        "Réfrigérateur combiné RB34",
        {"capacity_l": 340, "energy_class": "A++"},
        [({"color": "Inox"}, 21500, 18200), ({"color": "Noir"}, 22500, 19000)],
    ),
    (
        "refrigerateurs",
        "LG",
        "Réfrigérateur double porte GN-B392",
        {"capacity_l": 395, "energy_class": "A+"},
        [({"color": "Argent"}, 18900, 15800)],
    ),
    (
        "refrigerateurs",
        "Hisense",
        "Réfrigérateur RD-35",
        {"capacity_l": 270, "energy_class": "A+"},
        [({"color": "Blanc"}, 12800, 10600)],
    ),
    (
        "refrigerateurs",
        "Beko",
        "Congélateur coffre HS221",
        {"capacity_l": 205, "energy_class": "A+"},
        [({"color": "Blanc"}, 11500, 9400)],
    ),
    (
        "climatiseurs",
        "Midea",
        "Climatiseur Mission",
        {"type": "Split", "inverter": False},
        [({"btu": "12000 BTU"}, 14500, 12000), ({"btu": "18000 BTU"}, 19800, 16500)],
    ),
    (
        "climatiseurs",
        "Gree",
        "Climatiseur Lomo",
        {"type": "Split", "inverter": True},
        [({"btu": "12000 BTU"}, 15900, 13200), ({"btu": "24000 BTU"}, 29500, 24800)],
    ),
    (
        "climatiseurs",
        "LG",
        "Climatiseur Dual Inverter",
        {"type": "Split", "inverter": True},
        [({"btu": "12000 BTU"}, 22000, 18500)],
    ),
    (
        "televiseurs",
        "Samsung",
        "Crystal UHD CU7000",
        {"smart": True},
        [({"screen": "43 pouces"}, 13900, 11600), ({"screen": "55 pouces"}, 21500, 18200)],
    ),
    (
        "televiseurs",
        "TCL",
        "Smart TV S5400",
        {"smart": True},
        [({"screen": "32 pouces"}, 5900, 4700), ({"screen": "43 pouces"}, 8900, 7300)],
    ),
    (
        "televiseurs",
        "Hisense",
        "UHD A6",
        {"smart": True},
        [({"screen": "55 pouces"}, 16900, 14000)],
    ),
    (
        "machines-a-laver",
        "LG",
        "Lave-linge F4V5",
        {"loading": "Frontal"},
        [({"capacity_kg": "8 kg"}, 18900, 15800)],
    ),
    (
        "machines-a-laver",
        "Beko",
        "Lave-linge WTV7",
        {"loading": "Frontal"},
        [({"capacity_kg": "7 kg"}, 13500, 11200)],
    ),
    (
        "machines-a-laver",
        "Midea",
        "Lave-linge MA200",
        {"loading": "Par le dessus"},
        [({"capacity_kg": "10 kg"}, 12900, 10700)],
    ),
    (
        "petit-electromenager",
        "Moulinex",
        "Blender Blendforce",
        {"power_w": 600},
        [({"color": "Noir"}, 1450, 1050)],
    ),
    (
        "petit-electromenager",
        "Tefal",
        "Fer à repasser Virtuo",
        {"power_w": 2000},
        [({"color": "Bleu"}, 1250, 900)],
    ),
    (
        "petit-electromenager",
        "Kenwood",
        "Bouilloire 1,7 L",
        {"power_w": 2200},
        [({"color": "Inox"}, 950, 680)],
    ),
    (
        "petit-electromenager",
        "Binatone",
        "Micro-ondes 20 L",
        {"power_w": 700},
        [({"color": "Blanc"}, 3400, 2700)],
    ),
    (
        "ventilateurs",
        "Binatone",
        "Ventilateur sur pied 16 pouces",
        {"type": "Sur pied"},
        [({}, 1350, 950)],
    ),
    ("ventilateurs", "Midea", "Ventilateur de plafond", {"type": "Plafond"}, [({}, 1900, 1400)]),
    # Pharmacie
    (
        "medicaments",
        "Sanofi",
        "Doliprane",
        {"form": "Comprimé", "dosage": "1000 mg"},
        [({"pack": "Boîte de 8"}, 45, 30)],
    ),
    (
        "medicaments",
        "Sanofi",
        "Doliprane enfant",
        {"form": "Sirop", "dosage": "2,4 %"},
        [({"pack": "Flacon 100 ml"}, 60, 40)],
    ),
    (
        "medicaments",
        "UPSA",
        "Efferalgan",
        {"form": "Comprimé effervescent", "dosage": "1 g"},
        [({"pack": "Boîte de 8"}, 55, 38)],
    ),
    (
        "medicaments",
        "Teva",
        "Spasfon",
        {"form": "Comprimé", "dosage": "80 mg"},
        [({"pack": "Boîte de 30"}, 120, 85)],
    ),
    (
        "medicaments",
        "Ipsen",
        "Smecta",
        {"form": "Sachet", "dosage": "3 g"},
        [({"pack": "Boîte de 30"}, 140, 100)],
    ),
    (
        "medicaments",
        "UPSA",
        "Vitamine C",
        {"form": "Comprimé effervescent", "dosage": "1000 mg"},
        [({"pack": "Tube de 20"}, 120, 85)],
    ),
    (
        "medicaments",
        "Biafine",
        "Biafine émulsion",
        {"form": "Crème"},
        [({"pack": "Tube 93 g"}, 160, 115)],
    ),
    (
        "dermo-cosmetique",
        "Nivea",
        "Crème Nivea",
        {"skin": "Tous"},
        [({"volume": "150 ml"}, 160, 110), ({"volume": "400 ml"}, 330, 240)],
    ),
    (
        "dermo-cosmetique",
        "Bioderma",
        "Sensibio H2O",
        {"skin": "Sensible"},
        [({"volume": "250 ml"}, 420, 320), ({"volume": "500 ml"}, 650, 500)],
    ),
    (
        "dermo-cosmetique",
        "La Roche-Posay",
        "Anthelios SPF 50+",
        {"skin": "Tous"},
        [({"volume": "50 ml"}, 750, 580)],
    ),
    (
        "bebe",
        "Pampers",
        "Couches Baby-Dry",
        {},
        [({"size": "Taille 3"}, 480, 370), ({"size": "Taille 4"}, 520, 400)],
    ),
    (
        "bebe",
        "Nestlé",
        "Lait NAN Optipro 400 g",
        {},
        [({"size": "1er âge"}, 380, 300), ({"size": "2e âge"}, 360, 285)],
    ),
    ("hygiene", "Colgate", "Dentifrice Total", {}, [({"volume": "75 ml"}, 60, 40)]),
    (
        "hygiene",
        "Dettol",
        "Antiseptique liquide",
        {},
        [({"volume": "250 ml"}, 140, 100), ({"volume": "500 ml"}, 240, 175)],
    ),
    ("hygiene", None, "Gel hydroalcoolique", {}, [({"volume": "100 ml"}, 50, 30)]),
    ("autotest", "Omron", "Tensiomètre M2", {"measure": "Tension"}, [({}, 1900, 1450)]),
    ("autotest", "Omron", "Tensiomètre M3 Comfort", {"measure": "Tension"}, [({}, 2600, 2000)]),
    ("autotest", "Accu-Chek", "Glucomètre Instant", {"measure": "Glycémie"}, [({}, 1400, 1050)]),
    ("materiel-soins", "Microlife", "Thermomètre digital", {}, [({}, 180, 120)]),
    ("materiel-soins", None, "Compresses stériles (boîte de 25)", {}, [({}, 60, 35)]),
    # Quincaillerie
    (
        "outillage-electroportatif",
        "Bosch",
        "Perceuse à percussion GSB 13 RE",
        {"power_w": 600, "cordless": False},
        [({}, 2900, 2300)],
    ),
    (
        "outillage-electroportatif",
        "Makita",
        "Meuleuse 115 mm GA4530",
        {"power_w": 720, "cordless": False},
        [({}, 2600, 2050)],
    ),
    (
        "outillage-electroportatif",
        "Ingco",
        "Perceuse visseuse sans fil 20 V",
        {"cordless": True},
        [({}, 2200, 1700)],
    ),
    (
        "outillage-electroportatif",
        "Total",
        "Scie sauteuse 650 W",
        {"power_w": 650, "cordless": False},
        [({}, 1500, 1150)],
    ),
    ("outillage-main", "Stanley", "Marteau de coffreur", {}, [({"size": "500 g"}, 240, 160)]),
    (
        "outillage-main",
        "Stanley",
        "Mètre ruban",
        {},
        [({"size": "5 m"}, 180, 120), ({"size": "8 m"}, 260, 180)],
    ),
    ("outillage-main", "Ingco", "Coffret tournevis", {}, [({"size": "8 pièces"}, 350, 240)]),
    ("outillage-main", "Total", "Pince universelle", {}, [({"size": "200 mm"}, 190, 130)]),
    (
        "plomberie",
        None,
        "Tube PVC pression (barre 4 m)",
        {},
        [
            ({"diameter": "20 mm"}, 110, 75),
            ({"diameter": "32 mm"}, 180, 125),
            ({"diameter": "110 mm"}, 650, 480),
        ],
    ),
    ("plomberie", None, "Robinet mélangeur lavabo", {}, [({}, 950, 680)]),
    ("plomberie", None, "Ruban téflon", {}, [({}, 15, 7)]),
    (
        "electricite",
        None,
        "Câble rigide H07V-U (au mètre)",
        {},
        [({"section": "1,5 mm²"}, 18, 12), ({"section": "2,5 mm²"}, 28, 19)],
        METRE,
    ),
    ("electricite", "Philips", "Ampoule LED 9 W E27", {}, [({}, 75, 45)]),
    ("electricite", "Legrand", "Prise murale 2P+T", {}, [({}, 120, 80)]),
    ("electricite", "Schneider", "Disjoncteur 16 A", {}, [({}, 290, 210)]),
    (
        "peinture",
        "Jotun",
        "Peinture intérieure blanche",
        {"finish": "Mat"},
        [({"volume": "4 L"}, 950, 720), ({"volume": "20 L"}, 3900, 3100)],
    ),
    ("peinture", None, "Rouleau 180 mm", {}, [({}, 120, 75)]),
    ("peinture", None, "Pinceau plat 50 mm", {}, [({}, 45, 25)]),
    ("visserie-fixation", None, "Clous acier (au kg)", {}, [({}, 65, 45)], KILO),
    ("visserie-fixation", None, "Vis à bois 4 x 40 (boîte de 200)", {}, [({}, 140, 90)]),
    ("visserie-fixation", None, "Chevilles 8 mm (boîte de 100)", {}, [({}, 90, 55)]),
    ("materiaux", None, "Ciment CPJ 45 (sac 50 kg)", {}, [({}, 155, 130)]),
    (
        "materiaux",
        None,
        "Fer à béton (barre 12 m)",
        {},
        [({"diameter": "10 mm"}, 290, 245), ({"diameter": "12 mm"}, 410, 350)],
    ),
]

STORES = {
    Trade.APPLIANCES: {
        "name": "El Baraka Électroménager",
        "address": "Avenue Kennedy, Tevragh Zeina",
        "phone": "+22236223344",
        "serial_prefix": "EB",
        "barcode_base": 6291000000000,
        "suppliers": [("Hisense Afrique de l'Ouest", "+22145250011"), ("Gulf Home Trading", "")],
        "customers": [
            ("Mohamed Abdallahi Ould Sidi", "+22236110022"),
            ("Hôtel Al Wafa", "+22245290033"),
            ("Khadijetou Mint Ely", "+22246330044"),
        ],
    },
    Trade.PHARMACY: {
        "name": "Pharmacie Ennour",
        "address": "Carrefour Madrid, Ksar",
        "phone": "+22245256677",
        "serial_prefix": "PN",
        "barcode_base": 6292000000000,
        "suppliers": [
            ("Grossiste Pharma Nouakchott", "+22245251122"),
            ("Dépôt Médical El Amal", ""),
        ],
        "customers": [
            ("Clinique Chiva", "+22245243355"),
            ("Fatimetou Mint Mohamed", "+22236447788"),
            ("Ahmed Salem Ould Boubacar", "+22222119900"),
        ],
    },
    Trade.HARDWARE: {
        "name": "Quincaillerie El Wahda",
        "address": "Route de Rosso, Sebkha",
        "phone": "+22236558899",
        "serial_prefix": "QW",
        "barcode_base": 6293000000000,
        "suppliers": [("Comptoir Matériaux Sebkha", "+22245257788"), ("Outillage Pro Dakar", "")],
        "customers": [
            ("Entreprise BTP Essalam", "+22245334455"),
            ("Sidi Ould Mohamed Lemine", "+22236990011"),
            ("Atelier Menuiserie El Fath", "+22246221133"),
        ],
    },
}

METHODS = ["cash", "cash", "cash", "bankily", "masrvi", "sedad"]


def products_for(trade) -> list[tuple]:
    slugs = {slug for t, slug, *_ in CATEGORIES if t == trade}
    return [row for row in PRODUCTS if row[0] in slugs]


def variant_label(attrs: dict) -> str:
    return " · ".join(str(v) for v in attrs.values())


class Command(BaseCommand):
    help = "Load test stores for Électroménager, Pharmacie and Quincaillerie (catalog + data)."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, help="Email of the stores' owner")
        parser.add_argument("--password", help="Password if the owner account is created")
        parser.add_argument(
            "--trades",
            nargs="+",
            choices=list(STORES),
            default=list(STORES),
            help="Trades to load (default: all three)",
        )

    def handle(self, *args, **options):
        owner, password = self.owner(options["owner"], options["password"])
        for trade in options["trades"]:
            existing = Store.objects.filter(owner=owner, trade=trade).first()
            if existing:
                self.stdout.write(self.style.WARNING(f"{trade}: {existing.name} already exists."))
                continue
            with transaction.atomic():
                variants = self.catalog(trade)
                store = self.shop(owner, trade, variants)
            self.stdout.write(self.style.SUCCESS(f"{trade}: {store.name} ({store.id})"))
        if password:
            self.stdout.write(f"Owner created: {owner.email} / password: {password}")

    def owner(self, email, password):
        user = User.objects.filter(email__iexact=email).first()
        if user:
            return user, None
        password = password or secrets.token_urlsafe(12)
        user = User.objects.create_user(
            email=email,
            password=password,
            full_name=email.split("@")[0],
            email_verified_at=timezone.now(),
        )
        return user, password

    def catalog(self, trade) -> list[tuple]:
        categories = {}
        for order, (t, slug, name, name_ar, serial, warranty, schema) in enumerate(CATEGORIES):
            if t != trade:
                continue
            categories[slug], _ = Category.objects.update_or_create(
                slug=slug,
                defaults={
                    "trade": trade,
                    "name": name,
                    "name_ar": name_ar,
                    "tracks_serial": serial,
                    "default_warranty_months": warranty,
                    "attribute_schema": schema,
                    "sort_order": order,
                },
            )
        variants = []
        barcode = STORES[trade]["barcode_base"]
        for slug, brand_name, name, attrs, rows, *extra in products_for(trade):
            brand = None
            if brand_name:
                brand = Brand.objects.filter(name__iexact=brand_name).first()
                if brand is None:
                    brand = Brand.objects.create(
                        name=brand_name, slug=slugify(brand_name), trades=[trade]
                    )
                elif trade not in brand.trades:
                    brand.trades = [*brand.trades, trade]
                    brand.save(update_fields=["trades", "updated_at"])
            product, _ = Product.objects.get_or_create(
                category=categories[slug], brand=brand, name=name, defaults={"attributes": attrs}
            )
            for variant_attrs, price, cost in rows:
                barcode += 1
                variant, _ = Variant.objects.get_or_create(
                    product=product,
                    name=variant_label(variant_attrs),
                    defaults={"attributes": variant_attrs, "barcode": str(barcode)},
                )
                variants.append((variant, price, cost, extra[0] if extra else None))
        return variants

    def shop(self, owner, trade, variants) -> Store:
        spec = STORES[trade]
        now = timezone.now()
        store = Store.objects.create(
            owner=owner,
            name=spec["name"],
            trade=trade,
            status=StoreStatus.ACTIVE,
            city="Nouakchott",
            address=spec["address"],
            phone=spec["phone"],
            submitted_at=now - timedelta(days=10),
            approved_at=now - timedelta(days=9),
            decided_at=now - timedelta(days=9),
        )
        Membership.objects.create(store=store, user=owner, role=Role.OWNER)
        rng = random.Random(f"{trade}-{store.id}")  # noqa: S311  # nosec B311
        request = SimpleNamespace(
            store=store,
            user=owner,
            store_role=Role.OWNER,
            client_ip=None,
            auth_realm="merchant",
            headers={},
        )
        serials: set[str] = set()

        def serial() -> str:
            while True:
                value = f"{spec['serial_prefix']}{rng.randint(10**9, 10**10 - 1)}"
                if value not in serials:
                    serials.add(value)
                    return value

        with store_context(store.id):
            suppliers = [
                Supplier.objects.create(store=store, name=name, phone=phone)
                for name, phone in spec["suppliers"]
            ]
            customers = [
                Customer.objects.create(store=store, name=name, phone=phone)
                for name, phone in spec["customers"]
            ]

            products, lines = [], []
            for variant, price, cost, quantities in variants:
                category = variant.product.category
                store_product = StoreProduct.objects.create(
                    store=store,
                    variant=variant,
                    sale_price=price,
                    warranty_months=category.default_warranty_months,
                    reorder_level=2 if category.tracks_serial else 10,
                )
                if quantities:
                    quantity = quantities["stock"]
                elif category.tracks_serial:
                    quantity = Decimal(rng.randint(2, 5))
                else:
                    quantity = Decimal(rng.randint(12, 40))
                products.append((store_product, quantities))
                lines.append(
                    {
                        "store_product": store_product,
                        "quantity": quantity,
                        "unit_cost": cost,
                        "serials": (
                            [serial() for _ in range(int(quantity))]
                            if category.tracks_serial
                            else []
                        ),
                    }
                )
            inventory.receive(
                store,
                owner,
                lines=lines,
                supplier=suppliers[0],
                supplier_reference=f"FA-{now:%y%m}-001",
            )

            sales.open_session(store, owner, 5000)
            for day in range(6, -1, -1):
                for _ in range(rng.randint(3, 6)):
                    sale_lines, total = [], 0
                    for product, quantities in rng.sample(products, rng.randint(1, 3)):
                        product.refresh_from_db()
                        quantity = rng.choice(quantities["sell"]) if quantities else Decimal(1)
                        if product.quantity < quantity:
                            continue
                        line = {"store_product": product, "quantity": quantity}
                        if product.tracks_serial:
                            unit = product.serial_units.filter(status="in_stock").first()
                            line["serial"] = unit.serial
                        sale_lines.append(line)
                        total += round(quantity * product.sale_price)
                    if not sale_lines:
                        continue
                    on_credit = rng.random() < 0.15
                    method = rng.choice(METHODS)
                    sale = sales.create_sale(
                        request,
                        lines=sale_lines,
                        payments=[
                            {
                                "method": method,
                                "amount": total // 2 if on_credit else total,
                                "reference": ""
                                if method == "cash"
                                else f"TX{rng.randint(100000, 999999)}",
                            }
                        ],
                        customer=rng.choice(customers) if on_credit else None,
                    )
                    if day:
                        when = now - timedelta(days=day, hours=rng.randint(0, 6))
                        Sale.objects.filter(pk=sale.pk).update(created_at=when)
                        Payment.objects.filter(sale=sale).update(created_at=when)
            sales.record_expense(
                request, category="transport", amount=500, method="cash", note="Livraison"
            )
        return store
