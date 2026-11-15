from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.catalog.models import Brand, Category, Product, Variant

from .models import Order, OrderLine, OrderStatus, StoreOrder, StoreOrderLine, StoreOrderStatus

QUANTITY = {"max_digits": 12, "decimal_places": 3, "min_value": 0}

# ---------------------------------------------------------------- shop window (public)


class ShopBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug"]


class ShopCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True, help_text="Products in stock")

    class Meta:
        model = Category
        fields = ["id", "trade", "parent", "name", "name_ar", "slug", "product_count"]


class ShopCategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "trade", "name", "name_ar", "slug"]


class ShopProductSerializer(serializers.ModelSerializer):
    brand = ShopBrandSerializer(allow_null=True)
    category = ShopCategoryRefSerializer()
    price = serializers.IntegerField(help_text="MRU, lowest price of the product (from …)")

    class Meta:
        model = Product
        fields = ["id", "name", "name_ar", "brand", "category", "image_url", "price"]


class ShopVariantSerializer(serializers.ModelSerializer):
    price = serializers.IntegerField(allow_null=True, help_text="MRU; null when out of stock")
    available = serializers.SerializerMethodField()
    max_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, help_text="Most you can order"
    )
    warranty_months = serializers.IntegerField(source="warranty", allow_null=True)

    class Meta:
        model = Variant
        fields = [
            "id",
            "name",
            "full_name",
            "attributes",
            "price",
            "available",
            "max_quantity",
            "warranty_months",
        ]

    def get_available(self, obj) -> bool:
        return obj.price is not None


class ShopProductDetailSerializer(ShopProductSerializer):
    attribute_schema = serializers.JSONField(source="category.attribute_schema")
    tracks_serial = serializers.BooleanField(source="category.tracks_serial")
    variants = serializers.SerializerMethodField()

    class Meta(ShopProductSerializer.Meta):
        fields = [
            *ShopProductSerializer.Meta.fields,
            "description",
            "attributes",
            "attribute_schema",
            "tracks_serial",
            "variants",
        ]

    def get_variants(self, obj) -> ShopVariantSerializer(many=True):
        return ShopVariantSerializer(self.context["variants"], many=True).data


# ---------------------------------------------------------------- cart and orders (customer)


class CartLineSerializer(serializers.Serializer):
    variant = serializers.PrimaryKeyRelatedField(
        queryset=Variant.objects.select_related("product__category", "product__brand")
    )
    quantity = serializers.DecimalField(**QUANTITY)


class CartSerializer(serializers.Serializer):
    lines = CartLineSerializer(many=True, max_length=50)


class QuoteLineSerializer(serializers.Serializer):
    variant = serializers.UUIDField(source="variant_id")
    description = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    available = serializers.BooleanField()
    max_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.IntegerField(allow_null=True)
    line_total = serializers.IntegerField(allow_null=True)


class QuoteSerializer(serializers.Serializer):
    lines = QuoteLineSerializer(many=True)
    total = serializers.IntegerField(help_text="MRU, available lines only")


class OrderCreateSerializer(CartSerializer):
    delivery_name = serializers.CharField(max_length=120)
    delivery_phone = serializers.CharField(max_length=32)
    delivery_city = serializers.CharField(max_length=80)
    delivery_address = serializers.CharField(max_length=255)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderLine
        fields = ["id", "variant", "description", "quantity", "unit_price", "line_total"]


class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True)
    status = serializers.ChoiceField(choices=OrderStatus.choices)

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "status",
            "subtotal",
            "delivery_fee",
            "total",
            "payment_method",
            "delivery_name",
            "delivery_phone",
            "delivery_city",
            "delivery_address",
            "note",
            "cancel_reason",
            "created_at",
            "confirmed_at",
            "ready_at",
            "delivered_at",
            "cancelled_at",
            "lines",
        ]


# ---------------------------------------------------------------- stores (ERP)


class StoreOrderLineSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source="order_line.description")
    tracks_serial = serializers.BooleanField(source="store_product.tracks_serial")

    class Meta:
        model = StoreOrderLine
        fields = [
            "id",
            "store_product",
            "description",
            "quantity",
            "unit_price",
            "line_total",
            "tracks_serial",
            "serials",
        ]


class StoreOrderSerializer(serializers.ModelSerializer):
    """What a store sees: its part, at its prices. Never the customer."""

    number = serializers.CharField(source="order.number")
    status = serializers.ChoiceField(choices=StoreOrderStatus.choices)
    lines = StoreOrderLineSerializer(many=True)

    class Meta:
        model = StoreOrder
        fields = [
            "id",
            "number",
            "status",
            "total",
            "reject_reason",
            "created_at",
            "accepted_at",
            "ready_at",
            "picked_up_at",
            "closed_at",
            "lines",
        ]


class AcceptLineSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Store order line")
    serials = serializers.ListField(child=serializers.CharField(max_length=64), max_length=500)


class AcceptSerializer(serializers.Serializer):
    lines = AcceptLineSerializer(
        many=True, required=False, help_text="Serial numbers, for products that track them"
    )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


# ---------------------------------------------------------------- console


class ConsoleStoreRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    city = serializers.CharField()
    address = serializers.CharField()
    phone = serializers.CharField()


class ConsoleStoreOrderSerializer(StoreOrderSerializer):
    store = serializers.SerializerMethodField()

    class Meta(StoreOrderSerializer.Meta):
        fields = ["store", *StoreOrderSerializer.Meta.fields]

    def get_store(self, obj) -> ConsoleStoreRefSerializer:
        return ConsoleStoreRefSerializer(obj.store).data


class ConsoleOrderSerializer(OrderSerializer):
    customer = UserSerializer()
    margin_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    store_orders = ConsoleStoreOrderSerializer(many=True)

    class Meta(OrderSerializer.Meta):
        fields = [*OrderSerializer.Meta.fields, "customer", "margin_percent", "store_orders"]
