from django.urls import path

from . import views

urlpatterns = [
    path("stores/<uuid:store_id>/reports/summary", views.SummaryView.as_view()),
]
