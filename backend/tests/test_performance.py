from __future__ import annotations

from datetime import date
from decimal import Decimal
from time import perf_counter

import numpy as np
import pandas as pd

from apps.backtests.engine import run_event_backtest
from apps.market.calendar import sessions_in_range
from apps.strategies.engine import DEFENSIVE_WEIGHTS, RISK_SYMBOLS


def test_ten_year_eight_etf_backtest_completes_within_release_budget():
    dates = pd.to_datetime(sessions_in_range(date(2016, 1, 4), date(2025, 12, 31)))
    symbols = RISK_SYMBOLS + list(DEFENSIVE_WEIGHTS)
    session = np.arange(len(dates), dtype=float)
    hfq = pd.DataFrame(
        {
            symbol: (3.0 + index * 0.12)
            * np.exp((0.00012 + index * 0.000015) * session)
            * (1 + 0.025 * np.sin(session / (21 + index)))
            for index, symbol in enumerate(symbols)
        },
        index=dates,
    )
    raw = pd.concat(
        {
            "open": hfq,
            "high": hfq * 1.012,
            "low": hfq * 0.988,
            "close": hfq * 1.002,
            "volume": hfq * 0 + 2_000_000,
        },
        axis=1,
    )

    started = perf_counter()
    result = run_event_backtest(
        strategy_slug="relative-momentum-top-n",
        raw=raw,
        hfq=hfq,
        start_date=date(2016, 1, 4),
        end_date=date(2025, 12, 31),
        initial_capital=Decimal("100000"),
    )
    elapsed = perf_counter() - started

    assert len(symbols) == 8
    assert len(result["nav"]) > 2400
    assert result["trades"]
    assert elapsed < 30, f"10-year benchmark took {elapsed:.2f}s"
