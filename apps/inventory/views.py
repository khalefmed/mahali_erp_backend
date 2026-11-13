from django.db import IntegrityError
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action

from apps.core.exceptions import ApiError, Conflict, Forbidden
from apps.stores.access import StoreScopedViewMixin, has_perm
from apps.stores.roles import Perm

from . import services
from .filters import StockMovementFilter, StoreProductFilter
from .models import Receipt, SerialUnit, StockAdjustment, StockMovement, StoreProduct, Supplier
from .serializers import (
    ReceiptSerializer,
    SerialUnitSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    StoreProductSerializer,
    SupplierSerializer,
)


@extend_schema(tags=["stores: products & stock"])
class StoreProductViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The store's products: a catalog variant + price + stock. Add one with `variant_id`
    from `catalog/products`. Stock changes only through receipts, sales and adjustments."""

    serializer_class = StoreProductSerializer
    filterset_class = StoreProductFilter
    ordering_fields = ["sale_price", "quantity", "created_at"]
    http_method_names = ["get", "post", "patch"]
    required_permissions = {
        "GET": Perm.PRODUCTS_VIEW,
        "POST": Perm.PRODUCTS_MANAGE,
        "PATCH": Perm.PRODUCTS_MANAGE,
    }

    def get_queryset(self):
        return StoreProduct.objects.select_related(
            "variant__product__category", "variant__product__brand"
        ).order_by("variant__product__name", "variant__name")

    def perform_create(self, serializer):
        variant = serializer.validated_data["variant"]
        if variant.product.category.trade != self.store.trade:
            raise ApiError("wrong_trade", "This product is not in your store's trade.")
        if "warranty_months" not in serializer.validated_data:
            serializer.validated_data["warranty_months"] = (
                variant.product.category.default_warranty_months
            )
        try:
            serializer.save(store=self.store)
        except IntegrityError as exc:
            raise Conflict(
                "product_already_added", "This product is already in your store."
            ) from exc

    def perform_update(self, serializer):
        if "sale_price" in serializer.validated_data and not has_perm(
            self.request, Perm.PRICES_EDIT
        ):
            raise Forbidden(
                "permission_denied",
                "Missing permission prices.edit.",
                extra={"permission": Perm.PRICES_EDIT},
            )
        serializer.save()

    @extend_schema(
        operation_id="stores_products_movements",
        responses={200: StockMovementSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def movements(self, request, store_id=None, pk=None):
        queryset = StockMovement.objects.filter(store_product=self.get_object()).select_related(
            "created_by", "store_product__variant__product"
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(StockMovementSerializer(page, many=True).data)


@extend_schema(tags=["stores: products & stock"])
class SerialUnitViewSet(StoreScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Units with an IMEI / serial. At the till, `?serial=<scanned>` finds the unit."""

    serializer_class = SerialUnitSerializer
    filterset_fields = ["status", "store_product", "serial"]
    required_permissions = {"*": Perm.PRODUCTS_VIEW}

    def get_queryset(self):
        return SerialUnit.objects.select_related("store_product__variant__product").order_by(
            "-created_at"
        )


@extend_schema(tags=["stores: products & stock"])
class StockMovementViewSet(StoreScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Stock journal (append-only)."""

    serializer_class = StockMovementSerializer
    filterset_class = StockMovementFilter
    required_permissions = {"*": Perm.PRODUCTS_VIEW}

    def get_queryset(self):
        return StockMovement.objects.select_related("created_by", "store_product__variant__product")


@extend_schema(tags=["stores: purchasing"])
class SupplierViewSet(StoreScopedViewMixin, viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    search_fields = ["name", "phone"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "post", "patch"]
    required_permissions = {"GET": Perm.PRODUCTS_VIEW, "*": Perm.SUPPLIERS_MANAGE}

    def get_queryset(self):
        return Supplier.objects.all()

    def perform_create(self, serializer):
        serializer.save(store=self.store)


@extend_schema(tags=["stores: purchasing"])
class ReceiptViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Receive goods: adds stock, registers serials, updates the average cost.
    Errors: `serials_required`, `serial_exists`, `duplicate_serial`."""

    serializer_class = ReceiptSerializer
    filterset_fields = ["supplier"]
    required_permissions = {"GET": Perm.COSTS_VIEW, "POST": Perm.STOCK_RECEIVE}

    def get_queryset(self):
        return Receipt.objects.select_related("supplier").prefetch_related(
            "lines__store_product__variant__product", "lines__serial_units"
        )

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.receive(
            self.store,
            self.request.user,
            lines=data["lines"],
            supplier=data.get("supplier"),
            supplier_reference=data.get("supplier_reference", ""),
            note=data.get("note", ""),
        )


@extend_schema(tags=["stores: products & stock"])
class StockAdjustmentViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Inventory counts, damage, loss, initial stock. Give `counted_quantity` (what is on
    the shelf) or `quantity_delta`. Serial products need the `serials` concerned."""

    serializer_class = StockAdjustmentSerializer
    filterset_fields = ["reason", "store_product"]
    required_permissions = {"GET": Perm.PRODUCTS_VIEW, "POST": Perm.STOCK_ADJUST}

    def get_queryset(self):
        return StockAdjustment.objects.select_related("store_product__variant__product")

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        serializer.instance = services.adjust(self.store, self.request.user, **data)
