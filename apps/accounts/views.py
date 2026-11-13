from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import UserSession
from .serializers import (
    AuthResponseSerializer,
    EmailSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetSerializer,
    RefreshSerializer,
    RegisterSerializer,
    SessionSerializer,
    TokenPairSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from .throttles import AuthEmailThrottle, AuthIpThrottle, EmailCodeThrottle


class PublicAuthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthIpThrottle, AuthEmailThrottle]

    def validated(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


@extend_schema(tags=["auth"])
class RegisterView(PublicAuthView):
    throttle_classes = [AuthIpThrottle, EmailCodeThrottle]

    @extend_schema(
        operation_id="auth_register",
        request=RegisterSerializer,
        responses={202: None},
        description="Creates the account and emails a 6-digit code. Always 202, even if the "
        "email is already used (no account enumeration). Next: `auth/verify-email`.",
    )
    def post(self, request):
        services.register(**self.validated(RegisterSerializer))
        return Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["auth"])
class ResendCodeView(PublicAuthView):
    throttle_classes = [AuthIpThrottle, EmailCodeThrottle]

    @extend_schema(operation_id="auth_resend_code", request=EmailSerializer, responses={202: None})
    def post(self, request):
        services.resend_code(self.validated(EmailSerializer)["email"])
        return Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["auth"])
class VerifyEmailView(PublicAuthView):
    @extend_schema(
        operation_id="auth_verify_email",
        request=VerifyEmailSerializer,
        responses={200: AuthResponseSerializer},
        description="Errors: `invalid_code` (with `attempts_left`), `code_expired`. "
        "On success the user is signed in.",
    )
    def post(self, request):
        user, tokens = services.verify_email(request, **self.validated(VerifyEmailSerializer))
        return Response({**tokens, "user": UserSerializer(user).data})


@extend_schema(tags=["auth"])
class LoginView(PublicAuthView):
    realm = UserSession.Realm.MERCHANT

    @extend_schema(
        operation_id="auth_login",
        request=LoginSerializer,
        responses={200: AuthResponseSerializer},
        description="Errors: `invalid_credentials` (401), `email_not_verified` (403).",
    )
    def post(self, request):
        user, tokens = services.login(request, **self.validated(LoginSerializer), realm=self.realm)
        return Response({**tokens, "user": UserSerializer(user).data})


@extend_schema(tags=["auth"])
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class RefreshView(PublicAuthView):
    throttle_classes = [AuthIpThrottle]

    @extend_schema(
        operation_id="auth_refresh", request=RefreshSerializer, responses={200: TokenPairSerializer}
    )
    def post(self, request):
        return Response(services.refresh_tokens(self.validated(RefreshSerializer)["refresh"]))


@extend_schema(tags=["auth"])
class LogoutView(APIView):
    @extend_schema(operation_id="auth_logout", request=RefreshSerializer, responses={204: None})
    def post(self, request):
        services.logout(request.data.get("refresh"), getattr(request, "user_session", None))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class ForgotPasswordView(PublicAuthView):
    throttle_classes = [AuthIpThrottle, EmailCodeThrottle]

    @extend_schema(
        operation_id="auth_password_forgot",
        request=EmailSerializer,
        responses={202: None},
        description="Emails a reset link to `{WEB_APP_URL}/{lang}/reset-password"
        "?uid=…&token=…` (valid 30 min). Always 202.",
    )
    def post(self, request):
        services.request_password_reset(self.validated(EmailSerializer)["email"])
        return Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["auth"])
class ResetPasswordView(PublicAuthView):
    @extend_schema(
        operation_id="auth_password_reset",
        request=PasswordResetSerializer,
        responses={204: None},
        description="Errors: `invalid_reset_link`. Ends every session of the user.",
    )
    def post(self, request):
        services.reset_password(**self.validated(PasswordResetSerializer))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["me"])
class ChangePasswordView(APIView):
    @extend_schema(
        operation_id="me_password_change", request=PasswordChangeSerializer, responses={204: None}
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_password(
            request.user,
            current=serializer.validated_data["current_password"],
            new=serializer.validated_data["new_password"],
            session_id=request.user_session.id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["me"])
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


@extend_schema(tags=["me"])
class SessionViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Signed-in devices. DELETE signs that device out immediately."""

    serializer_class = SessionSerializer
    pagination_class = None
    realm = UserSession.Realm.MERCHANT

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return UserSession.objects.none()
        return UserSession.objects.filter(
            user=self.request.user,
            realm=self.realm,
            revoked_at__isnull=True,
            impersonator__isnull=True,
            last_seen_at__gte=services.session_cutoff(),
        ).order_by("-last_seen_at")

    def perform_destroy(self, instance):
        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at"])
