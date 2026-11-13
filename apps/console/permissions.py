from rest_framework.permissions import BasePermission

from apps.core.exceptions import Forbidden

from .models import StaffRole

R = StaffRole
CONSOLE_PERMISSIONS = {
    "stores.view": {R.SUPER_ADMIN, R.OPERATIONS, R.SUPPORT, R.FINANCE},
    "stores.review": {R.SUPER_ADMIN, R.OPERATIONS},
    "stores.suspend": {R.SUPER_ADMIN, R.OPERATIONS},
    "stores.impersonate": {R.SUPER_ADMIN, R.OPERATIONS, R.SUPPORT},
    "stores.notes": {R.SUPER_ADMIN, R.OPERATIONS, R.SUPPORT, R.FINANCE},
    "documents.view": {R.SUPER_ADMIN, R.OPERATIONS},
    "catalog.manage": {R.SUPER_ADMIN, R.OPERATIONS},
    "team.manage": {R.SUPER_ADMIN},
    "audit.view": {R.SUPER_ADMIN},
    "settings.manage": {R.SUPER_ADMIN},
}


def staff_permissions(role: str) -> list[str]:
    return sorted(p for p, roles in CONSOLE_PERMISSIONS.items() if role in roles)


def staff_can(request, perm: str) -> bool:
    staff = getattr(request.user, "platform_staff", None)
    return staff is not None and staff.role in CONSOLE_PERMISSIONS[perm]


class ConsolePermission(BasePermission):
    """Views declare `console_permissions` = {action or method or "*": perm}."""

    def has_permission(self, request, view):
        mapping = getattr(view, "console_permissions", {})
        perm = (
            mapping.get(getattr(view, "action", None))
            or mapping.get(request.method)
            or mapping.get("*")
        )
        if perm and not staff_can(request, perm):
            raise Forbidden(
                "permission_denied",
                f"Missing console permission {perm}.",
                extra={"permission": perm},
            )
        return True
