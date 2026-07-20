from django.urls import path

from .views import AdminBatchListView, InstrumentBarsView, InstrumentListView, MarketStatusView

urlpatterns = [
    path("status", MarketStatusView.as_view()),
    path("instruments", InstrumentListView.as_view()),
    path("instruments/<str:symbol>/bars", InstrumentBarsView.as_view()),
    path("admin/batches", AdminBatchListView.as_view()),
]
