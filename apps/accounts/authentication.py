from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .models import UserSession


class _RealmJWTAuthentication(JWTAuthentication):
    realm: str

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if token.get("realm") != self.realm:
            raise AuthenticationFailed("Token not valid for this API.", code="token_not_valid")
        session = (
            UserSession.objects.filter(id=token.get("sid"), user=user)
            .only(
                "id",
                "revoked_at",
                "expires_at",
                "impersonator_id",
                "impersonated_store_id",
                "last_seen_at",
            )
            .first()
        )
        if session is None or not session.is_active:
            raise AuthenticationFailed("Session ended.", code="session_revoked")
        if (timezone.now() - session.last_seen_at).total_seconds() > 300:
            UserSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now())
        request.auth_realm = self.realm
        request.user_session = session
        request.is_impersonation = session.impersonator_id is not None
        self.check_user(user)
        return user, token

    def check_user(self, user):
        pass


class MerchantJWTAuthentication(_RealmJWTAuthentication):
    realm = UserSession.Realm.MERCHANT

    def check_user(self, user):
        if not user.is_email_verified:
            raise AuthenticationFailed("Email not verified.", code="email_not_verified")


class ConsoleJWTAuthentication(_RealmJWTAuthentication):
    realm = UserSession.Realm.CONSOLE

    def check_user(self, user):
        staff = getattr(user, "platform_staff", None)
        if staff is None or not staff.is_active:
            raise AuthenticationFailed("Not a Mahali team member.", code="not_platform_staff")
