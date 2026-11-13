from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("catalog/categories", views.CategoryViewSet, basename="category")
router.register("catalog/brands", views.BrandViewSet, basename="brand")
router.register("catalog/products", views.ProductViewSet, basename="product")
router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/product-requests",
    views.ProductRequestViewSet,
    basename="product-request",
)
urlpatterns = router.urls
