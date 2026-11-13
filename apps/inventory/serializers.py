from decimal import Decimal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Variant
from apps.stores.access import has_perm
from apps.stores.roles import Perm

from .models import (
    AdjustmentReason,
    Receipt,
    ReceiptLine,
    SerialUnit,
    StockAdjustment,
    StockMovement,
    StoreProduct,
    Supplier,
)

QTY = {"max_digits": 12, "decimal_places": 3}


class CatalogVariantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    full_name = serializers.CharField()
    barcode = serializers.CharField(allow_null=True)
    attributes = serializers.DictField()
    product_id = serializers.UUIDField(source="product.id")
    product_name = serializers.CharField(source="product.name")
    product_name_ar = serializers.CharField(source="product.name_ar")
    brand_name = serializers.CharField(source="product.brand.name", default=None)
    category_id = serializers.UUIDField(source="product.category.id")
    category_name = serializers.CharField(source="product.category.name")
    image_url = serializers.CharField(source="product.image_url")
    tracks_serial = serializers.BooleanField(source="product.category.tracks_serial")


class StoreProductSerializer(serializers.ModelSerializer):
    """`avg_cost` and `stock_value` are null for roles without costs.view."""

    variant = CatalogVariantSerializer(read_only=True)
    variant_id = serializers.PrimaryKeyRelatedField(
        queryset=Variant.objects.filter(is_active=True, product__status="active"),
        source="variant",
        write_only=True,
    )
    avg_cost = serializers.IntegerField(read_only=True, allow_null=True)
    stock_value = serializers.SerializerMethodField()
    low_stock = serializers.SerializerMethodField()

    class Meta:
        model = StoreProduct
        fields = [
            "id",
            "variant",
            "variant_id",
            "condition",
            "sale_price",
            "quantity",
            "avg_cost",
            "stock_value",
            "warranty_months",
            "reorder_level",
            "low_stock",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "quantity", "created_at"]

    def get_stock_value(self, obj) -> int | None:
        if not self._can_see_costs():
            return None
        return int(obj.avg_cost * obj.quantity)

    def get_low_stock(self, obj) -> bool:
        return obj.quantity <= obj.reorder_level

    def _can_see_costs(self) -> bool:
        request = self.context.get("request")
        return request is not None and has_perm(request, Perm.COSTS_VIEW)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._can_see_costs():
            data["avg_cost"] = None
        return data

    def validate(self, attrs):
        if self.instance and "variant" in attrs and attrs["variant"] != self.instance.variant:
            raise serializers.ValidationError(
                {"variant_id": "Cannot change the variant."}, code="immutable"
            )
        if self.instance and "condition" in attrs and attrs["condition"] != self.instance.condition:
            raise serializers.ValidationError(
                {"condition": "Cannot change the condition."}, code="immutable"
            )
        return attrs


class SerialUnitSerializer(serializers.ModelSerializer):
    store_product_id = serializers.UUIDField(source="store_product.id", read_only=True)
    product_name = serializers.CharField(source="store_product.variant.full_name", read_only=True)
    condition = serializers.CharField(source="store_product.condition", read_only=True)
    sale_price = serializers.IntegerField(source="store_product.sale_price", read_only=True)

    class Meta:
        model = SerialUnit
        fields = [
            "id",
            "serial",
            "status",
            "store_product_id",
            "product_name",
            "condition",
            "sale_price",
            "created_at",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="store_product.variant.full_name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "store_product",
            "product_name",
            "kind",
            "quantity",
            "unit_cost",
            "balance_after",
            "reference",
            "serial",
            "note",
            "created_by_name",
            "created_at",
        ]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "phone", "email", "address", "note", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


@extend_schema_field(OpenApiTypes.UUID)
class StoreProductField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return StoreProduct.objects.all()  # RLS limits this to the current store


class ReceiptLineSerializer(serializers.ModelSerializer):
    store_product = StoreProductField()
    product_name = serializers.CharField(source="store_product.variant.full_name", read_only=True)
    quantity = serializers.DecimalField(min_value=Decimal("0.001"), **QTY)
    unit_cost = serializers.IntegerField(min_value=0)
    serials = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        write_only=True,
        help_text="One per unit, for products that track serials",
    )
    serial_numbers = serializers.SerializerMethodField()

    class Meta:
        model = ReceiptLine
        fields = [
            "id",
            "store_product",
            "product_name",
            "quantity",
            "unit_cost",
            "line_total",
            "serials",
            "serial_numbers",
        ]
        read_only_fields = ["id", "line_total"]

    def get_serial_numbers(self, obj) -> list[str]:
        return [u.serial for u in obj.serial_units.all()]


@extend_schema_field(OpenApiTypes.UUID)
class SupplierField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Supplier.objects.filter(is_active=True)


class ReceiptSerializer(serializers.ModelSerializer):
    supplier = SupplierField(required=False, allow_null=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    lines = ReceiptLineSerializer(many=True)

    class Meta:
        model = Receipt
        fields = [
            "id",
            "number",
            "supplier",
            "supplier_name",
            "supplier_reference",
            "note",
            "total_cost",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "number", "total_cost", "created_at"]

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one line.", code="required")
        return value


class StockAdjustmentSerializer(serializers.ModelSerializer):
    store_product = StoreProductField()
    product_name = serializers.CharField(source="store_product.variant.full_name", read_only=True)
    quantity_delta = serializers.DecimalField(required=False, **QTY)
    counted_quantity = serializers.DecimalField(required=False, write_only=True, min_value=0, **QTY)
    reason = serializers.ChoiceField(choices=AdjustmentReason.choices)
    unit_cost = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "number",
            "store_product",
            "product_name",
            "quantity_delta",
            "counted_quantity",
            "unit_cost",
            "reason",
            "note",
            "serials",
            "created_at",
        ]
        read_only_fields = ["id", "number", "created_at"]

    def validate(self, attrs):
        if ("quantity_delta" in attrs) == ("counted_quantity" in attrs):
            raise serializers.ValidationError(
                "Give either quantity_delta or counted_quantity.", code="invalid"
            )
        return attrs
