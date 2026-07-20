from __future__ import annotations

import csv
import io
import json
import zipfile

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import DefaultPagination
from apps.strategies.models import StrategyVersion

from .models import BacktestRun
from .serializers import BacktestCreateSerializer, BacktestListSerializer, BacktestRunSerializer
from .services import create_backtest
from .tasks import run_backtest


class BacktestListCreateView(APIView):
    throttle_scope = "backtest"

    def get(self, request):
        paginator = DefaultPagination()
        queryset = BacktestRun.objects.filter(user=request.user).select_related(
            "strategy_version", "snapshot"
        )
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(BacktestListSerializer(page, many=True).data)

    def post(self, request):
        serializer = BacktestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        strategy = get_object_or_404(
            StrategyVersion,
            pk=serializer.validated_data.pop("strategy_version_id"),
            active=True,
        )
        try:
            run = create_backtest(user=request.user, strategy=strategy, **serializer.validated_data)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if run.status == BacktestRun.Status.QUEUED and not run.task_id:
            task = run_backtest.delay(str(run.id))
            run.task_id = task.id
            run.save(update_fields=["task_id"])
        return Response({"id": run.id, "job_id": run.task_id, "status": run.status}, status=202)


class BacktestDetailView(APIView):
    def get(self, request, run_id):
        run = get_object_or_404(
            BacktestRun.objects.select_related("strategy_version", "snapshot"),
            pk=run_id,
            user=request.user,
        )
        return Response(BacktestRunSerializer(run).data)


class BacktestCancelView(APIView):
    @transaction.atomic
    def post(self, request, run_id):
        run = get_object_or_404(BacktestRun.objects.select_for_update(), pk=run_id, user=request.user)
        if run.status != BacktestRun.Status.QUEUED:
            raise ValidationError("只有排队中的回测可以取消")
        run.status = BacktestRun.Status.CANCELLED
        run.save(update_fields=["status"])
        return Response({"status": run.status})


class BacktestExportView(APIView):
    def get(self, request, run_id):
        run = get_object_or_404(
            BacktestRun, pk=run_id, user=request.user, status=BacktestRun.Status.SUCCEEDED
        )
        export_format = request.query_params.get("format", "json")
        if export_format == "json":
            response = Response(run.result)
            response["Content-Disposition"] = f'attachment; filename="backtest-{run.id}.json"'
            return response
        if export_format != "csv":
            raise ValidationError({"format": ["仅支持 json 或 csv"]})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "metrics.json", json.dumps(run.result.get("metrics", {}), ensure_ascii=False, indent=2)
            )
            for name in ["nav", "holdings", "trades", "allocations", "rejected_orders"]:
                rows = run.result.get(name, [])
                text = io.StringIO()
                if rows:
                    fieldnames = sorted({key for row in rows for key in row})
                    writer = csv.DictWriter(text, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(
                            {
                                key: json.dumps(value, ensure_ascii=False)
                                if isinstance(value, dict | list)
                                else value
                                for key, value in row.items()
                            }
                        )
                archive.writestr(f"{name}.csv", text.getvalue())
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="backtest-{run.id}.zip"'
        return response
