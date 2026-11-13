from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.exceptions import Forbidden


class NotReadOnlySession(BasePermission):
    """Console "log in as" sessions can only read."""

    def has_permission(self, request, view):
        if getattr(request, "is_impersonation", False) and request.method not in SAFE_METHODS:
            raise Forbidden("read_only_session", "This session is read-only.")
        return True
