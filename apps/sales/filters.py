import django_filters
from django.db.models import Q

from .models import Credit, Customer, Expense, Sale


class CustomerFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Name or phone")
    has_credit = django_filters.BooleanFilter(method="filter_has_credit")

    class Meta:
        model = Customer
        fields = ["is_active"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(Q(name__unaccent__icontains=value) | Q(phone__icontains=value))

    def filter_has_credit(self, queryset, name, value):
        return queryset.filter(credit_balance__gt=0) if value else queryset.filter(credit_balance=0)


class SaleFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")
    search = django_filters.CharFilter(method="filter_search", help_text="Number, customer, IMEI")

    class Meta:
        model = Sale
        fields = ["status", "customer", "seller", "cash_session"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(number__icontains=value)
            | Q(customer__name__icontains=value)
            | Q(lines__serial_unit__serial=value)
        ).distinct()


class CreditFilter(django_filters.FilterSet):
    overdue = django_filters.BooleanFilter(method="filter_overdue")

    class Meta:
        model = Credit
        fields = ["status", "customer"]

    def filter_overdue(self, queryset, name, value):
        from django.utils import timezone

        condition = Q(status=Credit.Status.OPEN, due_date__lt=timezone.localdate())
        return queryset.filter(condition) if value else queryset.exclude(condition)


class ExpenseFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Expense
        fields = ["category", "method"]
