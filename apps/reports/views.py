from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import selectors
from .serializers import SummaryQuerySerializer, SummarySerializer


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
