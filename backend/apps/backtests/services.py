from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.market.services import corporate_actions_for_snapshot, create_snapshot, load_snapshot_frames
from apps.strategies.models import StrategyVersion
from apps.strategies.services import ensure_strategy_implementation

from .models import BacktestRun


def backtest_input_hash(*, strategy_id, snapshot_id, start_date: date, end_date: date) -> str:
    payload = [
        str(strategy_id),
        str(snapshot_id),
        start_date.isoformat(),
        end_date.isoformat(),
        "100000",
        "fees-v1",
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


@transaction.atomic
def create_backtest(*, user, strategy: StrategyVersion, start_date: date, end_date: date) -> BacktestRun:
    if start_date >= end_date:
        raise ValueError("开始日期必须早于结束日期")
    snapshot = create_snapshot(cutoff_date=end_date)
    effective_end = min(end_date, snapshot.cutoff_date)
    input_hash = backtest_input_hash(
        strategy_id=strategy.id,
        snapshot_id=snapshot.id,
        start_date=start_date,
        end_date=effective_end,
    )
    existing = BacktestRun.objects.filter(
        user=user, input_hash=input_hash, status=BacktestRun.Status.SUCCEEDED
    ).first()
    if existing:
        return existing
    return BacktestRun.objects.create(
        user=user,
        strategy_version=strategy,
        snapshot=snapshot,
        start_date=start_date,
        end_date=effective_end,
        input_hash=input_hash,
    )


def execute_backtest(run: BacktestRun) -> dict:
    from .engine import run_event_backtest

    ensure_strategy_implementation(run.strategy_version)
    raw, hfq = load_snapshot_frames(run.snapshot)
    actions = corporate_actions_for_snapshot(run.snapshot, through=run.end_date)
    return run_event_backtest(
        strategy_slug=run.strategy_version.slug,
        raw=raw,
        hfq=hfq,
        start_date=run.start_date,
        end_date=run.end_date,
        actions=actions,
        initial_capital=Decimal(run.initial_capital),
    )
