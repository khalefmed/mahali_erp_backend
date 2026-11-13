from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import UserSession


def issue_tokens(user, session: UserSession) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["sid"] = str(session.id)
    refresh["realm"] = session.realm
    access = refresh.access_token
    return {"access": str(access), "refresh": str(refresh)}


def issue_impersonation_token(session: UserSession) -> dict:
    """Access token only (no refresh): read-only, one store, expires with the session."""
    access = AccessToken.for_user(session.user)
    access["sid"] = str(session.id)
    access["realm"] = UserSession.Realm.MERCHANT
    access.set_exp(lifetime=settings.IMPERSONATION_TTL)
    return {"access": str(access), "expires_at": session.expires_at or timezone.now()}
