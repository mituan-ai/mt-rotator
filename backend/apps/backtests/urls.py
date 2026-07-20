from django.urls import path

from .views import BacktestCancelView, BacktestDetailView, BacktestExportView, BacktestListCreateView

urlpatterns = [
    path("", BacktestListCreateView.as_view()),
    path("<uuid:run_id>", BacktestDetailView.as_view()),
    path("<uuid:run_id>/cancel", BacktestCancelView.as_view()),
    path("<uuid:run_id>/export", BacktestExportView.as_view()),
]
