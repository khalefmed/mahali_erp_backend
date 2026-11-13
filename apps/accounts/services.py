import contextlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.core.exceptions import ApiError, Forbidden
from apps.core.notifications import notify

from .models import EmailCode, User, UserSession
from .tokens import issue_tokens


def _send_verification_code(user: User) -> None:
    code = f"{secrets.randbelow(10**6):06d}"
    EmailCode.objects.filter(
        user=user, purpose=EmailCode.Purpose.VERIFY_EMAIL, used_at__isnull=True
    ).update(used_at=timezone.now())
    EmailCode.objects.create(
        user=user,
        purpose=EmailCode.Purpose.VERIFY_EMAIL,
        code_hash=make_password(code),
        expires_at=timezone.now() + settings.EMAIL_CODE_TTL,
    )
    notify(
        user,
        "verify_email",
        {"code": code, "user": user, "minutes": int(settings.EMAIL_CODE_TTL.total_seconds() // 60)},
    )


@transaction.atomic
def register(
    *, email: str, password: str, full_name: str, phone: str = "", language: str = "fr"
) -> None:
    """Same response whether or not the email is taken (no account enumeration)."""
    email = email.strip().lower()
    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        if existing.is_email_verified:
            notify(existing, "register_existing", {"user": existing})
        else:
            _send_verification_code(existing)
        return
    user = User(email=email, full_name=full_name.strip(), phone=phone, language=language)
    password_validation.validate_password(password, user)
    user.set_password(password)
    user.save()
    _send_verification_code(user)


def resend_code(email: str) -> None:
    user = User.objects.filter(email__iexact=email.strip(), email_verified_at__isnull=True).first()
    if user:
        _send_verification_code(user)


def _start_session(user: User, request, realm: str) -> dict:
    agent = request.headers.get("User-Agent", "")[:300]
    known_device = UserSession.objects.filter(user=user, realm=realm, user_agent=agent).exists()
    session = UserSession.objects.create(
        user=user, realm=realm, user_agent=agent, ip_address=getattr(request, "client_ip", None)
    )
    if not known_device and UserSession.objects.filter(user=user, realm=realm).count() > 1:
        notify(user, "new_login", {"user": user, "session": session})
    return issue_tokens(user, session)


@transaction.atomic
def verify_email(request, *, email: str, code: str) -> tuple[User, dict]:
    user = User.objects.filter(email__iexact=email.strip()).first()
    record = None
    if user:
        record = (
            EmailCode.objects.select_for_update()
            .filter(user=user, purpose=EmailCode.Purpose.VERIFY_EMAIL, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
    if record is None or record.expires_at <= timezone.now():
        raise ApiError("code_expired", "The code has expired. Ask for a new one.")
    if record.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
        raise ApiError("code_expired", "Too many attempts. Ask for a new code.")
    if not check_password(code, record.code_hash):
        record.attempts += 1
        record.save(update_fields=["attempts"])
        remaining = settings.EMAIL_CODE_MAX_ATTEMPTS - record.attempts
        raise ApiError("invalid_code", "Wrong code.", extra={"attempts_left": remaining})
    record.used_at = timezone.now()
    record.save(update_fields=["used_at"])
    if not user.is_email_verified:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
    return user, _start_session(user, request, UserSession.Realm.MERCHANT)


def login(request, *, email: str, password: str, realm: str) -> tuple[User, dict]:
    user = authenticate(request, username=email.strip().lower(), password=password)
    if user is None:
        raise ApiError("invalid_credentials", "Email or password is incorrect.", status_code=401)
    if realm == UserSession.Realm.MERCHANT and not user.is_email_verified:
        raise Forbidden("email_not_verified", "Verify your email first.")
    if realm == UserSession.Realm.CONSOLE:
        staff = getattr(user, "platform_staff", None)
        if staff is None or not staff.is_active:
            raise ApiError(
                "invalid_credentials", "Email or password is incorrect.", status_code=401
            )
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return user, _start_session(user, request, realm)


def revoke_all_sessions(user: User, *, except_session_id=None) -> None:
    sessions = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_session_id:
        sessions = sessions.exclude(id=except_session_id)
    sessions.update(revoked_at=timezone.now())


def request_password_reset(email: str) -> None:
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if not user:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.WEB_APP_URL}/{user.language}/reset-password?uid={uid}&token={token}"
    notify(
        user,
        "password_reset",
        {"user": user, "link": link, "minutes": settings.PASSWORD_RESET_TIMEOUT // 60},
    )


@transaction.atomic
def reset_password(*, uid: str, token: str, password: str) -> None:
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        raise ApiError("invalid_reset_link", "This link is invalid or has expired.")
    password_validation.validate_password(password, user)
    user.set_password(password)
    # A reset link proves access to the mailbox, so the email is verified.
    user.email_verified_at = user.email_verified_at or timezone.now()
    user.save(update_fields=["password", "email_verified_at"])
    revoke_all_sessions(user)
    notify(user, "password_changed", {"user": user})


@transaction.atomic
def change_password(user: User, *, current: str, new: str, session_id) -> None:
    if not user.check_password(current):
        raise ApiError("invalid_credentials", "Current password is incorrect.")
    password_validation.validate_password(new, user)
    user.set_password(new)
    user.save(update_fields=["password"])
    revoke_all_sessions(user, except_session_id=session_id)
    notify(user, "password_changed", {"user": user})


def session_cutoff():
    return timezone.now() - timedelta(days=30)


def refresh_tokens(raw: str) -> dict:
    """Rotate a refresh token. Reusing an already-rotated token is treated as theft:
    the whole session is revoked. Called outside the request transaction (see RefreshView)
    so that this revocation is committed even though the call then fails."""
    from rest_framework_simplejwt.exceptions import TokenBackendError, TokenError
    from rest_framework_simplejwt.state import token_backend
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    from rest_framework_simplejwt.tokens import RefreshToken

    try:
        token = RefreshToken(raw)
    except TokenError:
        try:
            payload = token_backend.decode(raw, verify=True)
        except TokenBackendError:
            payload = None
        if payload and BlacklistedToken.objects.filter(token__jti=payload.get("jti")).exists():
            UserSession.objects.filter(id=payload.get("sid"), revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
        raise ApiError(
            "token_not_valid", "Refresh token is invalid or expired.", status_code=401
        ) from None
    with transaction.atomic():
        session = UserSession.objects.select_related("user").filter(id=token.get("sid")).first()
        if session is None or not session.is_active or not session.user.is_active:
            raise ApiError("session_revoked", "Session ended.", status_code=401)
        token.blacklist()
        session.last_seen_at = timezone.now()
        session.save(update_fields=["last_seen_at"])
        return issue_tokens(session.user, session)


def logout(raw_refresh: str | None, session: UserSession | None) -> None:
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken

    if raw_refresh:
        with contextlib.suppress(TokenError):
            RefreshToken(raw_refresh).blacklist()
    if session:
        session.revoke()
