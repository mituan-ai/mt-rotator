from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuditEvent
from .pagination import DefaultPagination
from .permissions import IsAdministrator
from .serializers import AuditEventSerializer


class LiveView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "mt-rotator", "time": timezone.now()})


class ReadyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return Response({"status": "not_ready", "database": "unavailable"}, status=503)
        try:
            cache.set("health:ready", "ok", timeout=10)
            if cache.get("health:ready") != "ok":
                raise RuntimeError("cache round trip failed")
        except Exception:
            return Response({"status": "not_ready", "database": "ok", "cache": "unavailable"}, status=503)
        return Response({"status": "ready", "database": "ok", "cache": "ok"})


class DataFreshnessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.market.services import current_data_status

        status_payload = current_data_status()
        last_batch = status_payload["last_batch"]
        payload = {
            "status": "fresh" if status_payload["ready"] else "stale",
            "expected_session": status_payload["expected_session"],
            "last_batch_status": last_batch["status"] if last_batch else None,
        }
        return Response(payload, status=200 if status_payload["ready"] else 503)


class AuditListView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(AuditEvent.objects.select_related("actor").all(), request)
        return paginator.get_paginated_response(AuditEventSerializer(page, many=True).data)
