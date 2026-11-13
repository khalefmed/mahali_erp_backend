import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.accounts.tokens import issue_tokens
from apps.catalog.models import Brand, Category, Product, Variant
from apps.console.models import PlatformStaff
from apps.stores.models import Membership, Store, StoreStatus, Trade
from apps.stores.roles import Role

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.PWNED_PASSWORDS_CHECK = False
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }
    from django.core.cache import cache

    cache.clear()


def make_user(email="owner@example.com", **extra) -> User:
    extra.setdefault("full_name", email.split("@")[0].title())
    extra.setdefault("email_verified_at", timezone.now())
    return User.objects.create_user(email=email, password="Very-secret-pass-42", **extra)


def client_for(user, realm=UserSession.Realm.MERCHANT) -> APIClient:
    session = UserSession.objects.create(user=user, realm=realm)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, session)['access']}")
    return client


def make_store(owner, *, name="Tel Plus", status=StoreStatus.ACTIVE, trade=Trade.TELEPHONES):
    store = Store.objects.create(
        owner=owner, name=name, trade=trade, city="Nouakchott", status=status
    )
    Membership.objects.create(store=store, user=owner, role=Role.OWNER)
    return store


def add_member(store, role, email):
    user = make_user(email)
    Membership.objects.create(store=store, user=user, role=role)
    return user


@pytest.fixture
def owner(db):
    return make_user()


@pytest.fixture
def store(owner):
    return make_store(owner)


@pytest.fixture
def owner_client(owner):
    return client_for(owner)


@pytest.fixture
def staff_client(db):
    user = make_user("ops@mahali.mr")
    PlatformStaff.objects.create(user=user, role="super_admin")
    return client_for(user, UserSession.Realm.CONSOLE)


@pytest.fixture
def phone_variant(db):
    category = Category.objects.create(
        trade=Trade.TELEPHONES,
        name="Smartphones",
        slug="smartphones",
        tracks_serial=True,
        default_warranty_months=12,
        attribute_schema=[
            {
                "key": "storage",
                "label": "Stockage",
                "type": "choice",
                "level": "variant",
                "options": ["128 Go", "256 Go"],
                "required": True,
            },
        ],
    )
    brand = Brand.objects.create(name="Samsung", slug="samsung")
    product = Product.objects.create(category=category, brand=brand, name="Galaxy A55")
    return Variant.objects.create(
        product=product, name="128 Go", attributes={"storage": "128 Go"}, barcode="880000000001"
    )


@pytest.fixture
def earbuds_variant(db):
    category = Category.objects.create(
        trade=Trade.TELEPHONES, name="Écouteurs", slug="ecouteurs", tracks_serial=False
    )
    product = Product.objects.create(category=category, name="Écouteurs filaires")
    return Variant.objects.create(product=product, name="Blanc", barcode="880000000002")


def api(store, path):
    return f"/api/v1/stores/{store.id}/{path}"
