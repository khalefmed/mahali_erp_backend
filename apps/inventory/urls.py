from rest_framework.routers import SimpleRouter

from . import views

S = r"stores/(?P<store_id>[0-9a-f-]{36})"
router = SimpleRouter(trailing_slash=False)
router.register(f"{S}/products", views.StoreProductViewSet, basename="store-product")
router.register(f"{S}/serials", views.SerialUnitViewSet, basename="serial-unit")
router.register(f"{S}/stock-movements", views.StockMovementViewSet, basename="stock-movement")
router.register(f"{S}/suppliers", views.SupplierViewSet, basename="supplier")
router.register(f"{S}/receipts", views.ReceiptViewSet, basename="receipt")
router.register(f"{S}/stock-adjustments", views.StockAdjustmentViewSet, basename="stock-adjustment")
urlpatterns = router.urls
