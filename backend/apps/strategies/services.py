from __future__ import annotations

import hashlib
import inspect
from datetime import date
from typing import Any

from django.db import transaction

from apps.market.models import DatasetSnapshot
from apps.market.services import create_snapshot, load_snapshot_frames

from . import engine
from .models import Signal, StrategyVersion

STRATEGY_VERSION = "2.1.0"
EXECUTION_ASSUMPTIONS = {
    "initial_capital": "100000.00",
    "commission_rate": "0.0003",
    "minimum_commission": "5.00",
    "slippage_bps": 5,
    "lot_size": 100,
    "fill_timing": "next_session_open",
}
STRATEGY_SEED: list[dict[str, Any]] = [
    {
        "slug": "equity-bond-trend",
        "name": "趋势轮动",
        "description": "根据沪深300长期趋势，在主要ETF中选择六个月动量较强的标的。",
        "parameters": {"benchmark": "510300", "moving_average_sessions": 200, "momentum_sessions": 126},
    },
    {
        "slug": "relative-momentum-top-n",
        "name": "相对动量",
        "description": "综合一、三、六和十二个月收益，在主要ETF中筛选相对强势标的。",
        "parameters": {"momentum_sessions": [21, 63, 126, 252], "maximum_targets": 8},
    },
    {
        "slug": "moving-average-equal-weight",
        "name": "均线趋势",
        "description": "筛选高于二百日均线的主要ETF，并对相关标的去重后等权配置。",
        "parameters": {"moving_average_sessions": 200, "maximum_targets": 8},
    },
]


def current_strategy_code_hash() -> str:
    return hashlib.sha256(inspect.getsource(engine).encode()).hexdigest()


def ensure_strategy_implementation(version: StrategyVersion) -> None:
    if version.code_hash != current_strategy_code_hash():
        raise ValueError("策略代码与已发布版本摘要不一致，请发布新版本")


def seed_strategy_catalog() -> list[StrategyVersion]:
    versions = []
    source_hash = current_strategy_code_hash()
    for definition in STRATEGY_SEED:
        StrategyVersion.objects.filter(slug=definition["slug"], active=True).exclude(
            version=STRATEGY_VERSION
        ).update(active=False)
        version, _ = StrategyVersion.objects.get_or_create(
            slug=definition["slug"],
            version=STRATEGY_VERSION,
            defaults={
                "name": definition["name"],
                "description": definition["description"],
                "code_hash": source_hash,
                "parameters": {**definition["parameters"], "execution": EXECUTION_ASSUMPTIONS},
                "risk_symbols": [],
                "defensive_weights": {},
                "active": True,
                "locked": True,
            },
        )
        if not version.active:
            StrategyVersion.objects.filter(pk=version.pk).update(active=True)
            version.active = True
        versions.append(version)
    return versions


@transaction.atomic
def generate_signal(
    strategy_version: StrategyVersion,
    *,
    snapshot: DatasetSnapshot | None = None,
    signal_date: date | None = None,
    require_month_end: bool = False,
) -> Signal:
    snapshot = snapshot or create_snapshot()
    effective_date = signal_date or snapshot.cutoff_date
    if effective_date > snapshot.cutoff_date:
        raise ValueError("信号日期不能晚于数据快照截止日")
    ensure_strategy_implementation(strategy_version)
    raw, total_return = load_snapshot_frames(snapshot)
    amounts = raw["amount"] if not raw.empty and "amount" in raw else None
    decision = engine.evaluate(strategy_version.slug, total_return, effective_date, amounts)
    signal, _ = Signal.objects.get_or_create(
        strategy_version=strategy_version,
        signal_date=effective_date,
        defaults={
            "snapshot": snapshot,
            "tradable_on": decision.tradable_on,
            "target_weights": decision.target_weights,
            "rationale": decision.rationale,
        },
    )
    return signal


def generate_all_daily_signals(snapshot: DatasetSnapshot | None = None) -> list[Signal]:
    snapshot = snapshot or create_snapshot()
    return [
        generate_signal(version, snapshot=snapshot) for version in StrategyVersion.objects.filter(active=True)
    ]


def generate_all_month_end_signals(snapshot: DatasetSnapshot | None = None) -> list[Signal]:
    return generate_all_daily_signals(snapshot)
