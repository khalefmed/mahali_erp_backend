from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.catalog.models import Variant
from apps.core.models import AuditEvent
from apps.stores.models import StoreDocument
from apps.stores.serializers import StoreSerializer

from .models import PlatformSettings, PlatformStaff, StaffRole, StoreNote


class StaffMeSerializer(serializers.Serializer):
    user = UserSerializer()
    role = serializers.ChoiceField(choices=StaffRole.choices)
    permissions = serializers.ListField(child=serializers.CharField())


class ConsoleAuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    staff = StaffMeSerializer()


class OwnerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
    identity_verified = serializers.SerializerMethodField()
    date_joined = serializers.DateTimeField()

    def get_identity_verified(self, obj) -> bool:
        return obj.identity_verified_at is not None


class ConsoleStoreSerializer(StoreSerializer):
    owner = OwnerSerializer(read_only=True)
    members_count = serializers.IntegerField(read_only=True)
    waiting_hours = serializers.SerializerMethodField()
    decided_by_name = serializers.CharField(
        source="decided_by.full_name", default=None, read_only=True
    )

    class Meta(StoreSerializer.Meta):
        fields = [
            *StoreSerializer.Meta.fields,
            "owner",
            "members_count",
            "waiting_hours",
            "decided_at",
            "decided_by_name",
        ]

    def get_waiting_hours(self, obj) -> int | None:
        from django.utils import timezone

        if obj.status != "pending_approval" or not obj.submitted_at:
            return None
        return int((timezone.now() - obj.submitted_at).total_seconds() // 3600)


class ConsoleDocumentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField(
        help_text="Signed link, valid 5 minutes. Each download is audited."
    )

    class Meta:
        model = StoreDocument
        fields = [
            "id",
            "kind",
            "original_name",
            "content_type",
            "size",
            "created_at",
            "download_url",
        ]

    def get_download_url(self, obj) -> str:
        from apps.stores.files import signed_url

        return signed_url(self.context["request"], "document", obj.id)


class StoreNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)

    class Meta:
        model = StoreNote
        fields = ["id", "body", "author_name", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", default=None)
    store_name = serializers.CharField(source="store.name", default=None)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_email",
            "realm",
            "action",
            "target_type",
            "target_id",
            "store",
            "store_name",
            "reason",
            "metadata",
            "ip_address",
        ]


class StoreActivitySerializer(serializers.Serializer):
    products_count = serializers.IntegerField()
    sales_last_30_days = serializers.IntegerField()
    revenue_last_30_days = serializers.IntegerField()
    last_sale_at = serializers.DateTimeField(allow_null=True)


class MemberRowSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.CharField()
    last_seen_at = serializers.DateTimeField(allow_null=True)


class StoreDetailSerializer(serializers.Serializer):
    store = ConsoleStoreSerializer()
    documents = ConsoleDocumentSerializer(many=True)
    missing_documents = serializers.ListField(child=serializers.CharField())
    members = MemberRowSerializer(many=True)
    notes = StoreNoteSerializer(many=True)
    activity = StoreActivitySerializer(allow_null=True)
    history = AuditEventSerializer(many=True)
    other_stores = serializers.ListField(
        child=serializers.DictField(), help_text="Other stores of the same owner"
    )


class DecisionSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Required for request-info, reject, suspend",
    )


class ImpersonateSerializer(serializers.Serializer):
    reason = serializers.CharField()


class ImpersonationTokenSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Merchant access token, read-only, no refresh")
    expires_at = serializers.DateTimeField()


class DashboardSerializer(serializers.Serializer):
    stores_by_status = serializers.DictField(child=serializers.IntegerField())
    stores_by_trade = serializers.DictField(child=serializers.IntegerField())
    stores_by_city = serializers.DictField(child=serializers.IntegerField())
    pending_reviews = serializers.IntegerField()
    overdue_reviews = serializers.IntegerField(help_text="Waiting longer than the SLA")
    new_stores_7_days = serializers.IntegerField()
    users_count = serializers.IntegerField()
    pending_product_requests = serializers.IntegerField()
    review_sla_hours = serializers.IntegerField()


class StaffSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email")
    full_name = serializers.CharField(source="user.full_name")
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta:
        model = PlatformStaff
        fields = ["id", "email", "full_name", "role", "is_active", "last_login", "created_at"]
        read_only_fields = ["id", "last_login", "created_at"]


class StaffUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformStaff
        fields = ["role", "is_active"]


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = ["review_sla_hours", "announcement", "signups_open", "updated_at"]
        read_only_fields = ["updated_at"]


class ProductRequestDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    variant = serializers.PrimaryKeyRelatedField(
        queryset=Variant.objects.all(), required=False, allow_null=True
    )
    message = serializers.CharField(required=False, allow_blank=True, default="")


class PlatformInfoSerializer(serializers.Serializer):
    announcement = serializers.CharField(help_text="Banner to show to every merchant, or empty")
    signups_open = serializers.BooleanField()
    review_sla_hours = serializers.IntegerField(help_text="Promised review time for new stores")
