from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    EDITABLE_ONBOARDING,
    DocumentKind,
    Invitation,
    Membership,
    OwnershipTransfer,
    Store,
    StoreDocument,
)
from .roles import INVITABLE_ROLES, ROLE_PERMISSIONS


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "trade",
            "status",
            "city",
            "address",
            "latitude",
            "longitude",
            "phone",
            "vat_enabled",
            "vat_rate",
            "max_discount_percent",
            "submitted_at",
            "approved_at",
            "decision_message",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "submitted_at",
            "approved_at",
            "decision_message",
            "created_at",
        ]

    def validate(self, attrs):
        store = self.instance
        if (
            store
            and "trade" in attrs
            and attrs["trade"] != store.trade
            and store.status not in EDITABLE_ONBOARDING
        ):
            raise serializers.ValidationError(
                {"trade": "The trade cannot change after approval."}, code="immutable"
            )
        return attrs


class StoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["name", "trade", "city", "address", "latitude", "longitude", "phone"]


class MyStoreSerializer(serializers.Serializer):
    """A store I have access to, with my role and permissions in it."""

    store = StoreSerializer()
    role = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())
    is_owner = serializers.BooleanField()


def my_store_payload(membership: Membership) -> dict:
    return {
        "store": membership.store,
        "role": membership.role,
        "permissions": sorted(ROLE_PERMISSIONS[membership.role]),
        "is_owner": membership.store.owner_id == membership.user_id,
    }


class StoreDocumentSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)

    class Meta:
        model = StoreDocument
        fields = ["id", "kind", "file", "original_name", "content_type", "size", "created_at"]
        read_only_fields = ["id", "original_name", "content_type", "size", "created_at"]


class OnboardingStatusSerializer(serializers.Serializer):
    store = StoreSerializer()
    documents = StoreDocumentSerializer(many=True)
    missing_documents = serializers.ListField(
        child=serializers.ChoiceField(choices=DocumentKind.choices)
    )
    can_submit = serializers.BooleanField()


class MemberUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()


class MembershipSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)
    role = serializers.ChoiceField(choices=[(r.value, r.label) for r in INVITABLE_ROLES])

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "is_active", "created_at"]
        read_only_fields = ["id", "user", "is_active", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["role"] = instance.role
        return data


class InvitationSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=[(r.value, r.label) for r in INVITABLE_ROLES])
    status = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "status", "expires_at", "created_at"]
        read_only_fields = ["id", "status", "expires_at", "created_at"]

    @extend_schema_field(
        serializers.ChoiceField(choices=["pending", "accepted", "revoked", "expired"])
    )
    def get_status(self, obj) -> str:
        from django.utils import timezone

        if obj.accepted_at:
            return "accepted"
        if obj.revoked_at:
            return "revoked"
        if obj.expires_at <= timezone.now():
            return "expired"
        return "pending"


class InvitationPreviewSerializer(serializers.Serializer):
    store_name = serializers.CharField()
    store_trade = serializers.CharField()
    role = serializers.CharField()
    invited_by = serializers.CharField()
    email = serializers.EmailField()
    status = serializers.CharField()


class MyInvitationSerializer(InvitationSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta(InvitationSerializer.Meta):
        fields = [*InvitationSerializer.Meta.fields, "store_name"]


class OwnershipTransferSerializer(serializers.ModelSerializer):
    to_user_id = serializers.UUIDField(write_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    from_user = MemberUserSerializer(read_only=True)
    to_user = MemberUserSerializer(read_only=True)

    class Meta:
        model = OwnershipTransfer
        fields = [
            "id",
            "store",
            "store_name",
            "from_user",
            "to_user",
            "to_user_id",
            "accepted_at",
            "created_at",
        ]
        read_only_fields = ["id", "store", "accepted_at", "created_at"]
