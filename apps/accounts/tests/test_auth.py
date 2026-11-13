import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from conftest import make_user

pytestmark = pytest.mark.django_db
PASSWORD = "Tres-long-mot-de-passe-2026"


def code_from_last_email() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def test_register_verify_and_use_the_api(django_capture_on_commit_callbacks):
    client = APIClient()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/v1/auth/register",
            {"email": "Aicha@Example.com", "password": PASSWORD, "full_name": "Aïcha"},
        )
    assert response.status_code == 202
    user = User.objects.get(email="aicha@example.com")
    assert not user.is_email_verified

    response = client.post(
        "/api/v1/auth/verify-email",
        {"email": "aicha@example.com", "code": code_from_last_email()},
    )
    assert response.status_code == 200, response.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.data["email"] == "aicha@example.com"
    assert me.data["email_verified"] is True


def test_register_with_taken_email_looks_the_same(django_capture_on_commit_callbacks):
    make_user("taken@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        response = APIClient().post(
            "/api/v1/auth/register",
            {"email": "taken@example.com", "password": PASSWORD, "full_name": "X"},
        )
    assert response.status_code == 202
    assert "déjà un compte" in mail.outbox[-1].body


def test_wrong_code_counts_attempts(django_capture_on_commit_callbacks):
    client = APIClient()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            "/api/v1/auth/register",
            {"email": "x@example.com", "password": PASSWORD, "full_name": "X"},
        )
    response = client.post(
        "/api/v1/auth/verify-email", {"email": "x@example.com", "code": "000000"}
    )
    if code_from_last_email() == "000000":
        pytest.skip("random code collided")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_code"
    assert response.data["attempts_left"] == 2
    assert response["Content-Type"] == "application/problem+json"


def test_login_errors_and_unverified_email():
    make_user("ok@example.com")
    make_user("new@example.com", email_verified_at=None)
    client = APIClient()
    wrong = client.post("/api/v1/auth/login", {"email": "ok@example.com", "password": "nope"})
    assert wrong.status_code == 401
    assert wrong.data["code"] == "invalid_credentials"
    unverified = client.post(
        "/api/v1/auth/login", {"email": "new@example.com", "password": "Very-secret-pass-42"}
    )
    assert unverified.data["code"] == "email_not_verified"


@pytest.mark.django_db(transaction=True)  # real commits: the revocation must survive the 401
def test_refresh_rotates_and_reuse_kills_the_session():
    make_user("ok@example.com")
    client = APIClient()
    tokens = client.post(
        "/api/v1/auth/login", {"email": "ok@example.com", "password": "Very-secret-pass-42"}
    ).data
    rotated = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]})
    assert rotated.status_code == 200
    assert rotated.data["refresh"] != tokens["refresh"]

    reused = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]})
    assert reused.status_code == 401
    assert UserSession.objects.get().revoked_at is not None
    # the stolen session's newest token is dead too
    again = client.post("/api/v1/auth/refresh", {"refresh": rotated.data["refresh"]})
    assert again.status_code == 401


def test_revoked_session_blocks_access_token_immediately():
    make_user("ok@example.com")
    client = APIClient()
    tokens = client.post(
        "/api/v1/auth/login", {"email": "ok@example.com", "password": "Very-secret-pass-42"}
    ).data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    session_id = client.get("/api/v1/me/sessions").data[0]["id"]
    assert client.delete(f"/api/v1/me/sessions/{session_id}").status_code == 204
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.data["code"] == "session_revoked"


def test_console_token_is_refused_by_merchant_api(staff_client):
    response = staff_client.get("/api/v1/me")
    assert response.status_code == 401


def test_merchant_cannot_log_into_console():
    make_user("ok@example.com")
    response = APIClient().post(
        "/api/v1/console/auth/login",
        {"email": "ok@example.com", "password": "Very-secret-pass-42"},
    )
    assert response.status_code == 401
