from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.strategies.models import StrategyVersion

from .models import Fill, PaperAccount
from .serializers import (
    AccountActivateSerializer,
    FillSerializer,
    LedgerSerializer,
    NavSerializer,
    OrderSerializer,
    PaperAccountDetailSerializer,
    PaperAccountListSerializer,
)
from .services import activate_account, restart_account


class PaperAccountListCreateView(APIView):
    def get(self, request):
        accounts = PaperAccount.objects.filter(user=request.user).select_related("strategy_version")
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(accounts, request)
        return paginator.get_paginated_response(PaperAccountListSerializer(page, many=True).data)

    def post(self, request):
        serializer = AccountActivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        strategy = get_object_or_404(
            StrategyVersion,
            pk=serializer.validated_data["strategy_version_id"],
            active=True,
        )
        try:
            account = activate_account(user=request.user, strategy=strategy)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        record_audit("paper.account_activated", actor=request.user, target=account, request=request)
        return Response(PaperAccountDetailSerializer(account).data, status=201)


class PaperAccountDetailView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(
            PaperAccount.objects.select_related("strategy_version"),
            pk=account_id,
            user=request.user,
        )
        return Response(PaperAccountDetailSerializer(account).data)


class PaperAccountRestartView(APIView):
    def post(self, request, account_id):
        account = get_object_or_404(PaperAccount, pk=account_id, user=request.user)
        try:
            replacement = restart_account(account)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        record_audit(
            "paper.account_restarted",
            actor=request.user,
            target=replacement,
            request=request,
            detail={"archived_account_id": str(account.id)},
        )
        return Response(PaperAccountDetailSerializer(replacement).data, status=201)


class PaperOrderListView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(PaperAccount, pk=account_id, user=request.user)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(account.orders.select_related("instrument", "fill"), request)
        return paginator.get_paginated_response(OrderSerializer(page, many=True).data)


class PaperLedgerListView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(PaperAccount, pk=account_id, user=request.user)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(account.ledger_entries.select_related("instrument"), request)
        return paginator.get_paginated_response(LedgerSerializer(page, many=True).data)


class PaperFillListView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(PaperAccount, pk=account_id, user=request.user)
        paginator = DefaultPagination()
        queryset = Fill.objects.filter(order__account=account).select_related("order")
        page = paginator.paginate_queryset(queryset.order_by("-created_at"), request)
        return paginator.get_paginated_response(FillSerializer(page, many=True).data)


class PaperNavListView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(PaperAccount, pk=account_id, user=request.user)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(account.nav_snapshots.order_by("-date"), request)
        return paginator.get_paginated_response(NavSerializer(page, many=True).data)
