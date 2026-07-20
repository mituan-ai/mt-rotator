from django.urls import path

from .views import (
    AdminBatchListView,
    AdminCorporateActionView,
    AdminInstrumentRepairView,
    AdminInstrumentView,
    InstrumentBarsView,
    InstrumentDetailView,
    InstrumentListView,
    MarketStatusView,
)

urlpatterns = [
    path("status", MarketStatusView.as_view()),
    path("instruments", InstrumentListView.as_view()),
    path("instruments/<str:symbol>", InstrumentDetailView.as_view()),
    path("instruments/<str:symbol>/bars", InstrumentBarsView.as_view()),
    path("admin/batches", AdminBatchListView.as_view()),
    path("admin/instruments/<str:symbol>", AdminInstrumentView.as_view()),
    path("admin/instruments/<str:symbol>/repair", AdminInstrumentRepairView.as_view()),
    path("admin/instruments/<str:symbol>/actions", AdminCorporateActionView.as_view()),
]
