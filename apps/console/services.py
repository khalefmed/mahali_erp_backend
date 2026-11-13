from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import User, UserSession
from apps.accounts.services import revoke_all_sessions
from apps.accounts.tokens import issue_impersonation_token
from apps.core import audit
from apps.core.exceptions import ApiError, Conflict
from apps.core.notifications import notify
from apps.stores.models import Store, StoreStatus

from .models import PlatformStaff


def _decide(
    request, store: Store, *, allowed_from: set, to: str, message: str, action: str, template: str
) -> Store:
    store = Store.objects.select_for_update().select_related("owner").get(pk=store.pk)
    if store.status not in allowed_from:
        raise Conflict(
            "invalid_store_status",
            f"Store is {store.status}.",
            extra={"store_status": store.status},
        )
    store.status = to
    store.decided_at = timezone.now()
    store.decided_by = request.user
    store.decision_message = message
    if to == StoreStatus.ACTIVE and store.approved_at is None:
        store.approved_at = timezone.now()
    store.save()
    audit.record(request, action, target=store, store=store, reason=message)
    notify(store.owner, template, {"store": store, "message": message})
    return store


@transaction.atomic
def approve(request, store: Store, message: str = "") -> Store:
    store = _decide(
        request,
        store,
        allowed_from={StoreStatus.PENDING_APPROVAL},
        to=StoreStatus.ACTIVE,
        message=message,
        action="store.approved",
        template="store_approved",
    )
    if store.owner.identity_verified_at is None:
        store.owner.identity_verified_at = timezone.now()
        store.owner.save(update_fields=["identity_verified_at"])
    return store


@transaction.atomic
def request_info(request, store: Store, message: str) -> Store:
    return _decide(
        request,
        store,
        allowed_from={StoreStatus.PENDING_APPROVAL},
        to=StoreStatus.INFO_REQUESTED,
        message=message,
        action="store.info_requested",
        template="store_info_requested",
    )


@transaction.atomic
def reject(request, store: Store, message: str) -> Store:
    return _decide(
        request,
        store,
        allowed_from={StoreStatus.PENDING_APPROVAL, StoreStatus.INFO_REQUESTED},
        to=StoreStatus.REJECTED,
        message=message,
        action="store.rejected",
        template="store_rejected",
    )


@transaction.atomic
def suspend(request, store: Store, reason: str) -> Store:
    return _decide(
        request,
        store,
        allowed_from={StoreStatus.ACTIVE},
        to=StoreStatus.SUSPENDED,
        message=reason,
        action="store.suspended",
        template="store_suspended",
    )


@transaction.atomic
def reactivate(request, store: Store, reason: str) -> Store:
    return _decide(
        request,
        store,
        allowed_from={StoreStatus.SUSPENDED},
        to=StoreStatus.ACTIVE,
        message=reason,
        action="store.reactivated",
        template="store_reactivated",
    )


@transaction.atomic
def impersonate(request, store: Store, reason: str) -> dict:
    """Read-only session as the store owner, 30 minutes. The owner is told by email."""
    if not reason.strip():
        raise ApiError("reason_required", "Give a reason.")
    session = UserSession.objects.create(
        user=store.owner,
        realm=UserSession.Realm.MERCHANT,
        user_agent=request.headers.get("User-Agent", "")[:300],
        ip_address=getattr(request, "client_ip", None),
        impersonator=request.user,
        impersonated_store=store,
        expires_at=timezone.now() + settings.IMPERSONATION_TTL,
    )
    audit.record(
        request,
        "store.impersonated",
        target=store,
        store=store,
        reason=reason,
        session=str(session.id),
    )
    notify(store.owner, "store_impersonated", {"store": store, "reason": reason})
    return issue_impersonation_token(session)


@transaction.atomic
def add_staff(request, *, email: str, full_name: str, role: str) -> PlatformStaff:
    email = email.strip().lower()
    user = User.objects.filter(email__iexact=email).first()
    if user and user.memberships.filter(is_active=True).exists():
        raise Conflict("account_is_merchant", "Use a separate email for Mahali team accounts.")
    if user is None:
        user = User.objects.create_user(
            email=email, password=None, full_name=full_name, email_verified_at=timezone.now()
        )
    staff, created = PlatformStaff.objects.get_or_create(user=user, defaults={"role": role})
    if not created:
        raise Conflict("already_staff", "Already a team member.")
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    link = (
        f"{settings.WEB_APP_URL}/{user.language}/reset-password"
        f"?uid={uid}&token={default_token_generator.make_token(user)}"
    )
    notify(user, "staff_invited", {"user": user, "link": link, "role": staff.get_role_display()})
    audit.record(request, "staff.added", target=staff, email=email, role=role)
    return staff


@transaction.atomic
def update_staff(request, staff: PlatformStaff, **changes) -> PlatformStaff:
    if staff.user_id == request.user.id and changes.get("is_active") is False:
        raise ApiError("cannot_disable_self", "You cannot disable your own account.")
    for key, value in changes.items():
        setattr(staff, key, value)
    staff.save()
    if staff.is_active is False:
        revoke_all_sessions(staff.user)
    audit.record(request, "staff.updated", target=staff, **{k: str(v) for k, v in changes.items()})
    return staff
