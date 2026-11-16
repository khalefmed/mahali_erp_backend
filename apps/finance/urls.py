from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/supplier-payments",
    views.SupplierPaymentViewSet,
    basename="supplier-payment",
)

router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/recurring-expenses",
    views.RecurringExpenseViewSet,
    basename="recurring-expense",
)

S = "stores/<uuid:store_id>"
urlpatterns = [
    path(f"{S}/money-accounts", views.MoneyAccountListView.as_view()),
    path(f"{S}/money-movements", views.MoneyMovementListView.as_view()),
    path(f"{S}/money-transfers", views.MoneyTransferView.as_view()),
    path(f"{S}/expense-budgets", views.ExpenseBudgetView.as_view()),
    path("stores/<uuid:store_id>/accounting/journal", views.JournalView.as_view()),
    path("stores/<uuid:store_id>/accounting/closing", views.ClosingView.as_view()),
    *router.urls,
]
