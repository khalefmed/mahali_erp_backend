from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import selectors, services
from .models import ExpenseBudget, RecurringExpense, SupplierPayment
from .serializers import (
    ClosingSerializer,
    ExpenseBudgetListSerializer,
    ExpenseBudgetSerializer,
    JournalDaySerializer,
    JournalQuerySerializer,
    MoneyAccountListSerializer,
    MoneyMovementListSerializer,
    MoneyMovementQuerySerializer,
    MoneyMovementSerializer,
    MoneyTransferSerializer,
    PeriodQuerySerializer,
    RecurringExpenseListSerializer,
    RecurringExpenseSerializer,
    SupplierPaymentSerializer,
)


@extend_schema(tags=["stores: suppliers"])
class SupplierPaymentViewSet(
    StoreScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Règlements fournisseurs. A cash payment needs my open till (`no_open_cash_session`)."""

    serializer_class = SupplierPaymentSerializer
    filterset_fields = ["supplier", "method"]
    required_permissions = {"GET": Perm.SUPPLIERS_MANAGE, "POST": Perm.SUPPLIERS_MANAGE}

    def get_queryset(self):
        return SupplierPayment.objects.select_related("supplier", "created_by")

    def perform_create(self, serializer):
        serializer.instance = services.record_supplier_payment(
            self.request, **serializer.validated_data
        )


@extend_schema(tags=["stores: accounting"])
class JournalView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_accounting_journal",
        parameters=[JournalQuerySerializer],
        responses={200: JournalDaySerializer},
        description="Entries posted automatically on one day (sales, payments, credit notes, "
        "expenses, receipts, supplier payments), SYSCOHADA accounts.",
    )
    def get(self, request, store_id):
        query = JournalQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        day = query.validated_data.get("date") or timezone.localdate()
        return Response(JournalDaySerializer(selectors.journal(day)).data)


@extend_schema(tags=["stores: accounting"])
class ClosingView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_accounting_closing",
        parameters=[PeriodQuerySerializer],
        responses={200: ClosingSerializer},
        description="Month closing checklist and VAT declaration. Purchase VAT and bank "
        "statements are not recorded yet: `vat_deductible` is 0, the bank never reconciled.",
    )
    def get(self, request, store_id):
        query = PeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = selectors.closing(query.validated_data["date_from"], query.validated_data["date_to"])
        return Response(ClosingSerializer(data).data)


# ---------------------------------------------------------------- treasury


@extend_schema(tags=["stores: treasury"])
class MoneyAccountListView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_money_accounts_list",
        responses={200: MoneyAccountListSerializer},
        description="One account per payment method (till, Bankily, Masrvi, Sedad, bank).",
    )
    def get(self, request, store_id):
        return Response({"results": selectors.money_accounts()})


@extend_schema(tags=["stores: treasury"])
class MoneyMovementListView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_money_movements_list",
        parameters=[MoneyMovementQuerySerializer],
        responses={200: MoneyMovementListSerializer},
        description="Every flow of one day on the accounts: payments, refunds, expenses, "
        "supplier payments, transfers (two rows each).",
    )
    def get(self, request, store_id):
        query = MoneyMovementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        day = query.validated_data.get("date") or timezone.localdate()
        rows = MoneyMovementSerializer(selectors.money_movements(day), many=True).data
        return Response({"results": rows})


@extend_schema(tags=["stores: treasury"])
class MoneyTransferView(StoreScopedViewMixin, APIView):
    required_permissions = {"POST": Perm.STORE_MANAGE}

    @extend_schema(
        operation_id="stores_money_transfers_create",
        request=MoneyTransferSerializer,
        responses={201: MoneyTransferSerializer},
        description="Move money between two accounts (`same_account` when they're equal).",
    )
    def post(self, request, store_id):
        body = MoneyTransferSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        transfer = services.transfer_money(request, **body.validated_data)
        return Response(MoneyTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- expenses


@extend_schema(tags=["stores: expenses"])
class RecurringExpenseViewSet(
    StoreScopedViewMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Charges fixes. `post_recurring_expenses` (daily) records the due ones; variable
    bills wait for the real amount."""

    serializer_class = RecurringExpenseSerializer
    required_permissions = {"GET": Perm.EXPENSES_MANAGE, "*": Perm.EXPENSES_MANAGE}

    def get_queryset(self):
        return RecurringExpense.objects.all()

    @extend_schema(
        operation_id="stores_recurring_expenses_list",
        responses={200: RecurringExpenseListSerializer},
    )
    def list(self, request, store_id):
        return Response(
            {"results": RecurringExpenseSerializer(self.get_queryset(), many=True).data}
        )

    def perform_create(self, serializer):
        serializer.instance = services.add_recurring_expense(
            self.request, **serializer.validated_data
        )


@extend_schema(tags=["stores: expenses"])
class ExpenseBudgetView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW, "PUT": Perm.STORE_MANAGE}

    def _list(self):
        return {"results": ExpenseBudgetSerializer(ExpenseBudget.objects.all(), many=True).data}

    @extend_schema(
        operation_id="stores_expense_budgets_list",
        responses={200: ExpenseBudgetListSerializer},
        description="Monthly budget per expense category.",
    )
    def get(self, request, store_id):
        return Response(self._list())

    @extend_schema(
        operation_id="stores_expense_budgets_update",
        request=ExpenseBudgetListSerializer,
        responses={200: ExpenseBudgetListSerializer},
        description="Replace all budgets (owner). A category left out has no budget.",
    )
    def put(self, request, store_id):
        body = ExpenseBudgetListSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.set_budgets(request.store, body.validated_data["results"])
        return Response(self._list())
