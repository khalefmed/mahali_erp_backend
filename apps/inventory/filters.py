import django_filters
from django.db.models import F, Q

from .models import Condition, StockMovement, StoreProduct


class StoreProductFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method="filter_search", help_text="Product, brand, variant or barcode"
    )
    category = django_filters.UUIDFilter(method="filter_category")
    condition = django_filters.ChoiceFilter(choices=Condition.choices)
    barcode = django_filters.CharFilter(field_name="variant__barcode")
    in_stock = django_filters.BooleanFilter(method="filter_in_stock")
    low_stock = django_filters.BooleanFilter(method="filter_low_stock")

    class Meta:
        model = StoreProduct
        fields = ["is_active"]

    def filter_search(self, queryset, name, value):
        for word in value.split():
            queryset = queryset.filter(
                Q(variant__product__name__unaccent__icontains=word)
                | Q(variant__product__name_ar__icontains=word)
                | Q(variant__product__brand__name__unaccent__icontains=word)
                | Q(variant__name__icontains=word)
                | Q(variant__barcode=word)
            )
        return queryset

    def filter_category(self, queryset, name, value):
        return queryset.filter(
            Q(variant__product__category_id=value) | Q(variant__product__category__parent_id=value)
        )

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(quantity__gt=0) if value else queryset.filter(quantity=0)

    def filter_low_stock(self, queryset, name, value):
        condition = Q(quantity__lte=F("reorder_level"))
        return queryset.filter(condition) if value else queryset.exclude(condition)


class StockMovementFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = StockMovement
        fields = ["kind", "store_product"]
