import hashlib
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core import audit
from apps.core.exceptions import ApiError, Conflict, Forbidden
from apps.core.notifications import notify

from .files import sniff
from .models import (
    EDITABLE_ONBOARDING,
    DocumentKind,
    Invitation,
    Membership,
    OwnershipTransfer,
    RolePolicy,
    Store,
    StoreDocument,
    StoreSettings,
    StoreStatus,
    Trade,
)
from .roles import Role

MAX_STORES_IN_REVIEW = 3


@transaction.atomic
def create_store(user: User, **data) -> Store:
    from apps.console.models import PlatformSettings

    if not PlatformSettings.signups_are_open():
        raise Forbidden("signups_closed", "New stores are closed for now.")
    in_review = Store.objects.filter(
        owner=user,
        status__in=[StoreStatus.DRAFT, StoreStatus.PENDING_APPROVAL, StoreStatus.INFO_REQUESTED],
    ).count()
    if in_review >= MAX_STORES_IN_REVIEW:
        raise Conflict("too_many_pending_stores", "Finish the stores already in review first.")
    store = Store.objects.create(owner=user, **data)
    Membership.objects.create(store=store, user=user, role=Role.OWNER)
    return store


def ensure_owner_editing(store: Store, user: User) -> None:
    if store.owner_id != user.id:
        raise Forbidden("permission_denied", "Only the owner can do this.")
    if store.status not in EDITABLE_ONBOARDING:
        raise Conflict(
            "store_not_editable",
            "The store is not in an editable state.",
            extra={"store_status": store.status},
        )


def add_document(store: Store, user: User, kind: str, upload) -> StoreDocument:
    ensure_owner_editing(store, user)
    content_type, ext = sniff(upload)
    doc = StoreDocument(
        store=store,
        kind=kind,
        original_name=upload.name[:255],
        content_type=content_type,
        size=upload.size,
        uploaded_by=user,
    )
    doc.extension = ext
    doc.file.save(upload.name, upload, save=False)
    doc.save()
    return doc


def missing_documents(store: Store) -> list[str]:
    kinds = set(store.documents.values_list("kind", flat=True))
    required = {DocumentKind.STOREFRONT}
    if store.owner.identity_verified_at is None:
        required |= {DocumentKind.ID_FRONT, DocumentKind.ID_BACK}
    if store.trade == Trade.PHARMACY:
        required.add(DocumentKind.PHARMACY_LICENSE)
    return sorted(required - kinds)


@transaction.atomic
def submit_for_review(request, store: Store) -> Store:
    store = Store.objects.select_for_update().get(pk=store.pk)
    ensure_owner_editing(store, request.user)
    missing = missing_documents(store)
    if missing:
        raise ApiError(
            "documents_missing", "Required documents are missing.", extra={"missing": missing}
        )
    store.status = StoreStatus.PENDING_APPROVAL
    store.submitted_at = timezone.now()
    store.save(update_fields=["status", "submitted_at", "updated_at"])
    audit.record(request, "store.submitted", target=store, store=store)
    notify(store.owner, "store_submitted", {"store": store})
    return store


# --- Team -----------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def invite(request, store: Store, *, email: str, role: str) -> Invitation:
    email = email.strip().lower()
    if role == Role.OWNER:
        raise ApiError("invalid_role", "Use an ownership transfer to change the owner.")
    if Membership.objects.filter(store=store, user__email__iexact=email, is_active=True).exists():
        raise Conflict("already_member", "This person is already in the team.")
    Invitation.objects.filter(
        store=store, email=email, accepted_at__isnull=True, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        store=store,
        email=email,
        role=role,
        token_hash=_hash(token),
        invited_by=request.user,
        expires_at=timezone.now() + settings.INVITATION_TTL,
    )
    audit.record(request, "member.invited", target=invitation, store=store, email=email, role=role)
    notify(
        email,
        "invitation",
        {
            "store": store,
            "role": invitation.get_role_display(),
            "inviter": request.user,
            "link": f"{settings.WEB_APP_URL}/invitations/{token}",
        },
    )
    return invitation


def invitation_by_token(token: str) -> Invitation:
    invitation = (
        Invitation.objects.select_related("store", "invited_by")
        .filter(token_hash=_hash(token))
        .first()
    )
    if invitation is None:
        raise ApiError("invitation_invalid", "This invitation does not exist.", status_code=404)
    return invitation


