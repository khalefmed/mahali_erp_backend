from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.parsers import JSONParser, MultiPartParser

from apps.stores.access import StoreScopedViewMixin
from apps.stores.roles import Perm

from . import services
from .filters import ProductFilter
from .models import Brand, Category, Product, ProductRequest, ProductStatus
from .serializers import (
    BrandSerializer,
    CatalogProductSerializer,
    CategorySerializer,
    ProductRequestSerializer,
)


@extend_schema(tags=["catalog"])
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Mahali categories with their attribute schema (drives forms and filters)."""

    serializer_class = CategorySerializer
    pagination_class = None
    filterset_fields = ["trade", "parent"]

    def get_queryset(self):
        return Category.objects.filter(is_active=True)


@extend_schema(tags=["catalog"])
class BrandViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BrandSerializer
    pagination_class = None
    queryset = Brand.objects.all()


@extend_schema(tags=["catalog"])
class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Search the Mahali catalog to add a product to a store (`stores/{id}/products`)."""

    serializer_class = CatalogProductSerializer
    filterset_class = ProductFilter

    def get_queryset(self):
        return (
            Product.objects.filter(status=ProductStatus.ACTIVE)
            .select_related("category", "brand")
            .prefetch_related("variants")
        )


@extend_schema(tags=["stores: catalog requests"])
class ProductRequestViewSet(
    StoreScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """'Demander un produit' when a product is missing from the catalog."""

    serializer_class = ProductRequestSerializer
    parser_classes = [JSONParser, MultiPartParser]
    required_permissions = {"*": Perm.PRODUCTS_VIEW, "create": Perm.PRODUCT_REQUESTS_CREATE}
    filterset_fields = ["status"]

    def get_queryset(self):
        return ProductRequest.objects.filter(store=self.store).select_related("store", "variant")

    def perform_create(self, serializer):
        serializer.instance = services.create_product_request(
            self.request, self.store, dict(serializer.validated_data)
        )
