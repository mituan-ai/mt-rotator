from django.urls import path

from .views import AuditListView, DataFreshnessView, LiveView, ReadyView

urlpatterns = [
    path("health/live", LiveView.as_view()),
    path("health/ready", ReadyView.as_view()),
    path("health/data", DataFreshnessView.as_view()),
    path("admin/audit", AuditListView.as_view()),
]
