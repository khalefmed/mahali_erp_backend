from django.utils.text import slugify
from rest_framework import serializers

from .attributes import validate_attributes, validate_schema
from .models import Brand, Category, Product, ProductRequest, Variant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "trade",
            "parent",
            "name",
            "name_ar",
            "slug",
            "tracks_serial",
            "default_warranty_months",
            "attribute_schema",
            "sort_order",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate_attribute_schema(self, value):
        return validate_schema(value)

    def validate(self, attrs):
        if not attrs.get("slug") and not getattr(self.instance, "slug", None):
            attrs["slug"] = slugify(attrs.get("name", ""))
        return attrs

    def get_fields(self):
        fields = super().get_fields()
        fields["slug"].required = False
        return fields


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "trades"]
        read_only_fields = ["id", "slug"]

    def create(self, validated_data):
        validated_data["slug"] = slugify(validated_data["name"])
        return super().create(validated_data)


class VariantSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Variant
        fields = ["id", "name", "full_name", "attributes", "barcode", "is_active"]


class CatalogProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True, default=None)
    trade = serializers.CharField(source="category.trade", read_only=True)
    tracks_serial = serializers.BooleanField(source="category.tracks_serial", read_only=True)
    variants = VariantSerializer(many=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "category",
            "category_name",
            "trade",
            "tracks_serial",
            "brand",
            "brand_name",
            "name",
            "name_ar",
            "description",
            "attributes",
            "image_url",
            "status",
            "variants",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        category = attrs.get("category") or self.instance.category
        schema = category.attribute_schema
        if "attributes" in attrs or not self.instance:
            attrs["attributes"] = validate_attributes(
                schema, attrs.get("attributes", {}), "product", "attributes"
            )
        variants = attrs.get("variants")
        if variants is not None:
            if not variants:
                raise serializers.ValidationError(
                    {"variants": "At least one variant."}, code="required"
                )
            for index, variant in enumerate(variants):
                variant["attributes"] = validate_attributes(
                    schema, variant.get("attributes", {}), "variant", f"variants.{index}.attributes"
                )
                if not variant.get("name"):
                    variant["name"] = " · ".join(str(v) for v in variant["attributes"].values())
        return attrs

    def create(self, validated_data):
        variants = validated_data.pop("variants")
        product = Product.objects.create(**validated_data)
        for variant in variants:
            variant.pop("id", None)
            Variant.objects.create(product=product, **variant)
        return product

    def update(self, instance, validated_data):
        variants = validated_data.pop("variants", None)
        instance = super().update(instance, validated_data)
        if variants is not None:
            existing = {v.id: v for v in instance.variants.all()}
            for data in variants:
                variant_id = data.pop("id", None)
                if variant_id in existing:
                    variant = existing[variant_id]
                    for key, value in data.items():
                        setattr(variant, key, value)
                    variant.save()
                else:
                    Variant.objects.create(product=instance, **data)
        return instance


class ProductRequestSerializer(serializers.ModelSerializer):
    photo = serializers.FileField(write_only=True, required=False)
    store_name = serializers.CharField(source="store.name", read_only=True)
    variant = VariantSerializer(read_only=True)

    class Meta:
        model = ProductRequest
        fields = [
            "id",
            "store",
            "store_name",
            "name",
            "category",
            "brand_name",
            "barcode",
            "note",
            "photo",
            "status",
            "variant",
            "decision_message",
            "decided_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "store",
            "status",
            "variant",
            "decision_message",
            "decided_at",
            "created_at",
        ]


class ImportResultSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    created_products = serializers.IntegerField()
    created_variants = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField())


class ImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text=(
            "CSV (UTF-8). Columns: category (slug), brand, product, product_ar, description, "
            "image_url, variant, barcode, then `p:<key>` product attributes and `v:<key>` "
            "variant attributes."
        )
    )
    dry_run = serializers.BooleanField(default=True)
