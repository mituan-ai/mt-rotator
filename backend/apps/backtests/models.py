from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.market.models import DatasetSnapshot
from apps.strategies.models import StrategyVersion


class BacktestRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="backtests")
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="backtests")
    snapshot = models.ForeignKey(DatasetSnapshot, on_delete=models.PROTECT, related_name="backtests")
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=18, decimal_places=2, default=100000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True)
    task_id = models.CharField(max_length=80, blank=True)
    attempt_count = models.PositiveIntegerField(default=0, null=True)
    lease_token = models.CharField(max_length=64, blank=True, null=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    input_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
