"""Entry point of every store-scoped request (`/api/v1/stores/{store_id}/…`).

`StoreAccess` checks that the user may act on the store, then activates PostgreSQL
row-level security for it. Views declare what they need with `required_permissions`
({action or HTTP method: permission}); a missing entry means "member of the store".
"""

from rest_framework.exceptions import NotFound
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.exceptions import Forbidden
from apps.core.tenancy import activate_store

from .models import READ_ONLY_STATUSES, Membership, Store, StoreStatus
from .roles import ROLE_PERMISSIONS, Role


def store_for_request(request, store_id) -> tuple[Store, str]:
    """Returns (store, role) or raises 404 — a store you cannot access does not exist."""
    store = Store.objects.filter(pk=store_id).first()
    if store is None:
        raise NotFound()
    session = getattr(request, "user_session", None)
    if session is not None and session.impersonator_id:
        if session.impersonated_store_id != store.id:
            raise NotFound()
        return store, Role.OWNER
    membership = Membership.objects.filter(store=store, user=request.user, is_active=True).first()
    if membership is None:
        raise NotFound()
    return store, membership.role


def required_permission(view, request) -> str | None:
    mapping = getattr(view, "required_permissions", {}) or {}
    action = getattr(view, "action", None)
    return mapping.get(action) or mapping.get(request.method) or mapping.get("*")


class StoreAccess(BasePermission):
    def has_permission(self, request, view):
        store, role = store_for_request(request, view.kwargs["store_id"])
        if store.status in READ_ONLY_STATUSES:
            if request.method not in SAFE_METHODS:
                raise Forbidden(
                    "store_read_only",
                    "This store is read-only.",
                    extra={"store_status": store.status},
                )
        elif store.status != StoreStatus.ACTIVE:
            raise Forbidden(
                "store_not_active",
                "This store is not active yet.",
                extra={"store_status": store.status},
            )
        needed = required_permission(view, request)
        if needed and needed not in ROLE_PERMISSIONS[role]:
            raise Forbidden(
                "permission_denied", f"Missing permission {needed}.", extra={"permission": needed}
            )
        request.store = store
        request.store_role = role
        activate_store(store.id)
        return True


def has_perm(request, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(getattr(request, "store_role", ""), ())


class StoreScopedViewMixin:
    """Mixin for store-scoped views. `self.store` is the current store."""

    store_permission_classes = [StoreAccess]
    required_permissions: dict[str, str] = {}

    def get_permissions(self):
        return [*super().get_permissions(), *(p() for p in self.store_permission_classes)]

    @property
    def store(self) -> Store | None:
        # None only while drf-spectacular builds the schema (no real request)
        return getattr(self.request, "store", None)
