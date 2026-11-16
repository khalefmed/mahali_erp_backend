from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import selectors, services
from .models import SupplierPayment
from .serializers import (
    ClosingSerializer,
    JournalDaySerializer,
    JournalQuerySerializer,
    PeriodQuerySerializer,
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
