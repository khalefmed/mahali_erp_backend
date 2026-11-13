from rest_framework.routers import SimpleRouter

from . import views

S = r"stores/(?P<store_id>[0-9a-f-]{36})"
router = SimpleRouter(trailing_slash=False)
router.register(f"{S}/customers", views.CustomerViewSet, basename="customer")
router.register(f"{S}/cash-sessions", views.CashSessionViewSet, basename="cash-session")
router.register(f"{S}/sales", views.SaleViewSet, basename="sale")
router.register(f"{S}/credit-notes", views.CreditNoteViewSet, basename="credit-note")
router.register(f"{S}/credits", views.CreditViewSet, basename="credit")
router.register(f"{S}/expenses", views.ExpenseViewSet, basename="expense")
urlpatterns = router.urls
