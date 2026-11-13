from datetime import timedelta

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import ConsoleJWTAuthentication
from apps.accounts.models import User, UserSession
from apps.accounts.serializers import LoginSerializer
from apps.accounts.views import LoginView, SessionViewSet
from apps.catalog import services as catalog_services
from apps.catalog.filters import ProductFilter
from apps.catalog.models import Brand, Category, Product, ProductRequest
from apps.catalog.serializers import (
    BrandSerializer,
    CatalogProductSerializer,
    CategorySerializer,
    ImportRequestSerializer,
    ImportResultSerializer,
    ProductRequestSerializer,
)
from apps.core.models import AuditEvent
from apps.core.tenancy import store_context
from apps.inventory.models import StoreProduct
from apps.sales.models import Sale
from apps.stores.models import Store, StoreStatus
from apps.stores.services import missing_documents

from . import services
from .models import PlatformSettings, PlatformStaff, StoreNote
from .permissions import ConsolePermission, staff_permissions
from .serializers import (
    AuditEventSerializer,
    ConsoleAuthResponseSerializer,
    ConsoleStoreSerializer,
    DashboardSerializer,
    DecisionSerializer,
    ImpersonateSerializer,
    ImpersonationTokenSerializer,
    PlatformInfoSerializer,
    PlatformSettingsSerializer,
    ProductRequestDecisionSerializer,
    StaffMeSerializer,
    StaffSerializer,
    StaffUpdateSerializer,
    StoreDetailSerializer,
    StoreNoteSerializer,
)


class ConsoleMixin:
    authentication_classes = [ConsoleJWTAuthentication]

    def get_permissions(self):
        return [*super().get_permissions(), ConsolePermission()]


def _staff_me(user):
    staff = user.platform_staff
    return {"user": user, "role": staff.role, "permissions": staff_permissions(staff.role)}


@extend_schema(tags=["console: auth"])
class ConsoleLoginView(LoginView):
    realm = UserSession.Realm.CONSOLE

    @extend_schema(
        operation_id="console_auth_login",
        request=LoginSerializer,
        responses={200: ConsoleAuthResponseSerializer},
        description="Mahali team sign-in. Refresh and logout use `auth/refresh` and "
        "`console/auth/logout`.",
    )
    def post(self, request):
        from apps.accounts import services as account_services

        user, tokens = account_services.login(
            request, **self.validated(LoginSerializer), realm=self.realm
        )
        return Response({**tokens, "staff": StaffMeSerializer(_staff_me(user)).data})


@extend_schema(tags=["console: auth"])
class ConsoleLogoutView(ConsoleMixin, APIView):
    @extend_schema(operation_id="console_auth_logout", request=None, responses={204: None})
    def post(self, request):
        from apps.accounts.services import logout

        logout(request.data.get("refresh"), request.user_session)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["console: auth"])
class ConsoleMeView(ConsoleMixin, APIView):
    @extend_schema(operation_id="console_me", responses={200: StaffMeSerializer})
    def get(self, request):
        return Response(StaffMeSerializer(_staff_me(request.user)).data)


@extend_schema(tags=["console: auth"])
class ConsoleSessionViewSet(ConsoleMixin, SessionViewSet):
    realm = UserSession.Realm.CONSOLE


@extend_schema(tags=["console: dashboard"])
class DashboardView(ConsoleMixin, APIView):
    console_permissions = {"*": "stores.view"}

    @extend_schema(operation_id="console_dashboard", responses={200: DashboardSerializer})
    def get(self, request):
        sla = PlatformSettings.load().review_sla_hours
        stores = Store.objects.all()

        def grouped(field):
            return {row[field]: row["n"] for row in stores.values(field).annotate(n=Count("id"))}

        pending = stores.filter(status=StoreStatus.PENDING_APPROVAL)
        return Response(
            DashboardSerializer(
                {
                    "stores_by_status": grouped("status"),
                    "stores_by_trade": grouped("trade"),
                    "stores_by_city": grouped("city"),
                    "pending_reviews": pending.count(),
                    "overdue_reviews": pending.filter(
                        submitted_at__lt=timezone.now() - timedelta(hours=sla)
                    ).count(),
                    "new_stores_7_days": stores.filter(
                        created_at__gte=timezone.now() - timedelta(days=7)
                    ).count(),
                    "users_count": User.objects.filter(platform_staff__isnull=True).count(),
                    "pending_product_requests": ProductRequest.objects.filter(
                        status="pending"
                    ).count(),
                    "review_sla_hours": sla,
                }
            ).data
        )


