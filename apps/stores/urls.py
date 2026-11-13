from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("stores", views.StoreViewSet, basename="store")
router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/members", views.MemberViewSet, basename="member"
)
router.register(
    r"stores/(?P<store_id>[0-9a-f-]{36})/invitations",
    views.InvitationViewSet,
    basename="invitation",
)
router.register("me/invitations", views.MyInvitationViewSet, basename="my-invitation")
router.register(
    "me/ownership-transfers", views.MyOwnershipTransferViewSet, basename="my-ownership-transfer"
)

urlpatterns = [
    path("me/stores", views.MyStoresView.as_view()),
    path("stores/<uuid:store_id>/ownership-transfer", views.OwnershipTransferView.as_view()),
    path("invitations/<str:token>", views.InvitationPreviewView.as_view()),
    path("invitations/<str:token>/accept", views.InvitationAcceptView.as_view()),
    path("files/<str:token>", views.PrivateFileView.as_view(), name="private-file"),
    *router.urls,
]
