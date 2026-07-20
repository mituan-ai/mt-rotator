from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import conflict
from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.core.permissions import IsAdministrator
from apps.market.models import Instrument
from apps.market.services import current_data_status
from apps.strategies.models import StrategyVersion

from .models import AdviceSnapshot, Fill, Order, PaperAccount, PaperCycleRun
from .ranking import build_leaderboard
from .serializers import (
    AccountPreferenceSerializer,
    AdviceSnapshotSerializer,
    FillSerializer,
    LedgerSerializer,
    NavSerializer,
    OrderSerializer,
    PaperAccountDetailSerializer,
    PaperAccountListSerializer,
    PaperCycleRunSerializer,
    UserOrderCreateSerializer,
)
from .services import (
    cancel_user_order,
    create_user_order,
    ensure_manual_account,
    restart_account,
    update_account_preferences,
)
from .tasks import reconcile_paper_cycles


def _owned_account(user, account_id) -> PaperAccount:
    return get_object_or_404(
        PaperAccount.objects.select_related("strategy_version"),
        pk=account_id,
        user=user,
    )


class PaperAccountListCreateView(APIView):
    def get(self, request):
        ensure_manual_account(request.user)
        accounts = PaperAccount.objects.filter(user=request.user).select_related("strategy_version")
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(accounts, request)
        return paginator.get_paginated_response(PaperAccountListSerializer(page, many=True).data)

    def post(self, request):
        account = ensure_manual_account(request.user)
        return Response(PaperAccountDetailSerializer(account).data, status=status.HTTP_200_OK)


class PaperAccountDetailView(APIView):
    def get(self, request, account_id):
        return Response(PaperAccountDetailSerializer(_owned_account(request.user, account_id)).data)

    def patch(self, request, account_id):
        account = _owned_account(request.user, account_id)
        serializer = AccountPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        strategy = None
        if strategy_id := serializer.validated_data.get("strategy_version_id"):
            strategy = get_object_or_404(StrategyVersion, pk=strategy_id, active=True)
        try:
            account = update_account_preferences(
                account,
                strategy=strategy,
                risk_level=serializer.validated_data.get("risk_level"),
            )
        except ValueError as exc:
            return conflict(str(exc), code="account_preference_conflict")
        record_audit("paper.account_preferences_updated", actor=request.user, target=account, request=request)
        return Response(PaperAccountDetailSerializer(account).data)


class PaperAccountRestartView(APIView):
    def post(self, request, account_id):
        account = _owned_account(request.user, account_id)
        try:
            replacement = restart_account(account)
        except ValueError as exc:
            return conflict(str(exc), code="account_restart_not_allowed")
        record_audit(
            "paper.account_restarted",
            actor=request.user,
            target=replacement,
            request=request,
            detail={"archived_account_id": str(account.id)},
        )
        return Response(PaperAccountDetailSerializer(replacement).data, status=201)


class PaperOrderListCreateView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        paginator = DefaultPagination()
        queryset = account.orders.select_related("instrument", "fill")
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(OrderSerializer(page, many=True).data)

    def post(self, request, account_id):
        account = _owned_account(request.user, account_id)
        serializer = UserOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instrument = get_object_or_404(
            Instrument,
            symbol=serializer.validated_data.pop("instrument"),
            catalog_active=True,
        )
        try:
            order, created = create_user_order(
                account=account,
                instrument=instrument,
                **serializer.validated_data,
            )
        except ValueError as exc:
            message = str(exc)
            code = (
                "insufficient_cash"
                if "现金" in message
                else "insufficient_sellable_shares"
                if "可卖" in message
                else "instrument_unavailable"
                if "不可交易" in message or "收盘价" in message
                else "invalid_order"
            )
            return conflict(message, code=code)
        record_audit(
            "paper.user_order_created",
            actor=request.user,
            target=order,
            request=request,
            detail={"created": created},
        )
        return Response(OrderSerializer(order).data, status=201 if created else 200)


class PaperOrderCancelView(APIView):
    def post(self, request, account_id, order_id):
        account = _owned_account(request.user, account_id)
        order = get_object_or_404(Order, pk=order_id, account=account)
        try:
            order = cancel_user_order(order)
        except ValueError as exc:
            return conflict(str(exc), code="order_not_cancellable")
        record_audit("paper.user_order_cancelled", actor=request.user, target=order, request=request)
        return Response(OrderSerializer(order).data)


class PaperAdviceCurrentView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        advice = (
            account.advice_snapshots.filter(
                strategy_version=account.strategy_version,
                risk_level=account.risk_level,
            )
            .select_related("strategy_version")
            .first()
        )
        if not advice:
            return Response(
                {
                    "type": "https://mt-rotator.local/problems/advice_not_ready",
                    "title": "建议尚未生成",
                    "status": 404,
                    "detail": "完成首个健康交易日处理后才会生成建议",
                    "code": "advice_not_ready",
                },
                status=404,
                content_type="application/problem+json",
            )
        data = AdviceSnapshotSerializer(advice).data
        data["stale"] = advice.session_date < current_data_status()["expected_session"]
        return Response(data)


class PaperAdviceHistoryView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        queryset = AdviceSnapshot.objects.filter(account=account).select_related("strategy_version")
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(AdviceSnapshotSerializer(page, many=True).data)


class LeaderboardView(APIView):
    def get(self, request):
        try:
            result = build_leaderboard(request.query_params.get("period", "mtd"))
        except ValueError as exc:
            raise ValidationError({"period": [str(exc)]}) from exc
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(result["results"], request)
        response = paginator.get_paginated_response(page)
        response.data["period"] = result["period"]
        response.data["as_of_date"] = result["as_of_date"]
        return response


class PaperLedgerListView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(account.ledger_entries.select_related("instrument"), request)
        return paginator.get_paginated_response(LedgerSerializer(page, many=True).data)


class PaperFillListView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        paginator = DefaultPagination()
        queryset = Fill.objects.filter(order__account=account).select_related("order")
        page = paginator.paginate_queryset(queryset.order_by("-created_at"), request)
        return paginator.get_paginated_response(FillSerializer(page, many=True).data)


class PaperNavListView(APIView):
    def get(self, request, account_id):
        account = _owned_account(request.user, account_id)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(account.nav_snapshots.order_by("-date"), request)
        return paginator.get_paginated_response(NavSerializer(page, many=True).data)


class AdminPaperCycleListView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        queryset = PaperCycleRun.objects.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            valid = {choice for choice, _ in PaperCycleRun.Status.choices}
            if status_filter not in valid:
                raise ValidationError({"status": ["无效的周期状态"]})
            queryset = queryset.filter(status=status_filter)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(PaperCycleRunSerializer(page, many=True).data)


class AdminPaperReconcileView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def post(self, request):
        task = reconcile_paper_cycles.delay()
        record_audit(
            "admin.paper_reconcile_requested",
            actor=request.user,
            request=request,
            detail={"task_id": task.id},
        )
        return Response({"job_id": task.id, "status": "queued"}, status=202)
