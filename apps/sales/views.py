from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import services
from .filters import CreditFilter, CustomerFilter, ExpenseFilter, SaleFilter
from .models import CashSession, Credit, CreditNote, Customer, Expense, Sale
from .serializers import (
    CashSessionSerializer,
    CloseSessionSerializer,
    CreditNoteSerializer,
    CreditSerializer,
    CustomerSerializer,
    ExpenseSerializer,
    PaymentSerializer,
    RepaymentSerializer,
    SaleCreateSerializer,
    SaleListSerializer,
    SaleSerializer,
)


@extend_schema(tags=["stores: customers"])
class CustomerViewSet(StoreScopedViewMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    filterset_class = CustomerFilter
    http_method_names = ["get", "post", "patch"]
    required_permissions = {"GET": Perm.CUSTOMERS_VIEW, "*": Perm.CUSTOMERS_MANAGE}

    def get_queryset(self):
        return Customer.objects.annotate(
            credit_balance=Coalesce(
                Sum("credits__balance", filter=Q(credits__status=Credit.Status.OPEN)), Value(0)
            )
        )

    def perform_create(self, serializer):
        serializer.save(store=self.store)


@extend_schema(tags=["stores: till & sales"])
class CashSessionViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Open a till (POST with `opening_float`), sell, then close it with the cash count."""

    serializer_class = CashSessionSerializer
    filterset_fields = ["status", "opened_by"]
    required_permissions = {"*": Perm.CASH_SESSION}

    def get_queryset(self):
        return CashSession.objects.select_related("opened_by", "closed_by")

    def perform_create(self, serializer):
        serializer.instance = services.open_session(
            self.store, self.request.user, serializer.validated_data.get("opening_float", 0)
        )

    @extend_schema(
        operation_id="stores_cash_sessions_current",
        responses={200: CashSessionSerializer(allow_null=True)},
        description="My open till, or null.",
    )
    @action(detail=False, methods=["get"], required_permissions={"*": Perm.SALES_CREATE})
    def current(self, request, store_id=None):
        session = services.my_open_session(self.store, request.user)
        return Response(CashSessionSerializer(session).data if session else None)

    @extend_schema(
        operation_id="stores_cash_sessions_close",
        request=CloseSessionSerializer,
        responses={200: CashSessionSerializer},
    )
    @action(detail=True, methods=["post"])
    def close(self, request, store_id=None, pk=None):
        serializer = CloseSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.close_session(
            request,
            self.get_object(),
            serializer.validated_data["counted_cash"],
            serializer.validated_data.get("note", ""),
        )
        return Response(CashSessionSerializer(session).data)


@extend_schema(tags=["stores: till & sales"])
class SaleViewSet(
    StoreScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    filterset_class = SaleFilter
    required_permissions = {"GET": Perm.SALES_VIEW, "POST": Perm.SALES_CREATE}

    def get_queryset(self):
        queryset = Sale.objects.select_related("customer", "seller", "credit")
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("lines__serial_unit", "payments")
        return queryset

    def get_serializer_class(self):
        return SaleSerializer if self.action == "retrieve" else SaleListSerializer

    @extend_schema(
        operation_id="stores_sales_create",
        request=SaleCreateSerializer,
        responses={201: SaleSerializer},
        description="Prices come from the store product. Unpaid remainder becomes a credit "
        "(needs `customer`). Errors: `no_open_cash_session`, `insufficient_stock`, "
        "`serial_required`, `serial_not_in_stock`, `discount_requires_approval`, `overpaid`, "
        "`customer_required_for_credit`.",
    )
    def create(self, request, store_id=None):
        serializer = SaleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = services.create_sale(request, **serializer.validated_data)
        sale = (
            self.get_queryset().prefetch_related("lines__serial_unit", "payments").get(pk=sale.pk)
        )
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["stores: till & sales"])
class CreditNoteViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Avoirs: return items of a sale and refund (or reduce the customer's credit)."""

    serializer_class = CreditNoteSerializer
    filterset_fields = ["sale"]
    required_permissions = {"GET": Perm.SALES_VIEW, "POST": Perm.SALES_REFUND}

    def get_queryset(self):
        return CreditNote.objects.select_related("sale").prefetch_related("lines__sale_line")

    def perform_create(self, serializer):
        serializer.instance = services.create_credit_note(self.request, **serializer.validated_data)


@extend_schema(tags=["stores: credits"])
class CreditViewSet(StoreScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CreditSerializer
    filterset_class = CreditFilter
    required_permissions = {"GET": Perm.CUSTOMERS_VIEW, "POST": Perm.CREDITS_MANAGE}

    def get_queryset(self):
        return Credit.objects.select_related("customer", "sale")

    @extend_schema(
        operation_id="stores_credits_repay",
        request=RepaymentSerializer,
        responses={201: PaymentSerializer},
    )
    @action(detail=True, methods=["post"])
    def repay(self, request, store_id=None, pk=None):
        serializer = RepaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.repay_credit(request, self.get_object(), **serializer.validated_data)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["stores: expenses"])
class ExpenseViewSet(
    StoreScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilter
    required_permissions = {"GET": Perm.REPORTS_VIEW, "POST": Perm.EXPENSES_MANAGE}

    def get_queryset(self):
        return Expense.objects.select_related("created_by")

    def perform_create(self, serializer):
        serializer.instance = services.record_expense(self.request, **serializer.validated_data)
