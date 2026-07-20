from __future__ import annotations

import hashlib
import inspect
from datetime import date

from django.db import transaction

from apps.market.calendar import is_month_end_session
from apps.market.models import DatasetSnapshot
from apps.market.services import create_snapshot, load_snapshot_frames

from . import engine
from .engine import DEFENSIVE_WEIGHTS, RISK_SYMBOLS
from .models import Signal, StrategyVersion

STRATEGY_SEED = [
    {
        "slug": "equity-bond-trend",
        "name": "股债趋势轮动",
        "description": "以沪深300十月均线判断风险环境，并用六个月动量选择权益ETF。",
        "parameters": {
            "benchmark": "510300",
            "moving_average_months": 10,
            "momentum_sessions": 126,
            "risk_weight": 0.35,
            "execution": {
                "initial_capital": "100000.00",
                "commission_rate": "0.0003",
                "minimum_commission": "5.00",
                "slippage_bps": 5,
                "lot_size": 100,
            },
        },
    },
    {
        "slug": "relative-momentum-top-n",
        "name": "ETF相对动量Top-N",
        "description": "选择六个月收益为正的前两只ETF，并在候选不足时回到防御资产。",
        "parameters": {
            "momentum_sessions": 126,
            "top_n": 2,
            "execution": {
                "initial_capital": "100000.00",
                "commission_rate": "0.0003",
                "minimum_commission": "5.00",
                "slippage_bps": 5,
                "lot_size": 100,
            },
        },
    },
    {
        "slug": "moving-average-equal-weight",
        "name": "均线趋势等权",
        "description": "等权持有价格高于二百日均线的ETF，无合格资产时进入防御组合。",
        "parameters": {
            "moving_average_sessions": 200,
            "execution": {
                "initial_capital": "100000.00",
                "commission_rate": "0.0003",
                "minimum_commission": "5.00",
                "slippage_bps": 5,
                "lot_size": 100,
            },
        },
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
        version, _ = StrategyVersion.objects.get_or_create(
            slug=definition["slug"],
            version="1.0.0",
            defaults={
                "name": definition["name"],
                "description": definition["description"],
                "code_hash": source_hash,
                "parameters": definition["parameters"],
                "risk_symbols": RISK_SYMBOLS,
                "defensive_weights": DEFENSIVE_WEIGHTS,
                "active": True,
                "locked": True,
            },
        )
        versions.append(version)
    return versions


@transaction.atomic
def generate_signal(
    strategy_version: StrategyVersion,
    *,
    snapshot: DatasetSnapshot | None = None,
    signal_date: date | None = None,
    require_month_end: bool = True,
) -> Signal:
    snapshot = snapshot or create_snapshot()
    effective_date = signal_date or snapshot.cutoff_date
    if effective_date > snapshot.cutoff_date:
        raise ValueError("信号日期不能晚于数据快照截止日")
    if require_month_end and not is_month_end_session(effective_date):
        raise ValueError("当前不是月末交易日")
    ensure_strategy_implementation(strategy_version)
    _, hfq = load_snapshot_frames(snapshot)
    decision = engine.evaluate(strategy_version.slug, hfq, effective_date)
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


def generate_all_month_end_signals(snapshot: DatasetSnapshot | None = None) -> list[Signal]:
    snapshot = snapshot or create_snapshot()
    if not is_month_end_session(snapshot.cutoff_date):
        return []
    return [
        generate_signal(version, snapshot=snapshot) for version in StrategyVersion.objects.filter(active=True)
    ]
