from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.market.models import Instrument
from apps.strategies.models import Signal, StrategyVersion


class PaperAccount(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "运行中"
        ARCHIVED = "archived", "已归档"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="paper_accounts"
    )
    strategy_version = models.ForeignKey(
        StrategyVersion, on_delete=models.PROTECT, related_name="paper_accounts"
    )
    generation = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    initial_capital = models.DecimalField(max_digits=18, decimal_places=2, default=100000)
    cash = models.DecimalField(max_digits=18, decimal_places=2, default=100000)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "strategy_version"],
                condition=models.Q(status="active"),
                name="one_active_paper_account_per_strategy",
            ),
            models.UniqueConstraint(
                fields=["user", "strategy_version", "generation"], name="unique_account_generation"
            ),
        ]


class Position(models.Model):
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    shares = models.PositiveIntegerField(default=0)
    average_cost = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "instrument"], name="unique_account_position")
        ]


class PaperRebalance(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待估算"
        PROCESSED = "processed", "已处理"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="rebalances")
    signal = models.ForeignKey(
        Signal, null=True, blank=True, on_delete=models.PROTECT, related_name="paper_rebalances"
    )
    eligible_on = models.DateField(db_index=True)
    target_weights = models.JSONField(default=dict)
    source = models.CharField(max_length=20, choices=[("signal", "月末信号"), ("activation", "账户激活")])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "signal"],
                condition=models.Q(signal__isnull=False),
                name="unique_account_signal_rebalance",
            )
        ]


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="orders")
    rebalance = models.ForeignKey(PaperRebalance, on_delete=models.PROTECT, related_name="orders")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    side = models.CharField(max_length=4, choices=[("buy", "买入"), ("sell", "卖出")])
    shares = models.PositiveIntegerField()
    eligible_on = models.DateField()
    status = models.CharField(max_length=10, choices=[("filled", "已成交"), ("rejected", "已拒绝")])
    rejection_reason = models.CharField(max_length=80, blank=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Fill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="fill")
    price = models.DecimalField(max_digits=18, decimal_places=6)
    fee = models.DecimalField(max_digits=18, decimal_places=2)
    filled_on = models.DateField(db_index=True)
    estimated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LedgerEntry(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "初始入金"
        BUY = "buy", "买入"
        SELL = "sell", "卖出"
        FEE = "fee", "费用"
        DIVIDEND = "dividend", "现金分红"
        SPLIT = "split", "份额拆分"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="ledger_entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    instrument = models.ForeignKey(Instrument, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    occurred_on = models.DateField(db_index=True)
    event_key = models.CharField(max_length=180, unique=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]


class NavSnapshot(models.Model):
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="nav_snapshots")
    date = models.DateField(db_index=True)
    value = models.DecimalField(max_digits=18, decimal_places=2)
    cash = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["account", "date"], name="unique_account_nav_date")]


class HoldingSnapshot(models.Model):
    account = models.ForeignKey(PaperAccount, on_delete=models.PROTECT, related_name="holding_snapshots")
    date = models.DateField(db_index=True)
    positions = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "date"], name="unique_account_holding_date")
        ]