@extend_schema(tags=["console: stores"])
class ConsoleStoreViewSet(ConsoleMixin, viewsets.ReadOnlyModelViewSet):
    """All stores. The review queue (SA-02) is `?status=pending_approval&ordering=submitted_at`."""

    serializer_class = ConsoleStoreSerializer
    filterset_fields = ["status", "trade", "city"]
    ordering_fields = ["submitted_at", "created_at", "name"]
    console_permissions = {
        "*": "stores.view",
        "approve": "stores.review",
        "request_info": "stores.review",
        "reject": "stores.review",
        "suspend": "stores.suspend",
        "reactivate": "stores.suspend",
        "impersonate": "stores.impersonate",
        "notes": "stores.notes",
    }

    def get_queryset(self):
        queryset = Store.objects.select_related("owner", "decided_by").annotate(
            members_count=Count("memberships", filter=Q(memberships__is_active=True))
        )
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__unaccent__icontains=search)
                | Q(owner__email__icontains=search)
                | Q(owner__full_name__unaccent__icontains=search)
                | Q(phone__icontains=search)
            )
        return queryset

    @extend_schema(
        operation_id="console_stores_retrieve",
        responses={200: StoreDetailSerializer},
        description="Store 360 (SA-03 / SA-05).",
    )
    def retrieve(self, request, pk=None):
        store = self.get_object()
        activity = None
        if store.approved_at:
            since = timezone.now() - timedelta(days=30)
            with store_context(store.id):
                recent = Sale.objects.filter(created_at__gte=since)
                activity = {
                    "products_count": StoreProduct.objects.count(),
                    "sales_last_30_days": recent.count(),
                    "revenue_last_30_days": recent.aggregate(t=Sum("total"))["t"] or 0,
                    "last_sale_at": Sale.objects.aggregate(t=Max("created_at"))["t"],
                }
        members = [
            {
                "user_id": m.user_id,
                "full_name": m.user.full_name,
                "email": m.user.email,
                "role": m.role,
                "last_seen_at": m.user.sessions.aggregate(t=Max("last_seen_at"))["t"],
            }
            for m in store.memberships.filter(is_active=True).select_related("user")
        ]
        include_docs = "documents.view" in staff_permissions(request.user.platform_staff.role)
        data = {
            "store": store,
            "documents": store.documents.all() if include_docs else [],
            "missing_documents": missing_documents(store),
            "members": members,
            "notes": store.notes.select_related("author")[:50],
            "activity": activity,
            "history": AuditEvent.objects.filter(store=store).select_related("actor", "store")[:50],
            "other_stores": list(
                Store.objects.filter(owner=store.owner)
                .exclude(pk=store.pk)
                .values("id", "name", "status", "trade")
            ),
        }
        return Response(StoreDetailSerializer(data, context={"request": request}).data)

    def _decision(self, request, func, require_message=False):
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"].strip()
        if require_message and not message:
            from apps.core.exceptions import ApiError

            raise ApiError("message_required", "Explain the decision to the merchant.")
        store = func(request, self.get_object(), message)
        return Response(ConsoleStoreSerializer(self.get_queryset().get(pk=store.pk)).data)

    @extend_schema(
        operation_id="console_stores_approve",
        request=DecisionSerializer,
        responses={200: ConsoleStoreSerializer},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decision(request, services.approve)

    @extend_schema(
        operation_id="console_stores_request_info",
        request=DecisionSerializer,
        responses={200: ConsoleStoreSerializer},
    )
    @action(detail=True, methods=["post"], url_path="request-info")
    def request_info(self, request, pk=None):
        return self._decision(request, services.request_info, require_message=True)

    @extend_schema(
        operation_id="console_stores_reject",
        request=DecisionSerializer,
        responses={200: ConsoleStoreSerializer},
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decision(request, services.reject, require_message=True)

    @extend_schema(
        operation_id="console_stores_suspend",
        request=DecisionSerializer,
        responses={200: ConsoleStoreSerializer},
    )
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._decision(request, services.suspend, require_message=True)

    @extend_schema(
        operation_id="console_stores_reactivate",
        request=DecisionSerializer,
        responses={200: ConsoleStoreSerializer},
    )
    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._decision(request, services.reactivate, require_message=True)

    @extend_schema(
        operation_id="console_stores_impersonate",
        request=ImpersonateSerializer,
        responses={201: ImpersonationTokenSerializer},
        description="'Se connecter en tant que': read-only merchant token for this "
        "store, 30 min, reason required, owner notified.",
    )
    @action(detail=True, methods=["post"])
    def impersonate(self, request, pk=None):
        serializer = ImpersonateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = services.impersonate(
            request, self.get_object(), serializer.validated_data["reason"]
        )
        return Response(ImpersonationTokenSerializer(tokens).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="console_stores_notes_create",
        request=StoreNoteSerializer,
        responses={201: StoreNoteSerializer},
    )
    @action(detail=True, methods=["post"])
    def notes(self, request, pk=None):
        serializer = StoreNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = StoreNote.objects.create(
            store=self.get_object(), author=request.user, **serializer.validated_data
        )
        return Response(StoreNoteSerializer(note).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["console: catalog"])
class ConsoleCategoryViewSet(ConsoleMixin, viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    pagination_class = None
    filterset_fields = ["trade", "parent", "is_active"]
    http_method_names = ["get", "post", "patch"]
    console_permissions = {"GET": "stores.view", "*": "catalog.manage"}


@extend_schema(tags=["console: catalog"])
class ConsoleBrandViewSet(ConsoleMixin, viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    queryset = Brand.objects.all()
    pagination_class = None
    http_method_names = ["get", "post", "patch"]
    console_permissions = {"GET": "stores.view", "*": "catalog.manage"}


@extend_schema(tags=["console: catalog"])
class ConsoleProductViewSet(ConsoleMixin, viewsets.ModelViewSet):
    """Create / edit catalog products with their variants (nested). Archive instead of delete."""

    serializer_class = CatalogProductSerializer
    http_method_names = ["get", "post", "patch"]
    console_permissions = {"GET": "stores.view", "*": "catalog.manage"}

    filterset_class = ProductFilter

    def get_queryset(self):
        return Product.objects.select_related("category", "brand").prefetch_related("variants")

    @extend_schema(
        operation_id="console_catalog_import",
        request=ImportRequestSerializer,
        responses={200: ImportResultSerializer},
        description="CSV import, all or nothing. Use `dry_run=true` to preview errors.",
    )
    @action(detail=False, methods=["post"], url_path="import", parser_classes=[MultiPartParser])
    def import_csv(self, request):
        serializer = ImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = catalog_services.import_csv(
            serializer.validated_data["file"], dry_run=serializer.validated_data["dry_run"]
        )
        return Response(ImportResultSerializer(result).data)


@extend_schema(tags=["console: catalog"])
class ConsoleProductRequestViewSet(ConsoleMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductRequestSerializer
    filterset_fields = ["status", "store", "category"]
    console_permissions = {"GET": "stores.view", "*": "catalog.manage"}

    def get_queryset(self):
        return ProductRequest.objects.select_related("store", "variant").order_by("created_at")

    @extend_schema(
        operation_id="console_product_requests_decide",
        request=ProductRequestDecisionSerializer,
        responses={200: ProductRequestSerializer},
        description="Approve with the `variant` added to the catalog, or reject "
        "with a message. The store is notified.",
    )
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        serializer = ProductRequestDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = catalog_services.decide_product_request(
            request,
            self.get_object(),
            approve=serializer.validated_data["approve"],
            variant=serializer.validated_data.get("variant"),
            message=serializer.validated_data["message"],
        )
        return Response(ProductRequestSerializer(result).data)


@extend_schema(tags=["console: team & audit"])
class StaffViewSet(
    ConsoleMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Mahali team (SA-09). New members get an email to set their password."""

    serializer_class = StaffSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch"]
    console_permissions = {"*": "team.manage"}

    def get_queryset(self):
        return PlatformStaff.objects.select_related("user").order_by("user__full_name")

    def get_serializer_class(self):
        return StaffUpdateSerializer if self.action == "partial_update" else StaffSerializer

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.add_staff(
            self.request,
            email=data["user"]["email"],
            full_name=data["user"]["full_name"],
            role=data["role"],
        )

    def perform_update(self, serializer):
        serializer.instance = services.update_staff(
            self.request, serializer.instance, **serializer.validated_data
        )


@extend_schema(tags=["console: team & audit"])
class AuditEventViewSet(ConsoleMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    filterset_fields = ["action", "store", "actor", "realm"]
    console_permissions = {"*": "audit.view"}

    def get_queryset(self):
        return AuditEvent.objects.select_related("actor", "store")


@extend_schema(tags=["console: settings"])
class PlatformSettingsView(ConsoleMixin, APIView):
    console_permissions = {"GET": "stores.view", "PATCH": "settings.manage"}

    @extend_schema(
        operation_id="console_settings_retrieve", responses={200: PlatformSettingsSerializer}
    )
    def get(self, request):
        return Response(PlatformSettingsSerializer(PlatformSettings.load()).data)

    @extend_schema(
        operation_id="console_settings_update",
        request=PlatformSettingsSerializer,
        responses={200: PlatformSettingsSerializer},
    )
    def patch(self, request):
        serializer = PlatformSettingsSerializer(
            PlatformSettings.load(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(tags=["platform"])
class PlatformInfoView(APIView):
    """Public: what the Mahali team set in the console (SA-10)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="platform_info", responses={200: PlatformInfoSerializer})
    def get(self, request):
        return Response(PlatformInfoSerializer(PlatformSettings.load()).data)
