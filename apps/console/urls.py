from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("console/me/sessions", views.ConsoleSessionViewSet, basename="console-session")
router.register("console/stores", views.ConsoleStoreViewSet, basename="console-store")
router.register(
    "console/catalog/categories", views.ConsoleCategoryViewSet, basename="console-category"
)
router.register("console/catalog/brands", views.ConsoleBrandViewSet, basename="console-brand")
router.register("console/catalog/products", views.ConsoleProductViewSet, basename="console-product")
router.register(
    "console/product-requests",
    views.ConsoleProductRequestViewSet,
    basename="console-product-request",
)
router.register("console/team", views.StaffViewSet, basename="console-staff")
router.register("console/audit-events", views.AuditEventViewSet, basename="console-audit")

urlpatterns = [
    path("console/auth/login", views.ConsoleLoginView.as_view()),
    path("console/auth/logout", views.ConsoleLogoutView.as_view()),
    path("console/me", views.ConsoleMeView.as_view()),
    path("console/dashboard", views.DashboardView.as_view()),
    path("console/settings", views.PlatformSettingsView.as_view()),
    path("platform", views.PlatformInfoView.as_view()),
    *router.urls,
]
