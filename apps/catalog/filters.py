import unicodedata

import django_filters
from django.contrib.postgres.lookups import Unaccent
from django.db.models import Q

from apps.stores.models import Trade

from .models import Product


class ProductFilter(django_filters.FilterSet):
    trade = django_filters.ChoiceFilter(field_name="category__trade", choices=Trade.choices)
    category = django_filters.UUIDFilter(method="filter_category")
    brand = django_filters.UUIDFilter(field_name="brand_id")
    barcode = django_filters.CharFilter(field_name="variants__barcode")
    search = django_filters.CharFilter(
        method="filter_search", help_text="Name (fr or ar), brand, barcode. Accents ignored."
    )

    class Meta:
        model = Product
        fields = ["status"]

    def filter_category(self, queryset, name, value):
        return queryset.filter(Q(category_id=value) | Q(category__parent_id=value))

    def filter_search(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        queryset = queryset.alias(name_u=Unaccent("name"), brand_u=Unaccent("brand__name"))
        terms = Q()
        for word in value.split():
            terms &= (
                Q(name_u__icontains=strip_accents(word))
                | Q(name_ar__icontains=word)
                | Q(brand_u__icontains=strip_accents(word))
                | Q(variants__barcode=word)
                | Q(variants__name__icontains=word)
            )
        return queryset.filter(terms).distinct()


def strip_accents(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))
