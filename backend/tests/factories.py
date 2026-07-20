from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.backtests.models import BacktestRun
from apps.market.models import DatasetSnapshot, Instrument, MarketBar, MarketDataBatch
from apps.market.services import REQUIRED_SYMBOLS, seed_instruments
from apps.strategies.services import seed_strategy_catalog


def completed_batch(*, expected: date, status: str = MarketDataBatch.Status.HEALTHY) -> MarketDataBatch:
    return MarketDataBatch.objects.create(
        status=status,
        expected_session=expected,
        row_count=1,
        metadata={"catalog_count": 1},
        finished_at=timezone.now(),
    )


def seed_ready_day(expected: date, *, close: Decimal = Decimal("4.000000")) -> MarketDataBatch:
    instruments = {item.symbol: item for item in seed_instruments()}
    batch = completed_batch(expected=expected)
    for symbol in REQUIRED_SYMBOLS:
        instrument = instruments[symbol]
        instrument.data_status = Instrument.DataStatus.READY
        instrument.last_bar_date = expected
        instrument.average_amount_20d = Decimal("20000000")
        instrument.trade_eligible = True
        instrument.advice_eligible = True
        instrument.metadata = {**instrument.metadata, "valid_bar_count": 252}
        instrument.save()
        MarketBar.objects.create(
            instrument=instrument,
            batch=batch,
            trade_date=expected,
            adjustment=MarketBar.Adjustment.RAW,
            open=close,
            high=close + Decimal("0.100000"),
            low=close - Decimal("0.100000"),
            close=close,
            volume=Decimal("1000000.00"),
            amount=Decimal("20000000.00"),
        )
    return batch


def create_backtest_run(user) -> BacktestRun:
    strategy = seed_strategy_catalog()[0]
    snapshot = DatasetSnapshot.objects.create(
        cutoff_date=date(2025, 3, 31),
        digest=uuid.uuid4().hex * 2,
        provider="test",
    )
    return BacktestRun.objects.create(
        user=user,
        strategy_version=strategy,
        snapshot=snapshot,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 3, 31),
        input_hash=uuid.uuid4().hex * 2,
    )
