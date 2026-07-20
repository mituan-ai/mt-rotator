from django.urls import path

from .views import (
    AdminSignalGenerateView,
    AdminStrategyListView,
    AdminStrategyStatusView,
    LatestSignalView,
    SignalListView,
    StrategyDetailView,
    StrategyListView,
    StrategyVersionHistoryView,
)

urlpatterns = [
    path("", StrategyListView.as_view()),
    path("admin", AdminStrategyListView.as_view()),
    path("<slug:slug>", StrategyDetailView.as_view()),
    path("<slug:slug>/versions", StrategyVersionHistoryView.as_view()),
    path("<slug:slug>/signals", SignalListView.as_view()),
    path("<slug:slug>/signals/latest", LatestSignalView.as_view()),
    path("<slug:slug>/signals/generate", AdminSignalGenerateView.as_view()),
    path("admin/<uuid:strategy_id>", AdminStrategyStatusView.as_view()),
]
