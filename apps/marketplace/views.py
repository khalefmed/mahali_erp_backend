import django_filters
from django.db import transaction
from django.db.models import Count, Max, Min, Q
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts import services as account_services
from apps.accounts.authentication import CustomerJWTAuthentication
from apps.accounts.models import UserSession
from apps.accounts.serializers import (
    AuthResponseSerializer,
    EmailSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from apps.accounts.throttles import AuthIpThrottle, EmailCodeThrottle
from apps.accounts.views import LoginView, PublicAuthView
from apps.catalog.models import Product
from apps.console.views import ConsoleMixin
from apps.core.exceptions import ApiError
from apps.core.tenancy import enable_marketplace_read
from apps.stores.access import StoreScopedViewMixin
from apps.stores.models import Trade
from apps.stores.roles import Perm

from . import contract, kyc, meysara, selectors, services
from .models import IdentityVerification, Order, StoreOrder
from .search import ShopSearchFilter
from .serializers import (
    AcceptSerializer,
    CartSerializer,
    ConsoleOrderSerializer,
    IdentityCodeSerializer,
    IdentityDocumentsSerializer,
    IdentityStartSerializer,
    IdentityStateSerializer,
    MeysaraContractRequestSerializer,
    MeysaraContractTermsSerializer,
    MeysaraOfferSerializer,
    MeysaraSignedContractSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    PayInstalmentSerializer,
    QuoteSerializer,
    ReasonSerializer,
    ShopCategorySerializer,
    ShopFacetsSerializer,
    ShopProductDetailSerializer,
    ShopProductSerializer,
    StoreOrderSerializer,
)


class MeysaraTotalSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0, help_text="Order total in MRU (cart quote)")


