import pytest
from rest_framework.test import APIClient

from apps.console.models import PlatformSettings

pytestmark = pytest.mark.django_db


def test_platform_info_is_public_and_reflects_console(staff_client):
    staff_client.patch("/api/v1/console/settings", {"announcement": "Maintenance ce soir 22 h"})
    info = APIClient().get("/api/v1/platform").data
    assert info == {
        "announcement": "Maintenance ce soir 22 h",
        "signups_open": True,
        "review_sla_hours": 24,
    }


def test_closed_signups_block_registration_and_new_stores(owner_client):
    settings = PlatformSettings.load()
    settings.signups_open = False
    settings.save()
    register = APIClient().post(
        "/api/v1/auth/register",
        {"email": "new@example.com", "password": "Tres-long-mot-de-passe-2026", "full_name": "N"},
    )
    assert register.status_code == 403
    assert register.data["code"] == "signups_closed"
    store = owner_client.post(
        "/api/v1/stores", {"name": "S", "trade": "telephones", "city": "Nouakchott"}
    )
    assert store.data["code"] == "signups_closed"


def test_docs_are_public_and_carry_the_guide():
    client = APIClient()
    schema = client.get("/api/schema/?format=json").json()
    assert "After login: which screen?" in schema["info"]["description"]
    assert client.get("/api/redoc/").status_code == 200
    assert client.get("/").status_code == 302
