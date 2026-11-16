from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/supplier-payments",
    views.SupplierPaymentViewSet,
    basename="supplier-payment",
)

urlpatterns = [
    path("stores/<uuid:store_id>/accounting/journal", views.JournalView.as_view()),
    path("stores/<uuid:store_id>/accounting/closing", views.ClosingView.as_view()),
    *router.urls,
]
