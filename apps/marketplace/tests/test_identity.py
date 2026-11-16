"""Shoppers' e-KYC (simulated provider) and the BCM ceilings on Meysara
(BCM Instruction n°13/GR/2025: chapter II and art. 25)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import UserSession
from apps.console.models import PlatformSettings
from apps.marketplace import meysara
from apps.marketplace.models import IdentityStatus, IdentityVerification
from conftest import client_for, make_user

from .helpers import PUBLIC, verify_identity

pytestmark = pytest.mark.django_db
IDENTITY = f"{PUBLIC}/identity"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def details(**over):
    return {
        "nni": "2012345678",
        "first_name": "Aicha",
        "last_name": "Mint Ahmed",
        "birth_date": "1995-03-14",
        "phone": "+22236000000",
        "consent": True,
        **over,
    }


def photo(name="photo.jpg", content=JPEG):
    return SimpleUploadedFile(name, content, content_type="image/jpeg")


def send_documents(client):
    return client.post(
        f"{IDENTITY}/documents",
        {"id_front": photo("id.jpg"), "selfie": photo("selfie.jpg")},
        format="multipart",
    )


def start(client, **over):
    return client.post(IDENTITY, details(**over), format="json")


# ---------------------------------------------------------------- the three steps


def test_full_check_verifies_the_shopper_and_keeps_no_photo(shopper, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user, client = shopper
    empty = client.get(IDENTITY)
    assert empty.status_code == 200
    assert empty.data == {"identity": None, "simulation_code": None}

    started = start(client)
    assert started.status_code == 200, started.data
    code = started.data["simulation_code"]
    assert len(code) == 6
    identity = started.data["identity"]
    assert identity["status"] == "phone_pending"
    assert identity["nni"] == "••••••5678"  # masked
    assert identity["phone"] == "+222 •• •• •• 00"
    assert identity["simulation"] is True

    phone = client.post(f"{IDENTITY}/phone/verify", {"code": code}, format="json")
    assert phone.status_code == 200, phone.data
    assert phone.data["identity"]["status"] == "documents_pending"

    done = send_documents(client)
    assert done.status_code == 200, done.data
    result = done.data["identity"]
    assert result["status"] == "verified"
    assert result["checks"] == {"document": "passed", "face_match": 0.97, "liveness": "passed"}
    assert result["verified_at"]
    assert list(tmp_path.rglob("*")) == []  # photos checked, then dropped

    assert meysara.offer(user, 5000).identity_verified is True


def test_simulator_rejects_test_nnis_and_the_shopper_can_start_again(shopper):
    _, client = shopper
    code = start(client, nni="0001234567").data["simulation_code"]
    client.post(f"{IDENTITY}/phone/verify", {"code": code}, format="json")
    rejected = send_documents(client).data["identity"]
    assert (rejected["status"], rejected["reject_reason"]) == ("rejected", "document_unreadable")

    again = start(client)
    assert again.data["identity"]["status"] == "phone_pending"
    assert again.data["identity"]["reject_reason"] == ""


@pytest.mark.parametrize(
    ("over", "code", "field"),
    [
        ({"consent": False}, "consent_required", "consent"),
        ({"nni": "12345"}, "invalid_nni", "nni"),
        ({"phone": "+33612345678"}, "invalid_phone", "phone"),
        ({"phone": "+22216000000"}, "invalid_phone", "phone"),  # landline
    ],
)
def test_start_checks_the_details(shopper, over, code, field):
    _, client = shopper
    response = start(client, **over)
    assert (response.status_code, response.data["code"], response.data["field"]) == (
        400,
        code,
        field,
    )
    assert not IdentityVerification.objects.exists()


def test_meysara_is_for_adults_only(shopper):
    _, client = shopper
    today = timezone.localdate()
    minor = today.replace(year=today.year - 18) + timedelta(days=1)
    response = start(client, birth_date=minor.isoformat())
    assert response.data["code"] == "underage"
    adult = today.replace(year=today.year - 18)
    assert start(client, birth_date=adult.isoformat()).status_code == 200


@pytest.mark.django_db(transaction=True)  # real commits, like the API: wrong codes stay counted
def test_wrong_code_counts_attempts_then_expires(shopper):
    _, client = shopper
    code = start(client).data["simulation_code"]
    wrong = "000000" if code != "000000" else "111111"
    first = client.post(f"{IDENTITY}/phone/verify", {"code": wrong}, format="json")
    assert (first.data["code"], first.data["attempts_left"]) == ("invalid_code", 2)
    client.post(f"{IDENTITY}/phone/verify", {"code": wrong}, format="json")
    client.post(f"{IDENTITY}/phone/verify", {"code": wrong}, format="json")
    locked = client.post(f"{IDENTITY}/phone/verify", {"code": code}, format="json")
    assert locked.data["code"] == "code_expired"

    fresh = client.post(f"{IDENTITY}/phone/resend").data["simulation_code"]
    ok = client.post(f"{IDENTITY}/phone/verify", {"code": fresh}, format="json")
    assert ok.data["identity"]["status"] == "documents_pending"


@pytest.mark.django_db(transaction=True)  # real commits, like the API: wrong codes stay counted
def test_code_expires_after_ten_minutes(shopper):
    user, client = shopper
    code = start(client).data["simulation_code"]
    IdentityVerification.objects.filter(customer=user).update(
        otp_expires_at=timezone.now() - timedelta(seconds=1)
    )
    response = client.post(f"{IDENTITY}/phone/verify", {"code": code}, format="json")
    assert response.data["code"] == "code_expired"


@pytest.mark.django_db(transaction=True)  # real commits, like the API: wrong codes stay counted
def test_steps_come_in_order(shopper):
    _, client = shopper
    assert client.post(f"{IDENTITY}/phone/verify", {"code": "123456"}).data["code"] == (
        "identity_not_started"
    )
    start(client)
    early = send_documents(client)
    assert (early.status_code, early.data["code"]) == (409, "identity_wrong_step")


def test_documents_must_be_photos(shopper):
    _, client = shopper
    code = start(client).data["simulation_code"]
    client.post(f"{IDENTITY}/phone/verify", {"code": code}, format="json")
    pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    response = client.post(
        f"{IDENTITY}/documents", {"id_front": pdf, "selfie": photo()}, format="multipart"
    )
    assert (response.data["code"], response.data["field"]) == ("unsupported_file_type", "id_front")


def test_one_nni_one_account(shopper):
    verify_identity(make_user("first@example.com"), nni="2012345678")
    _, client = shopper
    response = start(client)
    assert (response.status_code, response.data["code"]) == (409, "nni_already_used")


def test_a_verified_identity_cannot_be_overwritten(shopper):
    user, client = shopper
    verify_identity(user)
    response = start(client, nni="2099999999")
    assert (response.status_code, response.data["code"]) == (409, "identity_already_verified")


def test_identity_is_for_shoppers_only(owner_client):
    assert owner_client.get(IDENTITY).status_code in (401, 403)


def test_each_shopper_sees_only_their_own_identity(shopper):
    _, client = shopper
    start(client)
    other = client_for(make_user("other@example.com"), UserSession.Realm.CUSTOMER)
    assert other.get(IDENTITY).data["identity"] is None


# ---------------------------------------------------------------- BCM ceilings


def test_the_console_cannot_go_above_the_bcm_ceiling(staff_client):
    above = staff_client.patch("/api/v1/console/settings", {"meysara_max_financed": 60001})
    assert above.status_code == 400
    at = staff_client.patch("/api/v1/console/settings", {"meysara_max_financed": 60000})
    assert at.status_code == 200, at.data


def test_ceiling_never_passes_the_bcm_limit_even_if_stored_higher(db):
    settings = PlatformSettings.load()
    PlatformSettings.objects.filter(pk=settings.pk).update(meysara_max_financed=90000)
    assert meysara.max_financed(PlatformSettings.load()) == 60000


def test_a_share_above_the_ceiling_is_not_offered(margin, shopper, monkeypatch):
    user, _ = shopper
    monkeypatch.setattr(meysara, "paid_orders", lambda customer: 3)
    monkeypatch.setattr(meysara, "max_percent", lambda customer: 100)
    verify_identity(user)
    # 100 000 MRU: 50 % = 50 000 fits, 100 % = 100 000 does not.
    current = meysara.offer(user, 100_000)
    assert (current.eligible, current.choices) == (True, [50])
    # 150 000 MRU: even 50 % (75 000) is above 60 000.
    assert meysara.offer(user, 150_000).reason == "meysara_limit_exceeded"


def test_a_plan_ends_within_twelve_months():
    assert meysara.INSTALMENTS * meysara.INTERVAL_DAYS <= 365


def test_statuses_are_documented():
    assert {s.value for s in IdentityStatus} == {
        "phone_pending",
        "documents_pending",
        "verified",
        "rejected",
    }
