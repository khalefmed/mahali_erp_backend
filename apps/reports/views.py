from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import selectors
from .serializers import (
    MemberActivityListSerializer,
    MemberActivitySerializer,
    ReportDetailsSerializer,
    SellerPerformanceQuerySerializer,
    SellerPerformanceSerializer,
    SummaryQuerySerializer,
    SummarySerializer,
)


@extend_schema(tags=["stores: reports"])
class SummaryView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_reports_summary",
        parameters=[SummaryQuerySerializer],
        responses={200: SummarySerializer},
        description="Dashboard and day / week / month reports. Without dates: today.",
    )
    def get(self, request, store_id):
        query = SummaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = selectors.summary(query.validated_data["date_from"], query.validated_data["date_to"])
        return Response(SummarySerializer(data).data)


@extend_schema(tags=["stores: reports"])
class DetailsView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.REPORTS_VIEW}

    @extend_schema(
        operation_id="stores_reports_details",
        parameters=[SummaryQuerySerializer],
        responses={200: ReportDetailsSerializer},
        description="Sales by category (VAT excluded), dormant stock, supplier payables.",
    )
    def get(self, request, store_id):
        query = SummaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = selectors.details(query.validated_data["date_from"], query.validated_data["date_to"])
        return Response(ReportDetailsSerializer(data).data)


@extend_schema(tags=["stores: team"])
class MemberActivityView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.MEMBERS_MANAGE}

    @extend_schema(
        operation_id="stores_member_activity",
        responses={200: MemberActivityListSerializer},
        description="Presence of each active member (last session seen, open till).",
    )
    def get(self, request, store_id):
        return Response(
            {
                "results": MemberActivitySerializer(
                    selectors.member_activity(request.store), many=True
                ).data
            }
        )


@extend_schema(tags=["stores: reports"])
class SellerPerformanceView(StoreScopedViewMixin, APIView):
    required_permissions = {"GET": Perm.SALES_CREATE}

    @extend_schema(
        operation_id="stores_seller_performance_me",
        parameters=[SellerPerformanceQuerySerializer],
        responses={200: SellerPerformanceSerializer},
        description="My collected sales of the month in this store and the sellers ranking. "
        "Commissions and targets aren't configured yet (rate 0, target null).",
    )
    def get(self, request, store_id):
        query = SellerPerformanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        month = query.validated_data.get("month")
        day = date.fromisoformat(f"{month}-01") if month else timezone.localdate()
        data = selectors.seller_performance(request.store, request.user, day)
        return Response(SellerPerformanceSerializer(data).data)
