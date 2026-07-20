from __future__ import annotations

import uuid

from django.db import models


class Instrument(models.Model):
    class Exchange(models.TextChoices):
        SHANGHAI = "XSHG", "上海证券交易所"
        SHENZHEN = "XSHE", "深圳证券交易所"

    symbol = models.CharField(primary_key=True, max_length=6)
    name = models.CharField(max_length=80)
    exchange = models.CharField(max_length=4, choices=Exchange.choices)
    lot_size = models.PositiveIntegerField(default=100)
    listed_on = models.DateField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["symbol"]

    def __str__(self) -> str:
        return f"{self.symbol} {self.name}"


class MarketDataBatch(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        HEALTHY = "healthy", "正常"
        DEGRADED = "degraded", "异常"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=40, default="eastmoney-akshare")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING, db_index=True)
    expected_session = models.DateField(null=True, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    triggered_by = models.CharField(max_length=80, default="scheduler")

    class Meta:
        ordering = ["-started_at"]


class MarketBar(models.Model):
    class Adjustment(models.TextChoices):
        RAW = "raw", "不复权"
        BACK = "hfq", "后复权"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="bars")
    batch = models.ForeignKey(MarketDataBatch, on_delete=models.PROTECT, related_name="bars")
    trade_date = models.DateField(db_index=True)
    adjustment = models.CharField(max_length=3, choices=Adjustment.choices)
    open = models.DecimalField(max_digits=18, decimal_places=6)
    high = models.DecimalField(max_digits=18, decimal_places=6)
    low = models.DecimalField(max_digits=18, decimal_places=6)
    close = models.DecimalField(max_digits=18, decimal_places=6)
    volume = models.DecimalField(max_digits=24, decimal_places=2)
    is_current = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["instrument", "adjustment", "trade_date", "is_current"])]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "trade_date", "adjustment"],
                condition=models.Q(is_current=True),
                name="one_current_market_bar",
            )
        ]


class CorporateAction(models.Model):
    class Kind(models.TextChoices):
        CASH_DIVIDEND = "cash_dividend", "现金分红"
        SPLIT = "split", "份额拆分"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="corporate_actions")
    batch = models.ForeignKey(MarketDataBatch, on_delete=models.PROTECT, related_name="corporate_actions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    record_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField(db_index=True)
    payment_date = models.DateField(null=True, blank=True)
    value = models.DecimalField(max_digits=18, decimal_places=8)
    source_detail = models.JSONField(default=dict, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "kind", "effective_date"],
                condition=models.Q(is_current=True),
                name="one_current_corporate_action",
            )
        ]


class DatasetSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cutoff_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    digest = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=40)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
