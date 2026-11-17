"""Shoppers' e-KYC, required before Meysara (BCM Instruction n°13/GR/2025, chapter II).

1. `start`: identity details (NNI, names, birth date, phone) and explicit consent. A
   one-time code goes to the phone (art. 4: phone ownership by OTP).
2. `verify_phone`: the code (10 min, 3 attempts).
3. `check_documents`: photos of the ID card (front, and back when the app sends it) and a
   selfie taken live. The provider checks the document (the back carries the MRZ), matches
   the face and runs a liveness check; the images are then dropped, never stored
   (law n°2017-020: keep only what is needed).

There is no identity provider yet: `SimulatedProvider` stands in for it. It sends no SMS
(the code is logged and returned to the app as `simulation_code`) and approves every
document, except the test NNIs starting with `000`, which it rejects. A real provider
replaces it behind the same three methods.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ApiError, Conflict
from apps.stores.files import sniff

from .models import IdentityStatus, IdentityVerification

logger = logging.getLogger(__name__)

NNI = re.compile(r"^\d{10}$")
PHONE = re.compile(r"^\+222[234]\d{7}$")
ADULT_AGE = 18
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass
class DocumentResult:
    approved: bool
    reference: str
    checks: dict
    reason: str = ""


class SimulatedProvider:
    """Stand-in for a real e-KYC provider. Same interface, no network, always quick."""

    name = "simulated"

    def send_code(self, phone: str, code: str) -> None:
        logger.info("kyc: simulated SMS to %s, code %s", phone, code)

    def check_documents(self, verification: IdentityVerification, id_front, selfie, id_back=None):
        reference = f"SIM-{uuid.uuid4().hex[:12].upper()}"
        if verification.nni.startswith("000"):
            checks = {"document": "failed", "face_match": None, "liveness": "not_run"}
            return DocumentResult(False, reference, checks, "document_unreadable")
        checks = {"document": "passed", "face_match": 0.97, "liveness": "passed"}
        return DocumentResult(True, reference, checks)


provider = SimulatedProvider()


def age_on(birth_date: date, today: date) -> int:
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - before_birthday


def is_verified(customer) -> bool:
    return IdentityVerification.objects.filter(
        customer=customer, status=IdentityStatus.VERIFIED
    ).exists()


def verified_identity(customer) -> IdentityVerification | None:
    """The identity the shopper proved, as named in a Meysara contract."""
    return IdentityVerification.objects.filter(
        customer=customer, status=IdentityStatus.VERIFIED
    ).first()


def _send_code(verification: IdentityVerification) -> str:
    code = f"{secrets.randbelow(10**6):06d}"
    verification.otp_hash = make_password(code)
    verification.otp_expires_at = timezone.now() + settings.KYC_OTP_TTL
    verification.otp_attempts = 0
    provider.send_code(verification.phone, code)
    return code


@transaction.atomic
def start(
    customer,
    *,
    nni: str,
    first_name: str,
    last_name: str,
    birth_date: date,
    phone: str,
    consent: bool,
) -> tuple[IdentityVerification, str]:
    """Starts (or restarts) the e-KYC and sends the phone code. Returns the code too, for the
    simulated provider only."""
    if not consent:
        raise ApiError("consent_required", "Consent is required.", extra={"field": "consent"})
    if not NNI.match(nni):
        raise ApiError("invalid_nni", "The NNI has 10 digits.", extra={"field": "nni"})
    if not PHONE.match(phone):
        raise ApiError(
            "invalid_phone",
            "A Mauritanian mobile number: +222 and 8 digits.",
            extra={"field": "phone"},
        )
    if age_on(birth_date, timezone.localdate()) < ADULT_AGE:
        raise ApiError("underage", "Meysara is for adults only.", extra={"field": "birth_date"})
    current = IdentityVerification.objects.select_for_update().filter(customer=customer).first()
    if current and current.is_verified:
        raise Conflict("identity_already_verified", "This identity is already verified.")
    taken = (
        IdentityVerification.objects.filter(nni=nni, status=IdentityStatus.VERIFIED)
        .exclude(customer=customer)
        .exists()
    )
    if taken:
        raise Conflict(
            "nni_already_used", "This NNI is linked to another account.", extra={"field": "nni"}
        )
    verification = current or IdentityVerification(customer=customer)
    verification.status = IdentityStatus.PHONE_PENDING
    verification.nni = nni
    verification.first_name = first_name.strip()
    verification.last_name = last_name.strip()
    verification.birth_date = birth_date
    verification.phone = phone
    verification.consent_at = timezone.now()
    verification.phone_verified_at = None
    verification.provider = provider.name
    verification.provider_reference = ""
    verification.checks = {}
    verification.reject_reason = ""
    code = _send_code(verification)
    verification.save()
    return verification, code


def _current(customer, *, for_update: bool = False) -> IdentityVerification:
    rows = IdentityVerification.objects.filter(customer=customer)
    verification = (rows.select_for_update() if for_update else rows).first()
    if verification is None:
        raise ApiError("identity_not_started", "Start the identity check first.")
    return verification


def verify_phone(customer, code: str) -> IdentityVerification:
    # The view runs outside the request transaction: a wrong code is committed with its
    # count, and the error is raised after the commit.
    with transaction.atomic():
        verification = _current(customer, for_update=True)
        if verification.status != IdentityStatus.PHONE_PENDING:
            raise Conflict(
                "identity_step_done",
                "The phone is already verified.",
                extra={"status": verification.status},
            )
        expired = not verification.otp_expires_at or verification.otp_expires_at <= timezone.now()
        if expired or verification.otp_attempts >= settings.KYC_OTP_MAX_ATTEMPTS:
            raise ApiError("code_expired", "The code has expired. Ask for a new one.")
        wrong = not check_password(code, verification.otp_hash)
        if wrong:
            verification.otp_attempts += 1
            verification.save(update_fields=["otp_attempts", "updated_at"])
        else:
            verification.status = IdentityStatus.DOCUMENTS_PENDING
            verification.phone_verified_at = timezone.now()
            verification.otp_hash = ""
            verification.otp_expires_at = None
            verification.save(
                update_fields=[
                    "status",
                    "phone_verified_at",
                    "otp_hash",
                    "otp_expires_at",
                    "updated_at",
                ]
            )
    if wrong:
        remaining = settings.KYC_OTP_MAX_ATTEMPTS - verification.otp_attempts
        raise ApiError("invalid_code", "Wrong code.", extra={"attempts_left": remaining})
    return verification


@transaction.atomic
def resend_code(customer) -> tuple[IdentityVerification, str]:
    verification = _current(customer, for_update=True)
    if verification.status != IdentityStatus.PHONE_PENDING:
        raise Conflict(
            "identity_step_done",
            "The phone is already verified.",
            extra={"status": verification.status},
        )
    code = _send_code(verification)
    verification.save(update_fields=["otp_hash", "otp_expires_at", "otp_attempts", "updated_at"])
    return verification, code


def _image(upload, field: str):
    content_type, _ = sniff(upload)
    if content_type not in IMAGE_TYPES:
        raise ApiError(
            "unsupported_file_type",
            "A photo is required: JPEG, PNG or WebP.",
            extra={"field": field},
        )
    return upload


@transaction.atomic
def check_documents(customer, *, id_front, selfie, id_back=None) -> IdentityVerification:
    """The provider decides; a rejection can be retried from `start`."""
    verification = _current(customer, for_update=True)
    if verification.status != IdentityStatus.DOCUMENTS_PENDING:
        raise Conflict(
            "identity_wrong_step",
            "Verify the phone first.",
            extra={"status": verification.status},
        )
    result = provider.check_documents(
        verification,
        _image(id_front, "id_front"),
        _image(selfie, "selfie"),
        id_back=_image(id_back, "id_back") if id_back else None,
    )
    verification.provider_reference = result.reference
    verification.checks = result.checks
    if result.approved:
        verification.status = IdentityStatus.VERIFIED
        verification.verified_at = timezone.now()
    else:
        verification.status = IdentityStatus.REJECTED
        verification.reject_reason = result.reason
    try:
        with transaction.atomic():
            verification.save()
    except IntegrityError:  # another account verified this NNI meanwhile
        raise Conflict(
            "nni_already_used", "This NNI is linked to another account.", extra={"field": "nni"}
        ) from None
    return verification
