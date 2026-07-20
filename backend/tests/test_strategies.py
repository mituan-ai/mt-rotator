from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.market.calendar import sessions_in_range
from apps.strategies.engine import DEFENSIVE_WEIGHTS, RISK_SYMBOLS, evaluate


def price_frame(start="2023-01-01", end="2025-03-31") -> pd.DataFrame:
    dates = pd.to_datetime(sessions_in_range(pd.Timestamp(start).date(), pd.Timestamp(end).date()))
    base = np.linspace(100, 180, len(dates))
    return pd.DataFrame(
        {
            symbol: base * (1 + index * 0.0004 * np.arange(len(dates)))
            for index, symbol in enumerate(RISK_SYMBOLS + list(DEFENSIVE_WEIGHTS))
        },
        index=dates,
    )


@pytest.mark.parametrize(
    "slug",
    ["equity-bond-trend", "relative-momentum-top-n", "moving-average-equal-weight"],
)
def test_three_strategies_are_deterministic_and_fully_allocated(slug):
    frame = price_frame()
    signal_date = pd.Timestamp("2025-03-31").date()
    first = evaluate(slug, frame, signal_date)
    second = evaluate(slug, frame, signal_date)
    assert first == second
    assert sum(first.target_weights.values()) == pytest.approx(1.0)
    assert first.tradable_on > first.signal_date


def test_future_prices_cannot_change_past_signal():
    frame = price_frame()
    signal_date = pd.Timestamp("2025-02-28").date()
    before = evaluate("relative-momentum-top-n", frame, signal_date)
    frame.loc[frame.index > pd.Timestamp(signal_date), "510300"] *= 100
    after = evaluate("relative-momentum-top-n", frame, signal_date)
    assert before == after


def test_pre_listing_missing_values_are_not_backfilled():
    frame = price_frame()
    frame.loc[frame.index < "2025-01-01", "515300"] = np.nan
    decision = evaluate("moving-average-equal-weight", frame, pd.Timestamp("2025-03-31").date())
    assert decision.rationale["assets"]["515300"]["reason"] == "insufficient_data"
