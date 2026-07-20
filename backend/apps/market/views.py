from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.core.permissions import IsAdministrator

from .models import Instrument, MarketBar, MarketDataBatch
from .serializers import InstrumentSerializer, MarketBarSerializer, MarketDataBatchSerializer
from .services import REQUIRED_SYMBOLS, current_data_status
from .tasks import update_market_data


class MarketStatusView(APIView):
    def get(self, request):
        return Response(current_data_status())


class InstrumentListView(APIView):
    def get(self, request):
        items = Instrument.objects.filter(symbol__in=REQUIRED_SYMBOLS, enabled=True)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(items, request)
        return paginator.get_paginated_response(InstrumentSerializer(page, many=True).data)


class InstrumentBarsView(APIView):
    def get(self, request, symbol):
        instrument = get_object_or_404(Instrument, symbol=symbol, enabled=True)
        adjustment = request.query_params.get("adjustment", "raw")
        if adjustment not in {"raw", "hfq"}:
            raise ValidationError({"adjustment": ["仅支持 raw 或 hfq"]})
        queryset = MarketBar.objects.filter(instrument=instrument, adjustment=adjustment, is_current=True)
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
                "source": "东方财富，经 AKShare 获取",
                "bars": MarketBarSerializer(queryset, many=True).data,
            }
        )


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
