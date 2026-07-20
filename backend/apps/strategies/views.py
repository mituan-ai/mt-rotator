from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.core.permissions import IsAdministrator

from .models import Signal, StrategyVersion
from .serializers import SignalSerializer, StrategyVersionSerializer
from .services import generate_signal


class StrategyListView(APIView):
    def get(self, request):
        versions = StrategyVersion.objects.filter(active=True)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(versions, request)
        return paginator.get_paginated_response(StrategyVersionSerializer(page, many=True).data)


class StrategyVersionHistoryView(APIView):
    def get(self, request, slug):
        versions = StrategyVersion.objects.filter(slug=slug)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(versions, request)
        return paginator.get_paginated_response(StrategyVersionSerializer(page, many=True).data)


class AdminStrategyListView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(StrategyVersion.objects.all(), request)
        return paginator.get_paginated_response(StrategyVersionSerializer(page, many=True).data)


class StrategyDetailView(APIView):
    def get(self, request, slug):
        version = get_object_or_404(StrategyVersion, slug=slug, active=True)
        data = StrategyVersionSerializer(version).data
        latest = version.signals.select_related("snapshot").first()
        data["latest_signal"] = SignalSerializer(latest).data if latest else None
        return Response(data)


class SignalListView(APIView):
    def get(self, request, slug):
        version = get_object_or_404(StrategyVersion, slug=slug, active=True)
        signals = Signal.objects.filter(strategy_version=version).select_related(
            "strategy_version", "snapshot"
        )
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(signals, request)
        return paginator.get_paginated_response(SignalSerializer(page, many=True).data)


class LatestSignalView(APIView):
    def get(self, request, slug):
        version = get_object_or_404(StrategyVersion, slug=slug, active=True)
        signal = version.signals.select_related("snapshot", "strategy_version").first()
        if not signal:
            return Response({"detail": "尚无有效信号"}, status=404)
        return Response(SignalSerializer(signal).data)


class AdminSignalGenerateView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request, slug):
        version = get_object_or_404(StrategyVersion, slug=slug, active=True)
        try:
            signal = generate_signal(version)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        record_audit("admin.signal_generated", actor=request.user, target=signal, request=request)
        return Response(SignalSerializer(signal).data, status=201)


class AdminStrategyStatusView(APIView):
    permission_classes = [IsAdministrator]

    def patch(self, request, strategy_id):
        version = get_object_or_404(StrategyVersion, pk=strategy_id)
        if not isinstance(request.data.get("active"), bool):
            raise ValidationError({"active": ["必须为布尔值"]})
        StrategyVersion.objects.filter(pk=version.pk).update(active=request.data["active"])
        version.refresh_from_db()
        record_audit(
            "admin.strategy_status_changed",
            actor=request.user,
            target=version,
            request=request,
            detail={"active": version.active},
        )
        return Response(StrategyVersionSerializer(version).data)