@transaction.atomic
def accept_invitation(request, invitation: Invitation) -> Membership:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.revoked_at or invitation.accepted_at or invitation.expires_at <= timezone.now():
        raise Conflict("invitation_invalid", "This invitation is no longer valid.")
    if invitation.email.lower() != request.user.email.lower():
        raise Forbidden(
            "invitation_wrong_account", "This invitation was sent to another email address."
        )
    membership, _ = Membership.objects.update_or_create(
        store=invitation.store,
        user=request.user,
        defaults={"role": invitation.role, "is_active": True},
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    audit.record(request, "member.joined", target=membership, store=invitation.store)
    return membership


@transaction.atomic
def change_role(request, membership: Membership, role: str) -> Membership:
    if membership.role == Role.OWNER or role == Role.OWNER:
        raise ApiError("invalid_role", "Use an ownership transfer to change the owner.")
    old = membership.role
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    audit.record(
        request, "member.role_changed", target=membership, store=membership.store, old=old, new=role
    )
    return membership


@transaction.atomic
def remove_member(request, membership: Membership) -> None:
    if membership.role == Role.OWNER:
        raise ApiError("invalid_role", "The owner cannot be removed.")
    membership.is_active = False
    membership.save(update_fields=["is_active", "updated_at"])
    audit.record(request, "member.removed", target=membership, store=membership.store)


@transaction.atomic
def request_ownership_transfer(request, store: Store, to_user_id) -> OwnershipTransfer:
    if store.owner_id != request.user.id:
        raise Forbidden("permission_denied", "Only the owner can transfer the store.")
    target = Membership.objects.filter(store=store, user_id=to_user_id, is_active=True).first()
    if target is None or target.role == Role.OWNER:
        raise ApiError("invalid_member", "Choose an active member of the team.")
    OwnershipTransfer.objects.filter(
        store=store, accepted_at__isnull=True, cancelled_at__isnull=True
    ).update(cancelled_at=timezone.now())
    transfer = OwnershipTransfer.objects.create(
        store=store, from_user=request.user, to_user=target.user
    )
    audit.record(request, "store.ownership_transfer_requested", target=transfer, store=store)
    notify(target.user, "ownership_transfer", {"store": store, "from_user": request.user})
    return transfer


@transaction.atomic
def accept_ownership_transfer(request, transfer: OwnershipTransfer) -> Store:
    transfer = (
        OwnershipTransfer.objects.select_for_update().select_related("store").get(pk=transfer.pk)
    )
    if transfer.to_user_id != request.user.id or transfer.accepted_at or transfer.cancelled_at:
        raise Conflict("transfer_invalid", "This transfer is no longer valid.")
    store = Store.objects.select_for_update().get(pk=transfer.store_id)
    if store.owner_id != transfer.from_user_id:
        raise Conflict("transfer_invalid", "This transfer is no longer valid.")
    Membership.objects.filter(store=store, role=Role.OWNER).update(role=Role.MANAGER)
    try:
        Membership.objects.filter(store=store, user=request.user).update(
            role=Role.OWNER, is_active=True
        )
    except IntegrityError as exc:  # pragma: no cover — guarded by the update above
        raise Conflict("transfer_invalid", "Could not transfer.") from exc
    store.owner = request.user
    store.save(update_fields=["owner", "updated_at"])
    transfer.accepted_at = timezone.now()
    transfer.save(update_fields=["accepted_at"])
    audit.record(
        request,
        "store.ownership_transferred",
        target=store,
        store=store,
        from_user=str(transfer.from_user_id),
    )
    return store


# ---------------------------------------------------------------- store preferences


def store_settings(store: Store) -> StoreSettings:
    """The store's preferences (one row, created with the defaults on first read)."""
    settings_row, _ = StoreSettings.objects.get_or_create(store=store)
    return settings_row


def update_settings(store: Store, **fields) -> StoreSettings:
    row = store_settings(store)
    for name, value in fields.items():
        setattr(row, name, value)
    row.save()
    return row


POLICY_ROLES = [Role.MANAGER, Role.CASHIER, Role.SELLER, Role.STOCK_KEEPER]


def role_policy_defaults(store: Store, role: str) -> dict:
    """What a role may do when the owner hasn't set anything: managers decide, the
    till staff stay within the store's discount cap, stock keepers don't sell."""
    selling = role in (Role.CASHIER, Role.SELLER)
    return {
        "max_discount_percent": None
        if role == Role.MANAGER
        else (store.max_discount_percent if selling else 0),
        "credit_limit": None if role == Role.MANAGER else 0,
        "void_window_minutes": None if role == Role.MANAGER else (30 if selling else 0),
        "cash_tolerance": 0 if role != Role.STOCK_KEEPER else None,
        "see_other_stores_stock": role in (Role.MANAGER, Role.STOCK_KEEPER),
        "see_daily_takings": role == Role.MANAGER,
    }


def role_policies(store: Store) -> list[dict]:
    saved = {policy.role: policy for policy in RolePolicy.objects.all()}
    rows = []
    for role in POLICY_ROLES:
        values = role_policy_defaults(store, role)
        if role in saved:
            values = {name: getattr(saved[role], name) for name in values}
        rows.append({"role": role, **values})
    return rows


def update_role_policy(store: Store, role: str, **fields) -> dict:
    if role not in POLICY_ROLES:
        raise ApiError("invalid_role", "No policy for this role.", status_code=404)
    policy, _ = RolePolicy.objects.get_or_create(
        store=store, role=role, defaults=role_policy_defaults(store, role)
    )
    for name, value in fields.items():
        setattr(policy, name, value)
    policy.save()
    return next(row for row in role_policies(store) if row["role"] == role)
