from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from apps.backtests.engine import run_event_backtest
from apps.market.calendar import sessions_in_range
from apps.strategies.engine import DEFENSIVE_WEIGHTS, RISK_SYMBOLS


def test_event_backtest_fills_only_after_confirmed_daily_advice():
    dates = pd.to_datetime(sessions_in_range(date(2023, 1, 3), date(2025, 3, 31)))
    symbols = RISK_SYMBOLS + list(DEFENSIVE_WEIGHTS)
    hfq = pd.DataFrame(
        {
            symbol: np.linspace(3 + index * 0.1, 6 + index * 0.4, len(dates))
            for index, symbol in enumerate(symbols)
        },
        index=dates,
    )
    fields = {}
    for field, multiplier in {
        "open": 1.0,
        "high": 1.02,
        "low": 0.98,
        "close": 1.01,
        "volume": 1_000_000,
    }.items():
        fields[field] = hfq * multiplier if field != "volume" else hfq * 0 + multiplier
    raw = pd.concat(fields, axis=1)

    result = run_event_backtest(
        strategy_slug="relative-momentum-top-n",
        raw=raw,
        hfq=hfq,
        start_date=date(2024, 3, 1),
        end_date=date(2025, 3, 31),
        initial_capital=Decimal("100000"),
    )

    assert result["trades"]
    first = result["trades"][0]
    allocation = next(item for item in result["allocations"] if item["signal_date"] == first["signal_date"])
    assert first["date"] == allocation["tradable_on"]
    assert first["date"] > first["signal_date"]
    assert first["estimated"] is True
    assert result["holdings"]
