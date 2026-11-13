from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import Language, User, UserSession


class UserSerializer(serializers.ModelSerializer):
    email_verified = serializers.BooleanField(source="is_email_verified", read_only=True)
    identity_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "language",
            "email_verified",
            "identity_verified",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "date_joined"]

    def get_identity_verified(self, obj) -> bool:
        return obj.identity_verified_at is not None


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=Language.choices, default=Language.FR)

    def validate(self, attrs):
        user = User(email=attrs["email"], full_name=attrs["full_name"])
        password_validation.validate_password(attrs["password"], user)
        return attrs


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r"^\d{6}$")


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="JWT, 10 minutes. Send as `Authorization: Bearer`.")
    refresh = serializers.CharField(
        help_text="Single use: each refresh returns a new one. Reusing an old one ends the session."
    )


class AuthResponseSerializer(TokenPairSerializer):
    user = UserSerializer()


class PasswordResetSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class SessionSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = ["id", "user_agent", "ip_address", "created_at", "last_seen_at", "current"]

    def get_current(self, obj) -> bool:
        session = getattr(self.context.get("request"), "user_session", None)
        return session is not None and session.id == obj.id
