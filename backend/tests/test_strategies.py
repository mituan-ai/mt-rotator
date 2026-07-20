from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.market.calendar import sessions_in_range
from apps.strategies.engine import DEFENSIVE_WEIGHTS, RISK_SYMBOLS, _deduplicate, evaluate


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
def test_three_advice_strategies_are_deterministic(slug):
    frame = price_frame()
    signal_date = pd.Timestamp("2025-03-31").date()
    first = evaluate(slug, frame, signal_date)
    second = evaluate(slug, frame, signal_date)
    assert first == second
    assert sum(first.target_weights.values()) == pytest.approx(1.0)
    assert first.tradable_on > first.signal_date
    assert len(first.target_weights) <= 8


def test_future_prices_cannot_change_past_signal():
    frame = price_frame()
    signal_date = pd.Timestamp("2025-02-28").date()
    before = evaluate("relative-momentum-top-n", frame, signal_date)
    frame.loc[frame.index > pd.Timestamp(signal_date), "510300"] *= 100
    after = evaluate("relative-momentum-top-n", frame, signal_date)
    assert before == after


def test_pre_listing_missing_values_are_not_backfilled_or_selected():
    frame = price_frame()
    frame.loc[frame.index < "2025-01-01", "515300"] = np.nan
    decision = evaluate("moving-average-equal-weight", frame, pd.Timestamp("2025-03-31").date())
    assert "515300" not in decision.target_weights


def test_correlation_filter_scans_top_30_before_limiting_targets():
    random = np.random.default_rng(20260720)
    index = pd.date_range("2025-01-01", periods=80, freq="B")
    returns = {"A": random.normal(0.001, 0.01, len(index))}
    for number in range(7):
        returns[f"B{number}"] = random.normal(0.001, 0.01, len(index))
    returns["C"] = returns["A"]
    history = pd.DataFrame(
        {symbol: 100 * np.cumprod(1 + values) for symbol, values in returns.items()},
        index=index,
    )
    amounts = pd.DataFrame(1.0, index=index, columns=history.columns)
    amounts["C"] = 100.0
    ranked = [("A", 100.0), *[(f"B{number}", 99.0 - number) for number in range(7)], ("C", 90.0)]

    selected = [symbol for symbol, _ in _deduplicate(history, ranked, amounts)]

    assert len(selected) == 8
    assert "C" in selected
    assert "A" not in selected
