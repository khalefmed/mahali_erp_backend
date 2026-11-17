from rest_framework import serializers

from apps.accounts.models import Language
from apps.accounts.serializers import UserSerializer
from apps.catalog.models import Brand, Category, Product, Variant

from . import meysara
from .models import (
    IdentityStatus,
    IdentityVerification,
    InstalmentMethod,
    MeysaraContract,
    MeysaraInstalment,
    MeysaraPlan,
    MeysaraPlanStatus,
    Order,
    OrderLine,
    OrderStatus,
    PaymentMethod,
    StoreOrder,
    StoreOrderLine,
    StoreOrderStatus,
)

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


class FacetBrandSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    count = serializers.IntegerField(help_text="Products of this brand in the listing")


class ShopFacetsSerializer(serializers.Serializer):
    brands = FacetBrandSerializer(many=True, help_text="Ignoring the `brand` filter itself")
    min_price = serializers.IntegerField(allow_null=True)
    max_price = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField()


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
    image_url = serializers.CharField(help_text="Product photo, or empty")
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    available = serializers.BooleanField()
    max_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.IntegerField(allow_null=True)
    line_total = serializers.IntegerField(allow_null=True)


class QuoteSerializer(serializers.Serializer):
    lines = QuoteLineSerializer(many=True)
    total = serializers.IntegerField(help_text="MRU, available lines only")


# Same codes as the accounts' language, so one enum in the schema.
LANGUAGE_CHOICES = Language.choices


class MeysaraContractAcceptanceSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=10)
    digest = serializers.CharField(max_length=64)
    language = serializers.ChoiceField(choices=LANGUAGE_CHOICES)
    accepted = serializers.BooleanField(help_text="The shopper ticked the box")


class OrderCreateSerializer(CartSerializer):
    delivery_name = serializers.CharField(max_length=120)
    delivery_phone = serializers.CharField(max_length=32)
    delivery_city = serializers.CharField(max_length=80)
    delivery_address = serializers.CharField(max_length=255)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices, default=PaymentMethod.CASH_ON_DELIVERY
    )
    meysara_percent = serializers.ChoiceField(
        choices=[(25, "25 %"), (50, "50 %"), (100, "100 %")],
        required=False,
        allow_null=True,
        help_text="With payment_method=meysara: one of the offer's `choices`",
    )
    meysara_contract = MeysaraContractAcceptanceSerializer(
        required=False,
        allow_null=True,
        help_text="With payment_method=meysara: the contract shown "
        "(`marketplace/meysara/contract`), accepted",
    )


# ---------------------------------------------------------------- Meysara


class MeysaraOfferSerializer(serializers.Serializer):
    eligible = serializers.BooleanField()
    reason = serializers.ChoiceField(
        choices=[(r, r) for r in meysara.Reason.ALL],
        allow_null=True,
        help_text="First rule that fails, when not eligible",
    )
    max_percent = serializers.IntegerField(allow_null=True)
    choices = serializers.ListField(child=serializers.IntegerField(), help_text="Shares on offer")
    paid_orders = serializers.IntegerField(help_text="Delivered and paid orders so far")
    required_orders = serializers.IntegerField()
    min_total = serializers.IntegerField(help_text="MRU")
    max_financed = serializers.IntegerField(
        help_text="MRU, largest share in instalments (never above `regulatory_max_financed`)"
    )
    identity_verified = serializers.BooleanField(
        help_text="e-KYC done (`marketplace/identity`); required before Meysara"
    )
    regulatory_max_financed = serializers.IntegerField(
        help_text="MRU, BCM ceiling per private person (Instruction n°13/GR/2025, art. 25)"
    )


class MeysaraInstalmentSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = MeysaraInstalment
        fields = ["number", "amount", "due_date", "paid_at", "paid_via", "status"]

    def get_status(self, obj) -> str:
        """paid · waiting_delivery · upcoming · due · overdue (more than 7 days late)"""
        return meysara.instalment_status(obj)


class MeysaraContractRequestSerializer(CartSerializer):
    meysara_percent = serializers.ChoiceField(choices=[(25, "25 %"), (50, "50 %"), (100, "100 %")])
    language = serializers.ChoiceField(choices=LANGUAGE_CHOICES, default="fr")


class ContractPartySerializer(serializers.Serializer):
    full_name = serializers.CharField()
    nni = serializers.CharField(help_text="Masked: •••• 4821")
    phone = serializers.CharField()


class ContractSellerSerializer(serializers.Serializer):
    name = serializers.CharField()
    role = serializers.CharField()
    city = serializers.CharField()


class ContractLineSerializer(serializers.Serializer):
    description = serializers.CharField()
    quantity = serializers.CharField()
    line_total = serializers.IntegerField(help_text="MRU")


class ContractInstalmentSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    amount = serializers.IntegerField(help_text="MRU")
    days_after_delivery = serializers.IntegerField()


class ContractClauseSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    text = serializers.CharField()


