from django.urls import path

from .views import (
    PaperAccountDetailView,
    PaperAccountListCreateView,
    PaperAccountRestartView,
    PaperFillListView,
    PaperLedgerListView,
    PaperNavListView,
    PaperOrderListView,
)

urlpatterns = [
    path("accounts", PaperAccountListCreateView.as_view()),
    path("accounts/<uuid:account_id>", PaperAccountDetailView.as_view()),
    path("accounts/<uuid:account_id>/restart", PaperAccountRestartView.as_view()),
    path("accounts/<uuid:account_id>/orders", PaperOrderListView.as_view()),
    path("accounts/<uuid:account_id>/fills", PaperFillListView.as_view()),
    path("accounts/<uuid:account_id>/ledger", PaperLedgerListView.as_view()),
    path("accounts/<uuid:account_id>/nav", PaperNavListView.as_view()),
]
