from django.core import signing
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit
from apps.core.exceptions import Forbidden

from . import services
from .access import StoreScopedViewMixin
from .files import unsign
from .models import Invitation, Membership, OwnershipTransfer, Store, StoreDocument
from .roles import ROLE_PERMISSIONS, Perm
from .serializers import (
    InvitationPreviewSerializer,
    InvitationSerializer,
    MembershipSerializer,
    MyInvitationSerializer,
    MyStoreSerializer,
    OnboardingStatusSerializer,
    OwnershipTransferSerializer,
    StoreCreateSerializer,
    StoreDocumentSerializer,
    StoreSerializer,
    my_store_payload,
)


@extend_schema(tags=["me"])
class MyStoresView(APIView):
    @extend_schema(
        operation_id="me_stores_list",
        responses={200: MyStoreSerializer(many=True)},
        description="Every store I can open, with my role and permissions in it. "
        "Store status tells the web which screen to show (pending → AUTH-11…).",
    )
    def get(self, request):
        memberships = (
            Membership.objects.filter(user=request.user, is_active=True)
            .select_related("store")
            .order_by("store__name")
        )
        data = [my_store_payload(m) for m in memberships]
        return Response(MyStoreSerializer(data, many=True).data)


@extend_schema(tags=["stores: onboarding"])
class StoreViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Create a store and go through onboarding (documents → submit → Mahali review).
    Works in every status, unlike the store-scoped routes which need an active store."""

    serializer_class = StoreSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Store.objects.none()
        return Store.objects.filter(
            memberships__user=self.request.user, memberships__is_active=True
        )

    def get_object(self):
        session = self.request.user_session
        if session.impersonator_id:
            if str(session.impersonated_store_id) != str(self.kwargs["pk"]):
                raise Http404
            return get_object_or_404(Store, pk=self.kwargs["pk"])
        return super().get_object()

    @extend_schema(
        operation_id="stores_create",
        request=StoreCreateSerializer,
        responses={201: StoreSerializer},
        description="Creates a store in `draft`; the caller becomes its owner. "
        "Errors: `too_many_pending_stores` (409), `signups_closed` (403).",
    )
    def create(self, request, *args, **kwargs):
        serializer = StoreCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = services.create_store(request.user, **serializer.validated_data)
        return Response(StoreSerializer(store).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        store = serializer.instance
        membership = Membership.objects.filter(store=store, user=self.request.user).first()
        if membership is None or Perm.STORE_MANAGE not in ROLE_PERMISSIONS[membership.role]:
            raise Forbidden("permission_denied", "Only the owner can change the store.")
        serializer.save()
        audit.record(
            self.request,
            "store.updated",
            target=store,
            store=store,
            fields=sorted(serializer.validated_data),
        )

    @extend_schema(
        operation_id="stores_onboarding",
        responses={200: OnboardingStatusSerializer},
        description="Everything AUTH-12 / AUTH-11 need: documents, what is missing.",
    )
    @action(detail=True, methods=["get"])
    def onboarding(self, request, pk=None):
        store = self.get_object()
        missing = services.missing_documents(store)
        return Response(
            OnboardingStatusSerializer(
                {
                    "store": store,
                    "documents": store.documents.order_by("created_at"),
                    "missing_documents": missing,
                    "can_submit": not missing and store.status in {"draft", "info_requested"},
                }
            ).data
        )

    @extend_schema(
        operation_id="stores_documents_upload",
        request=StoreDocumentSerializer,
        responses={201: StoreDocumentSerializer},
        description="multipart/form-data: `kind` + `file` (JPEG, PNG, WebP or PDF, "
        "8 MB max). Errors: `unsupported_file_type`, `file_too_large`, "
        "`store_not_editable`.",
    )
    @action(detail=True, methods=["post"], url_path="documents", parser_classes=[MultiPartParser])
    def upload_document(self, request, pk=None):
        store = self.get_object()
        serializer = StoreDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = services.add_document(
            store,
            request.user,
            serializer.validated_data["kind"],
            serializer.validated_data["file"],
        )
        return Response(StoreDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(operation_id="stores_documents_delete", request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"documents/(?P<document_id>[^/.]+)")
    def delete_document(self, request, pk=None, document_id=None):
        store = self.get_object()
        services.ensure_owner_editing(store, request.user)
        doc = get_object_or_404(StoreDocument, pk=document_id, store=store)
        doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="stores_submit",
        request=None,
        responses={200: StoreSerializer},
        description="Sends the store to the Mahali team → `pending_approval`. "
        "Error `documents_missing` lists `missing`.",
    )
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        store = services.submit_for_review(request, self.get_object())
        return Response(StoreSerializer(store).data)


@extend_schema(tags=["stores: team"])
class MemberViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MembershipSerializer
    pagination_class = None
    http_method_names = ["get", "patch", "delete"]
    required_permissions = {
        "list": Perm.STORE_VIEW,
        "partial_update": Perm.MEMBERS_MANAGE,
        "destroy": Perm.MEMBERS_MANAGE,
    }

    def get_queryset(self):
        return (
            Membership.objects.filter(store=self.store, is_active=True)
            .select_related("user")
            .order_by("created_at")
        )

    def perform_update(self, serializer):
        services.change_role(self.request, serializer.instance, serializer.validated_data["role"])

    def perform_destroy(self, instance):
        services.remove_member(self.request, instance)


@extend_schema(tags=["stores: team"])
class InvitationViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = InvitationSerializer
    pagination_class = None
    required_permissions = {"*": Perm.MEMBERS_MANAGE}

    def get_queryset(self):
        return Invitation.objects.filter(
            store=self.store, accepted_at__isnull=True, revoked_at__isnull=True
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.instance = services.invite(self.request, self.store, **serializer.validated_data)

    def perform_destroy(self, instance):
        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at"])


@extend_schema(tags=["stores: team"])
class OwnershipTransferView(StoreScopedViewMixin, APIView):
    required_permissions = {"POST": Perm.STORE_MANAGE}

    @extend_schema(
        operation_id="stores_ownership_transfer_create",
        request=OwnershipTransferSerializer,
        responses={201: OwnershipTransferSerializer},
    )
    def post(self, request, store_id):
        serializer = OwnershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = services.request_ownership_transfer(
            request, self.store, serializer.validated_data["to_user_id"]
        )
        return Response(OwnershipTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["invitations"])
class InvitationPreviewView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="invitations_preview", responses={200: InvitationPreviewSerializer})
    def get(self, request, token):
        invitation = services.invitation_by_token(token)
        data = InvitationSerializer(invitation).data
        return Response(
            {
                "store_name": invitation.store.name,
                "store_trade": invitation.store.trade,
                "role": invitation.role,
                "invited_by": invitation.invited_by.full_name,
                "email": invitation.email,
                "status": data["status"],
            }
        )


@extend_schema(tags=["invitations"])
class InvitationAcceptView(APIView):
    @extend_schema(
        operation_id="invitations_accept",
        request=None,
        responses={200: MyStoreSerializer},
        description="Errors: `invitation_invalid`, `invitation_wrong_account`.",
    )
    def post(self, request, token):
        membership = services.accept_invitation(request, services.invitation_by_token(token))
        return Response(MyStoreSerializer(my_store_payload(membership)).data)


@extend_schema(tags=["me"])
class MyInvitationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Pending invitations sent to my email, to accept from inside the app."""

    serializer_class = MyInvitationSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invitation.objects.none()
        return Invitation.objects.filter(
            email__iexact=self.request.user.email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).select_related("store")

    @extend_schema(
        operation_id="me_invitations_accept", request=None, responses={200: MyStoreSerializer}
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        membership = services.accept_invitation(request, self.get_object())
        return Response(MyStoreSerializer(my_store_payload(membership)).data)


@extend_schema(tags=["me"])
class MyOwnershipTransferViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = OwnershipTransferSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OwnershipTransfer.objects.none()
        return OwnershipTransfer.objects.filter(
            to_user=self.request.user, accepted_at__isnull=True, cancelled_at__isnull=True
        ).select_related("store", "from_user", "to_user")

    @extend_schema(
        operation_id="me_ownership_transfers_accept", request=None, responses={200: StoreSerializer}
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        store = services.accept_ownership_transfer(request, self.get_object())
        return Response(StoreSerializer(store).data)


@extend_schema(exclude=True)
class PrivateFileView(APIView):
    """Signed link download (5 minutes). Every download is audited."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            payload = unsign(token)
        except signing.BadSignature:
            raise Http404 from None
        if payload["k"] != "document":
            raise Http404
        doc = StoreDocument.objects.filter(pk=payload["id"]).select_related("store").first()
        if doc is None:
            raise Http404
        audit.record(
            request,
            "document.downloaded",
            target=doc,
            store=doc.store,
            realm="console",
            downloaded_by=payload["u"],
        )
        response = FileResponse(doc.file.open("rb"), content_type=doc.content_type)
        response["Content-Disposition"] = f'inline; filename="{doc.kind}{doc.file.name[-4:]}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