class MeysaraContractTermsSerializer(serializers.Serializer):
    version = serializers.CharField()
    language = serializers.ChoiceField(choices=LANGUAGE_CHOICES)
    title = serializers.CharField()
    digest = serializers.CharField(help_text="Send back with the order, with `version`")
    buyer = ContractPartySerializer()
    seller = ContractSellerSerializer()
    lines = ContractLineSerializer(many=True)
    total = serializers.IntegerField(help_text="MRU")
    percent = serializers.IntegerField()
    on_delivery = serializers.IntegerField(help_text="MRU")
    financed = serializers.IntegerField(help_text="MRU")
    instalments = ContractInstalmentSerializer(many=True)
    interest = serializers.IntegerField()
    fees = serializers.IntegerField()
    late_fees = serializers.IntegerField()
    clauses = ContractClauseSerializer(many=True)


class MeysaraContractSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = MeysaraContract
        fields = ["number", "version", "language", "accepted_at"]


class MeysaraSignedContractSerializer(serializers.ModelSerializer):
    terms = MeysaraContractTermsSerializer()

    class Meta:
        model = MeysaraContract
        fields = ["number", "version", "language", "accepted_at", "terms"]


class MeysaraPlanSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=MeysaraPlanStatus.choices)
    instalments = MeysaraInstalmentSerializer(many=True)
    contract = serializers.SerializerMethodField()

    class Meta:
        model = MeysaraPlan
        fields = [
            "contract",
            "percent",
            "financed",
            "on_delivery",
            "status",
            "activated_at",
            "closed_at",
            "instalments",
        ]

    def get_contract(self, obj) -> MeysaraContractSummarySerializer(allow_null=True):
        """The signed contract; null for plans booked before contracts existed."""
        signed = getattr(obj, "contract", None)
        return MeysaraContractSummarySerializer(signed).data if signed else None


class PayInstalmentSerializer(serializers.Serializer):
    number = serializers.IntegerField(min_value=1, max_value=meysara.INSTALMENTS)
    via = serializers.ChoiceField(choices=InstalmentMethod.choices)


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderLine
        fields = ["id", "variant", "description", "quantity", "unit_price", "line_total"]


class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True)
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    meysara = serializers.SerializerMethodField()

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
            "meysara",
        ]

    def get_meysara(self, obj) -> MeysaraPlanSerializer(allow_null=True):
        """The pay-in-4 plan, or null when the order is paid on delivery."""
        plan = getattr(obj, "meysara_plan", None)
        return MeysaraPlanSerializer(plan).data if plan else None


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


# ---------------------------------------------------------------- e-KYC


class IdentityStartSerializer(serializers.Serializer):
    nni = serializers.CharField(max_length=10, help_text="10 digits")
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80)
    birth_date = serializers.DateField()
    phone = serializers.CharField(max_length=16, help_text="+222 and 8 digits")
    consent = serializers.BooleanField(
        help_text="The shopper agrees to the identity checks and to their data being processed"
    )


class IdentityCodeSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=6)


class IdentityDocumentsSerializer(serializers.Serializer):
    id_front = serializers.FileField(help_text="Photo of the front of the ID card")
    id_back = serializers.FileField(
        required=False, help_text="Photo of the back of the ID card (MRZ). Optional for now"
    )
    selfie = serializers.FileField(help_text="Selfie taken in the app (liveness check)")


class IdentityChecksSerializer(serializers.Serializer):
    document = serializers.CharField(required=False, help_text="passed · failed")
    face_match = serializers.FloatField(
        required=False, allow_null=True, help_text="0 to 1, the selfie against the ID photo"
    )
    liveness = serializers.CharField(required=False, help_text="passed · failed · not_run")


class IdentitySerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=IdentityStatus.choices, read_only=True)
    checks = IdentityChecksSerializer(read_only=True, help_text="Empty until the photos")
    nni = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    simulation = serializers.SerializerMethodField()

    class Meta:
        model = IdentityVerification
        fields = [
            "status",
            "nni",
            "first_name",
            "last_name",
            "birth_date",
            "phone",
            "phone_verified_at",
            "checks",
            "reject_reason",
            "verified_at",
            "simulation",
        ]
        read_only_fields = fields

    def get_nni(self, obj) -> str:
        """Masked: last 4 digits only"""
        return f"••••••{obj.nni[-4:]}"

    def get_phone(self, obj) -> str:
        """Masked: last 2 digits only"""
        return f"{obj.phone[:4]} •• •• •• {obj.phone[-2:]}"

    def get_simulation(self, obj) -> bool:
        """True while no real e-KYC provider is plugged in"""
        return obj.provider == "simulated"


class IdentityStateSerializer(serializers.Serializer):
    identity = IdentitySerializer(allow_null=True, help_text="Null before the first step")
    simulation_code = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Simulated provider only: the code it would have sent by SMS. Shown in the "
        "app as a demo hint; absent with a real provider.",
    )