class MarketplaceReadMixin:
    """Views that read across stores (inside the request transaction)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        enable_marketplace_read()


class PublicMixin:
    authentication_classes = []
    permission_classes = [AllowAny]


class CustomerMixin:
    authentication_classes = [CustomerJWTAuthentication]
    permission_classes = [IsAuthenticated]


# ---------------------------------------------------------------- shop window


@extend_schema(tags=["marketplace: shop"])
class ShopCategoryView(PublicMixin, MarketplaceReadMixin, generics.ListAPIView):
    """Active categories with how many products are in stock (hide the empty ones)."""

    serializer_class = ShopCategorySerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.categories()

    @extend_schema(operation_id="marketplace_categories_list")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ShopProductFilter(django_filters.FilterSet):
    trade = django_filters.ChoiceFilter(field_name="category__trade", choices=Trade.choices)
    category = django_filters.CharFilter(
        method="filter_category", help_text="Category slug (includes its sub-categories)"
    )
    brand = django_filters.CharFilter(field_name="brand__slug", help_text="Brand slug")
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")

    class Meta:
        model = Product
        fields = ["trade", "category", "brand", "min_price", "max_price"]

    def filter_category(self, queryset, name, value):
        return queryset.filter(Q(category__slug=value) | Q(category__parent__slug=value))


@extend_schema(tags=["marketplace: shop"])
class ShopProductViewSet(PublicMixin, MarketplaceReadMixin, viewsets.ReadOnlyModelViewSet):
    """Products in stock somewhere, priced from the cheapest store plus the Mahali margin.
    Stores are never named."""

    serializer_class = ShopProductSerializer
    filterset_class = ShopProductFilter
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        ShopSearchFilter,
        filters.OrderingFilter,
    ]
    # Documented by ShopSearchFilter (accents and synonyms); kept for the schema.
    search_fields = ["name", "name_ar", "brand__name", "category__name", "variants__barcode"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Schema generation runs without a migrated database (CI): don't read PlatformSettings.
            return Product.objects.none()
        return selectors.products(selectors.margin_percent()).distinct()

    @extend_schema(operation_id="marketplace_products_list")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="marketplace_products_facets",
        filters=True,
        responses={200: ShopFacetsSerializer},
        description="Filters for a listing: same query as the list (`trade`, `category`, "
        "`search`, prices). Brands ignore the `brand` filter so the shopper can switch.",
    )
    @action(detail=False, methods=["get"])
    def facets(self, request):
        listing = self.filter_queryset(self.get_queryset())
        without_brand = request.query_params.copy()
        without_brand.pop("brand", None)
        brand_base = ShopProductFilter(
            without_brand, queryset=self.get_queryset(), request=request
        ).qs
        brand_base = ShopSearchFilter().filter_queryset(request, brand_base, self)
        ids = Product.objects.filter(pk__in=brand_base.values("pk"), brand__isnull=False)
        brands = (
            ids.values("brand__slug", "brand__name")
            .annotate(count=Count("pk"))
            .order_by("brand__name")
        )
        bounds = listing.aggregate(min_price=Min("price"), max_price=Max("price"))
        return Response(
            ShopFacetsSerializer(
                {
                    "brands": [
                        {"slug": b["brand__slug"], "name": b["brand__name"], "count": b["count"]}
                        for b in brands
                    ],
                    "min_price": bounds["min_price"],
                    "max_price": bounds["max_price"],
                    "count": listing.count(),
                }
            ).data
        )

    @extend_schema(
        operation_id="marketplace_products_retrieve",
        responses={200: ShopProductDetailSerializer},
        description="Variants out of stock come back with `price: null, available: false`.",
    )
    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        variants = selectors.variants_of(product, selectors.margin_percent())
        data = ShopProductDetailSerializer(product, context={"variants": variants}).data
        return Response(data)


@extend_schema(tags=["marketplace: shop"])
class QuoteView(PublicMixin, APIView):
    @extend_schema(
        operation_id="marketplace_cart_quote",
        request=CartSerializer,
        responses={200: QuoteSerializer},
        description="Prices a cart kept by the app (no login needed). Unavailable lines come "
        "back with `available: false` and the largest quantity one store can serve. "
        "Errors: `invalid_quantity`, `whole_quantity_required`.",
    )
    def post(self, request):
        serializer = CartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lines, total = services.price_lines(serializer.validated_data["lines"], strict=False)
        return Response(QuoteSerializer({"lines": lines, "total": total}).data)


# ---------------------------------------------------------------- customer accounts


@extend_schema(tags=["marketplace: auth"])
class CustomerRegisterView(PublicAuthView):
    @extend_schema(
        operation_id="marketplace_auth_register",
        request=RegisterSerializer,
        responses={202: None},
        description="Same as `auth/register` for shoppers (works even when merchant sign-ups "
        "are closed). Then `marketplace/auth/verify-email`.",
    )
    def post(self, request):
        account_services.register(**self.validated(RegisterSerializer), merchant=False)
        return Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["marketplace: auth"])
class CustomerVerifyEmailView(PublicAuthView):
    @extend_schema(
        operation_id="marketplace_auth_verify_email",
        request=VerifyEmailSerializer,
        responses={200: AuthResponseSerializer},
        description="Errors: `invalid_code` (with `attempts_left`), `code_expired`. "
        "Signs the shopper in (customer tokens).",
    )
    def post(self, request):
        user, tokens = account_services.verify_email(
            request,
            **self.validated(VerifyEmailSerializer),
            realm=UserSession.Realm.CUSTOMER,
        )
        return Response({**tokens, "user": UserSerializer(user).data})


@extend_schema(tags=["marketplace: auth"])
class CustomerLoginView(LoginView):
    realm = UserSession.Realm.CUSTOMER

    @extend_schema(
        operation_id="marketplace_auth_login",
        request=LoginSerializer,
        responses={200: AuthResponseSerializer},
        description="Errors: `invalid_credentials` (401), `email_not_verified` (403). "
        "Refresh with the shared `auth/refresh`.",
    )
    def post(self, request):
        return super().post(request)


@extend_schema(tags=["marketplace: auth"])
class CustomerLogoutView(CustomerMixin, APIView):
    @extend_schema(
        operation_id="marketplace_auth_logout",
        request={
            "application/json": {"type": "object", "properties": {"refresh": {"type": "string"}}}
        },
        responses={204: None},
    )
    def post(self, request):
        account_services.logout(request.data.get("refresh"), getattr(request, "user_session", None))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["marketplace: auth"])
class CustomerPasswordForgotView(PublicAuthView):
    throttle_classes = [AuthIpThrottle, EmailCodeThrottle]

    @extend_schema(
        operation_id="marketplace_auth_password_forgot",
        request=EmailSerializer,
        responses={202: None},
        description="Like `auth/password/forgot`, but the link opens the marketplace: "
        "`{MARKETPLACE_URL}/{lang}/mot-de-passe/nouveau?uid=…&token=…` (30 min). Then the "
        "shared `auth/password/reset`. Always 202.",
    )
    def post(self, request):
        account_services.request_password_reset(self.validated(EmailSerializer)["email"], shop=True)
        return Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["marketplace: auth"])
class CustomerMeView(CustomerMixin, generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


# ---------------------------------------------------------------- Meysara


@extend_schema(tags=["marketplace: orders"])
class MeysaraOfferView(CustomerMixin, APIView):
    @extend_schema(
        operation_id="marketplace_meysara_offer",
        parameters=[MeysaraTotalSerializer],
        responses={200: MeysaraOfferSerializer},
        description="Can the signed-in shopper pay this order total in 4 instalments, and "
        "which shares? Rules in the Meysara spec; `reason` = first rule that fails.",
    )
    def get(self, request):
        query = MeysaraTotalSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        offer = meysara.offer(request.user, query.validated_data["total"])
        return Response(MeysaraOfferSerializer(offer).data)


@extend_schema(tags=["marketplace: orders"])
class MeysaraContractView(CustomerMixin, APIView):
    @extend_schema(
        operation_id="marketplace_meysara_contract",
        request=MeysaraContractRequestSerializer,
        responses={200: MeysaraContractTermsSerializer},
        description="The Meysara contract for this cart and share, in `language`: parties, "
        "items, schedule (days after delivery), plain-language clauses. Show it, let the "
        "shopper tick the box, then send `version` and `digest` back with the order "
        "(`meysara_contract`). Errors: those of the order (`insufficient_stock`…) and "
        "`meysara_not_allowed` (409, with `reason`).",
    )
    def post(self, request):
        serializer = MeysaraContractRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        terms = contract.preview(
            request.user,
            lines=data["lines"],
            percent=data["meysara_percent"],
            language=data["language"],
        )
        return Response(MeysaraContractTermsSerializer(terms).data)


# ---------------------------------------------------------------- e-KYC


def identity_state(customer, code: str | None = None) -> dict:
    verification = IdentityVerification.objects.filter(customer=customer).first()
    return IdentityStateSerializer({"identity": verification, "simulation_code": code}).data


class IdentityCodeThrottle(SimpleRateThrottle):
    """Codes sent to a phone: 5 per hour per shopper."""

    scope = "identity_code"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


IDENTITY_DOC = (
    "e-KYC required before Meysara (BCM Instruction n°13/GR/2025, chapter II). Steps: "
    "`POST marketplace/identity` (details + consent, sends a code to the phone) → "
    "`POST marketplace/identity/phone/verify` → `POST marketplace/identity/documents` "
    "(ID card front and back + live selfie). `identity.status`: `phone_pending` · "
    "`documents_pending` · `verified` · `rejected` (start again). The provider is simulated "
    "for now: `simulation_code` carries the SMS code, and NNIs starting with `000` are "
    "rejected (`reject_reason` `document_unreadable`)."
)


@extend_schema(tags=["marketplace: identity"])
class IdentityView(CustomerMixin, APIView):
    def get_throttles(self):
        if self.request.method == "POST":
            return [*super().get_throttles(), IdentityCodeThrottle()]
        return super().get_throttles()

    @extend_schema(
        operation_id="marketplace_identity_get",
        responses={200: IdentityStateSerializer},
        description=IDENTITY_DOC,
    )
    def get(self, request):
        return Response(identity_state(request.user))

    @extend_schema(
        operation_id="marketplace_identity_start",
        request=IdentityStartSerializer,
        responses={200: IdentityStateSerializer},
        description="Starts or restarts the check and sends a code to `phone` (10 min, 3 "
        "attempts; 5 codes per hour). Errors (with `field`): `consent_required`, `invalid_nni`, "
        "`invalid_phone`, `underage` (18+); `nni_already_used` (409), "
        "`identity_already_verified` (409).",
    )
    def post(self, request):
        serializer = IdentityStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, code = kyc.start(request.user, **serializer.validated_data)
        return Response(identity_state(request.user, code))


@extend_schema(tags=["marketplace: identity"])
class IdentityResendView(CustomerMixin, APIView):
    def get_throttles(self):
        return [*super().get_throttles(), IdentityCodeThrottle()]

    @extend_schema(
        operation_id="marketplace_identity_phone_resend",
        request=None,
        responses={200: IdentityStateSerializer},
        description="A new code to the same phone. Errors: `identity_not_started`, "
        "`identity_step_done` (409).",
    )
    def post(self, request):
        _, code = kyc.resend_code(request.user)
        return Response(identity_state(request.user, code))


@extend_schema(tags=["marketplace: identity"])
# Outside the request transaction, so that a wrong code stays counted (see kyc.verify_phone).
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class IdentityVerifyPhoneView(CustomerMixin, APIView):
    @extend_schema(
        operation_id="marketplace_identity_phone_verify",
        request=IdentityCodeSerializer,
        responses={200: IdentityStateSerializer},
        description="Errors: `invalid_code` (with `attempts_left`), `code_expired`, "
        "`identity_not_started`, `identity_step_done` (409).",
    )
    def post(self, request):
        serializer = IdentityCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kyc.verify_phone(request.user, serializer.validated_data["code"])
        return Response(identity_state(request.user))


@extend_schema(tags=["marketplace: identity"])
class IdentityDocumentsView(CustomerMixin, APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        operation_id="marketplace_identity_documents",
        request={"multipart/form-data": IdentityDocumentsSerializer},
        responses={200: IdentityStateSerializer},
        description="The provider checks the ID card (front, and back when sent), matches the "
        "face and runs a liveness check; the photos are not kept. Ends in `verified` or "
        "`rejected`. Errors (with `field`): `unsupported_file_type`, `file_too_large`; "
        "`identity_not_started`, `identity_wrong_step` (409), `nni_already_used` (409).",
    )
    def post(self, request):
        serializer = IdentityDocumentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kyc.check_documents(request.user, **serializer.validated_data)
        return Response(identity_state(request.user))


# ---------------------------------------------------------------- customer orders


@extend_schema(tags=["marketplace: orders"])
class CustomerOrderViewSet(
    CustomerMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """The shopper's own orders. Payment on delivery."""

    serializer_class = OrderSerializer
    filterset_fields = ["status"]

    queryset = Order.objects.none()  # for the schema; see get_queryset

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        return (
            Order.objects.filter(customer=self.request.user)
            .select_related("meysara_plan__contract")
            .prefetch_related("lines", "meysara_plan__instalments")
        )

    @extend_schema(
        operation_id="marketplace_orders_create",
        request=OrderCreateSerializer,
        responses={201: OrderSerializer},
        description="Each line goes to the cheapest store able to serve it; prices are "
        "fixed now. `payment_method=meysara` with `meysara_percent` (one of the offer's "
        "`choices`) reserves a pay-in-4 plan. Errors: `empty_cart`, `insufficient_stock` "
        "(409, with `field`, `available`), `invalid_quantity`, `whole_quantity_required`, "
        "`meysara_percent_required`, `meysara_not_allowed` (409, with `reason`), "
        "`meysara_contract_required` (no accepted contract), `meysara_contract_outdated` "
        "(409: prices, items or text changed since it was read; fetch it again).",
    )
    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines, note = data.pop("lines"), data.pop("note", "")
        order = services.place_order(
            request.user,
            lines=lines,
            delivery=data,
            note=note,
            payment_method=data.pop("payment_method"),
            meysara_percent=data.pop("meysara_percent", None),
            meysara_contract=data.pop("meysara_contract", None),
            request=request,
        )
        return Response(
            OrderSerializer(self.get_queryset().get(pk=order.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="marketplace_orders_meysara_contract",
        request=None,
        responses={200: MeysaraSignedContractSerializer},
        description="The Meysara contract the shopper signed for this order, as shown then. "
        "Errors: `no_meysara_contract` (404: paid on delivery, or booked before contracts).",
    )
    @action(detail=True, methods=["get"], url_path="meysara/contract")
    def meysara_contract(self, request, pk=None):
        order = self.get_object()
        signed = getattr(getattr(order, "meysara_plan", None), "contract", None)
        if signed is None:
            raise ApiError(
                "no_meysara_contract", "This order has no Meysara contract.", status_code=404
            )
        return Response(MeysaraSignedContractSerializer(signed).data)

    @extend_schema(
        operation_id="marketplace_orders_cancel",
        request=None,
        responses={200: OrderSerializer},
        description="While `pending` or `confirmed`. Errors: `order_not_cancellable` (409).",
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(OrderSerializer(services.cancel_by_customer(self.get_object())).data)


# ---------------------------------------------------------------- stores (ERP)


@extend_schema(tags=["stores: marketplace"])
class StoreOrderViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Marketplace orders for this store: accept (takes stock out), reject, mark ready."""

    serializer_class = StoreOrderSerializer
    filterset_fields = ["status"]
    required_permissions = {"*": Perm.MARKETPLACE_ORDERS}

    def get_queryset(self):
        return StoreOrder.objects.select_related("order").prefetch_related(
            "lines__order_line", "lines__store_product__variant__product__category"
        )

    @extend_schema(
        operation_id="stores_marketplace_orders_accept",
        request=AcceptSerializer,
        responses={200: StoreOrderSerializer},
        description="Takes the goods out of stock. Lines of products with serial numbers "
        "need `serials` (one per unit). Errors: `store_order_not_pending`, `order_cancelled`, "
        "`insufficient_stock`, `serial_not_in_stock` (409); `serials_required` (400).",
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, store_id=None, pk=None):
        serializer = AcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serials = {
            line["id"]: line["serials"] for line in serializer.validated_data.get("lines", [])
        }
        store_order = services.accept(request, self.get_object(), serials)
        return Response(StoreOrderSerializer(self.get_queryset().get(pk=store_order.pk)).data)

    @extend_schema(
        operation_id="stores_marketplace_orders_reject",
        request=ReasonSerializer,
        responses={200: StoreOrderSerializer},
        description="Cancels the whole customer order. Errors: `store_order_not_pending` (409).",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, store_id=None, pk=None):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store_order = services.reject(
            request, self.get_object(), serializer.validated_data["reason"]
        )
        return Response(StoreOrderSerializer(self.get_queryset().get(pk=store_order.pk)).data)

    @extend_schema(
        operation_id="stores_marketplace_orders_ready",
        request=None,
        responses={200: StoreOrderSerializer},
        description="Packed, waiting for Mahali. Errors: `store_order_not_accepted` (409).",
    )
    @action(detail=True, methods=["post"])
    def ready(self, request, store_id=None, pk=None):
        store_order = services.mark_ready(request, self.get_object())
        return Response(StoreOrderSerializer(self.get_queryset().get(pk=store_order.pk)).data)


# ---------------------------------------------------------------- console


@extend_schema(tags=["console: marketplace"])
class ConsoleOrderViewSet(ConsoleMixin, MarketplaceReadMixin, viewsets.ReadOnlyModelViewSet):
    """Every marketplace order with the stores serving it (where to pick up)."""

    serializer_class = ConsoleOrderSerializer
    console_permissions = {"GET": "marketplace.view", "*": "marketplace.manage"}
    filterset_fields = ["status"]
    search_fields = ["number", "customer__email", "delivery_phone", "delivery_name"]

    def get_queryset(self):
        return Order.objects.select_related("customer", "meysara_plan__contract").prefetch_related(
            "lines",
            "meysara_plan__instalments",
            "store_orders__store",
            "store_orders__lines__order_line",
            "store_orders__lines__store_product__variant__product__category",
        )

    def _respond(self, order):
        return Response(ConsoleOrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @extend_schema(
        operation_id="console_marketplace_orders_deliver",
        request=None,
        responses={200: ConsoleOrderSerializer},
        description="Every store part was picked up and the customer got the order. "
        "Errors: `order_not_ready` (409).",
    )
    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        order = services.deliver(self.get_object(), request.user)
        return self._respond(order)

    @extend_schema(
        operation_id="console_marketplace_orders_meysara_pay",
        request=PayInstalmentSerializer,
        responses={200: ConsoleOrderSerializer},
        description="Records a Meysara instalment the shopper paid. The last one closes the "
        "plan. Errors: `not_a_meysara_order`, `meysara_plan_not_active` (409, before "
        "delivery), `invalid_instalment`, `instalment_already_paid` (409).",
    )
    @action(detail=True, methods=["post"], url_path="meysara/pay")
    def meysara_pay(self, request, pk=None):
        serializer = PayInstalmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meysara.pay(self.get_object(), actor=request.user, **serializer.validated_data)
        return self._respond(self.get_object())

    @extend_schema(
        operation_id="console_marketplace_orders_cancel",
        request=ReasonSerializer,
        responses={200: ConsoleOrderSerializer},
        description="Puts back in stock what stores had taken out. "
        "Errors: `order_not_cancellable` (409).",
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.cancel_order(
            self.get_object(), reason=serializer.validated_data["reason"], actor=request.user
        )
        return self._respond(order)
