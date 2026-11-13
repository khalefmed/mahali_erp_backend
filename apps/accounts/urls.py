from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("me/sessions", views.SessionViewSet, basename="session")

urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/resend-code", views.ResendCodeView.as_view()),
    path("auth/verify-email", views.VerifyEmailView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/refresh", views.RefreshView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/password/forgot", views.ForgotPasswordView.as_view()),
    path("auth/password/reset", views.ResetPasswordView.as_view()),
    path("me", views.MeView.as_view()),
    path("me/password", views.ChangePasswordView.as_view()),
    *router.urls,
]
