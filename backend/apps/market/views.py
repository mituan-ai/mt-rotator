from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.core.permissions import IsAdministrator

from .models import CorporateAction, Instrument, MarketBar, MarketDataBatch
from .serializers import InstrumentSerializer, MarketBarSerializer, MarketDataBatchSerializer
from .services import (
    current_data_status,
    record_manual_corporate_action,
    update_instrument_controls,
)
from .tasks import repair_market_instrument, update_market_data


class MarketStatusView(APIView):
    def get(self, request):
        return Response(current_data_status())


class InstrumentListView(APIView):
    def get(self, request):
        items = Instrument.objects.filter(catalog_active=True, enabled=True)
        if query := request.query_params.get("q", "").strip():
            items = items.filter(Q(symbol__icontains=query) | Q(name__icontains=query))
        if asset_class := request.query_params.get("asset_class"):
            if asset_class not in {choice for choice, _ in Instrument.AssetClass.choices}:
                raise ValidationError({"asset_class": ["无效的ETF分类"]})
            items = items.filter(asset_class=asset_class)
        if request.query_params.get("tradable") == "true":
            items = items.filter(trade_eligible=True)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(items, request)
        return paginator.get_paginated_response(InstrumentSerializer(page, many=True).data)


class InstrumentDetailView(APIView):
    def get(self, request, symbol):
        instrument = get_object_or_404(Instrument, symbol=symbol, catalog_active=True)
        return Response(InstrumentSerializer(instrument).data)


class InstrumentBarsView(APIView):
    def get(self, request, symbol):
        instrument = get_object_or_404(Instrument, symbol=symbol, enabled=True)
        adjustment = request.query_params.get("adjustment", "raw")
        if adjustment != "raw":
            raise ValidationError({"adjustment": ["公开行情接口仅提供原始日线"]})
        queryset = MarketBar.objects.filter(
            instrument=instrument,
            adjustment=MarketBar.Adjustment.RAW,
            is_current=True,
            batch__finished_at__isnull=False,
        )
        for field, lookup in [("from", "trade_date__gte"), ("to", "trade_date__lte")]:
            if value := request.query_params.get(field):
                try:
                    parsed = date.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError({field: ["日期格式必须为 YYYY-MM-DD"]}) from exc
                queryset = queryset.filter(**{lookup: parsed})
        queryset = queryset.order_by("trade_date")[:5000]
        return Response(
            {
                "instrument": InstrumentSerializer(instrument).data,
                "adjustment": adjustment,
                "source": "新浪财经，经 AKShare 获取",
                "bars": MarketBarSerializer(queryset, many=True).data,
            }
        )


class AdminInstrumentView(APIView):
    permission_classes = [IsAdministrator]

    def patch(self, request, symbol):
        instrument = get_object_or_404(Instrument, symbol=symbol)
        enabled = request.data.get("enabled")
        settlement = request.data.get("settlement_cycle")
        asset_class = request.data.get("asset_class")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValidationError({"enabled": ["必须为布尔值"]})
        if settlement is not None and settlement not in {
            choice for choice, _ in Instrument.SettlementCycle.choices
        }:
            raise ValidationError({"settlement_cycle": ["仅支持 t0 或 t1"]})
        if asset_class is not None and asset_class not in {
            choice for choice, _ in Instrument.AssetClass.choices
        }:
            raise ValidationError({"asset_class": ["无效的ETF分类"]})
        instrument = update_instrument_controls(
            instrument,
            enabled=enabled,
            settlement_cycle=settlement,
            asset_class=asset_class,
        )
        record_audit("admin.instrument_updated", actor=request.user, target=instrument, request=request)
        return Response(InstrumentSerializer(instrument).data)


class AdminInstrumentRepairView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request, symbol):
        get_object_or_404(Instrument, symbol=symbol, catalog_active=True)
        task = repair_market_instrument.delay(symbol, f"admin:{request.user.id}")
        record_audit(
            "admin.instrument_repair_requested",
            actor=request.user,
            request=request,
            detail={"symbol": symbol, "task_id": task.id},
        )
        return Response({"job_id": task.id, "status": "queued"}, status=202)


class AdminCorporateActionView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request, symbol):
        instrument = get_object_or_404(Instrument, symbol=symbol)
        kind = request.data.get("kind")
        if kind not in {choice for choice, _ in CorporateAction.Kind.choices}:
            raise ValidationError({"kind": ["无效的公司行动类型"]})
        try:
            effective_date = date.fromisoformat(request.data.get("effective_date", ""))
            value = Decimal(str(request.data.get("value")))
            record_date = (
                date.fromisoformat(request.data["record_date"]) if request.data.get("record_date") else None
            )
            payment_date = (
                date.fromisoformat(request.data["payment_date"]) if request.data.get("payment_date") else None
            )
        except (ValueError, InvalidOperation, TypeError) as exc:
            raise ValidationError("日期或数值格式无效") from exc
        if value <= 0:
            raise ValidationError({"value": ["必须大于0"]})
        action = record_manual_corporate_action(
            instrument,
            kind=kind,
            effective_date=effective_date,
            value=value,
            record_date=record_date,
            payment_date=payment_date,
        )
        record_audit("admin.corporate_action_created", actor=request.user, target=action, request=request)
        return Response({"id": action.id, "kind": action.kind}, status=201)


class AdminBatchListView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(MarketDataBatch.objects.all(), request)
        return paginator.get_paginated_response(MarketDataBatchSerializer(page, many=True).data)

    def post(self, request):
        full_refresh = request.data.get("full_refresh", False)
        if not isinstance(full_refresh, bool):
            raise ValidationError({"full_refresh": ["必须为布尔值"]})
        task = update_market_data.delay(f"admin:{request.user.id}", full_refresh)
        record_audit(
            "admin.market_update_requested",
            actor=request.user,
            request=request,
            detail={"task_id": task.id, "full_refresh": full_refresh},
        )
        return Response({"job_id": task.id, "status": "queued"}, status=202)
