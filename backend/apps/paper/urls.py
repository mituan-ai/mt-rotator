from django.urls import path

from .views import (
    AdminPaperCycleListView,
    AdminPaperReconcileView,
    LeaderboardView,
    PaperAccountDetailView,
    PaperAccountListCreateView,
    PaperAccountRestartView,
    PaperAdviceCurrentView,
    PaperAdviceHistoryView,
    PaperFillListView,
    PaperLedgerListView,
    PaperNavListView,
    PaperOrderCancelView,
    PaperOrderListCreateView,
)

urlpatterns = [
    path("admin/cycles", AdminPaperCycleListView.as_view()),
    path("admin/reconcile", AdminPaperReconcileView.as_view()),
    path("leaderboard", LeaderboardView.as_view()),
    path("accounts", PaperAccountListCreateView.as_view()),
    path("accounts/<uuid:account_id>", PaperAccountDetailView.as_view()),
    path("accounts/<uuid:account_id>/restart", PaperAccountRestartView.as_view()),
    path("accounts/<uuid:account_id>/orders", PaperOrderListCreateView.as_view()),
    path(
        "accounts/<uuid:account_id>/orders/<uuid:order_id>/cancel",
        PaperOrderCancelView.as_view(),
    ),
    path("accounts/<uuid:account_id>/advice/current", PaperAdviceCurrentView.as_view()),
    path("accounts/<uuid:account_id>/advice", PaperAdviceHistoryView.as_view()),
    path("accounts/<uuid:account_id>/fills", PaperFillListView.as_view()),
    path("accounts/<uuid:account_id>/ledger", PaperLedgerListView.as_view()),
    path("accounts/<uuid:account_id>/nav", PaperNavListView.as_view()),
]
