from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

S = r"stores/(?P<store_id>[0-9a-f-]{36})"
router = SimpleRouter(trailing_slash=False)
router.register("marketplace/products", views.ShopProductViewSet, basename="shop-product")
router.register("marketplace/orders", views.CustomerOrderViewSet, basename="marketplace-order")
router.register(f"{S}/marketplace-orders", views.StoreOrderViewSet, basename="store-order")
router.register(
    "console/marketplace/orders", views.ConsoleOrderViewSet, basename="console-marketplace-order"
)

urlpatterns = [
    path("marketplace/categories", views.ShopCategoryView.as_view()),
    path("marketplace/cart/quote", views.QuoteView.as_view()),
    path("marketplace/auth/register", views.CustomerRegisterView.as_view()),
    path("marketplace/auth/verify-email", views.CustomerVerifyEmailView.as_view()),
    path("marketplace/auth/login", views.CustomerLoginView.as_view()),
    path("marketplace/auth/logout", views.CustomerLogoutView.as_view()),
    path("marketplace/auth/password/forgot", views.CustomerPasswordForgotView.as_view()),
    path("marketplace/meysara/offer", views.MeysaraOfferView.as_view()),
    path("marketplace/meysara/contract", views.MeysaraContractView.as_view()),
    path("marketplace/identity", views.IdentityView.as_view()),
    path("marketplace/identity/phone/resend", views.IdentityResendView.as_view()),
    path("marketplace/identity/phone/verify", views.IdentityVerifyPhoneView.as_view()),
    path("marketplace/identity/documents", views.IdentityDocumentsView.as_view()),
    path("marketplace/me", views.CustomerMeView.as_view()),
    *router.urls,
]
