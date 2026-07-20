from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.market.models import DatasetSnapshot


class StrategyVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240)
    version = models.CharField(max_length=20)
    code_hash = models.CharField(max_length=64)
    parameters = models.JSONField(default=dict)
    risk_symbols = models.JSONField(default=list)
    defensive_weights = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    locked = models.BooleanField(default=True)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "-published_at"]
        constraints = [models.UniqueConstraint(fields=["slug", "version"], name="unique_strategy_version")]

    def save(self, *args, **kwargs):
        if self.pk and StrategyVersion.objects.filter(pk=self.pk, locked=True).exists():
            original = StrategyVersion.objects.get(pk=self.pk)
            immutable = [
                "slug",
                "name",
                "description",
                "version",
                "code_hash",
                "parameters",
                "risk_symbols",
                "defensive_weights",
            ]
            if any(getattr(original, field) != getattr(self, field) for field in immutable):
                raise ValidationError("已发布策略版本不可修改，请发布新版本")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


class Signal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="signals")
    snapshot = models.ForeignKey(DatasetSnapshot, on_delete=models.PROTECT, related_name="signals")
    signal_date = models.DateField(db_index=True)
    tradable_on = models.DateField(db_index=True)
    target_weights = models.JSONField(default=dict)
    rationale = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-signal_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["strategy_version", "signal_date"], name="unique_strategy_signal_date"
            )
        ]
