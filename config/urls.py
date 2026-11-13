from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.core.views import health

api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.stores.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.sales.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.console.urls")),
]

urlpatterns = [
    path("health", health),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema")),
    path("", RedirectView.as_view(url="/api/redoc/", permanent=False)),
]

if settings.ADMIN_PATH:
    urlpatterns.append(path(settings.ADMIN_PATH, admin.site.urls))
