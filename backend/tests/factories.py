from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.market.models import MarketBar, MarketDataBatch
from apps.market.services import REQUIRED_SYMBOLS, seed_instruments


def completed_batch(*, expected: date, status: str = MarketDataBatch.Status.HEALTHY) -> MarketDataBatch:
    return MarketDataBatch.objects.create(
        status=status,
        expected_session=expected,
        row_count=1,
        finished_at=timezone.now(),
    )


def seed_ready_day(expected: date, *, close: Decimal = Decimal("4.000000")) -> MarketDataBatch:
    instruments = {item.symbol: item for item in seed_instruments()}
    batch = completed_batch(expected=expected)
    for symbol in REQUIRED_SYMBOLS:
        for adjustment in [MarketBar.Adjustment.RAW, MarketBar.Adjustment.BACK]:
            MarketBar.objects.create(
                instrument=instruments[symbol],
                batch=batch,
                trade_date=expected,
                adjustment=adjustment,
                open=close,
                high=close + Decimal("0.100000"),
                low=close - Decimal("0.100000"),
                close=close,
                volume=Decimal("1000000.00"),
            )
    return batch
