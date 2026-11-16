from django.urls import path

from . import views

urlpatterns = [
    path("stores/<uuid:store_id>/reports/summary", views.SummaryView.as_view()),
    path("stores/<uuid:store_id>/reports/details", views.DetailsView.as_view()),
    path("stores/<uuid:store_id>/member-activity", views.MemberActivityView.as_view()),
    path("stores/<uuid:store_id>/seller-performance/me", views.SellerPerformanceView.as_view()),
]
