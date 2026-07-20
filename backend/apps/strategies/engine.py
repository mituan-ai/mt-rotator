from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from apps.market.calendar import next_session

RISK_SYMBOLS = ["510300", "510500", "159915", "510880", "515300"]
DEFENSIVE_WEIGHTS = {"511160": 0.70, "511990": 0.20, "511010": 0.10}
WARMUP_SESSIONS = 252


@dataclass(frozen=True)
class StrategyDecision:
    signal_date: date
    tradable_on: date
    target_weights: dict[str, float]
    rationale: dict


def _history(hfq: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    frame = hfq.loc[hfq.index <= pd.Timestamp(signal_date)].copy()
    if len(frame) < WARMUP_SESSIONS:
        raise ValueError(f"策略至少需要 {WARMUP_SESSIONS} 个交易日预热")
    return frame


def _defensive(total: float = 1.0) -> dict[str, float]:
    return {symbol: round(weight * total, 10) for symbol, weight in DEFENSIVE_WEIGHTS.items()}


def _momentum(series: pd.Series, periods: int) -> float | None:
    clean = series.dropna()
    if len(clean) <= periods:
        return None
    start = float(clean.iloc[-periods - 1])
    end = float(clean.iloc[-1])
    return end / start - 1 if start > 0 else None


def equity_bond_trend(hfq: pd.DataFrame, signal_date: date) -> StrategyDecision:
    history = _history(hfq, signal_date)
    benchmark = history["510300"].dropna().resample("ME").last()
    if len(benchmark) < 10:
        raise ValueError("沪深300ETF月线不足10个月")
    current = float(benchmark.iloc[-1])
    moving_average = float(benchmark.tail(10).mean())
    scores = {symbol: _momentum(history[symbol], 126) for symbol in RISK_SYMBOLS}
    eligible = {symbol: score for symbol, score in scores.items() if score is not None and score > 0}
    selected = max(eligible, key=lambda symbol: eligible[symbol]) if eligible else None
    risk_on = current > moving_average and selected is not None
    weights = _defensive(0.65 if risk_on else 1.0)
    if risk_on and selected:
        weights[selected] = 0.35
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=weights,
        rationale={
            "risk_on": risk_on,
            "benchmark_close": round(current, 6),
            "benchmark_sma_10m": round(moving_average, 6),
            "momentum_6m": {
                key: round(value, 6) if value is not None else None for key, value in scores.items()
            },
            "selected": [selected] if selected else [],
        },
    )


def relative_momentum_top_n(hfq: pd.DataFrame, signal_date: date) -> StrategyDecision:
    history = _history(hfq, signal_date)
    scores = {symbol: _momentum(history[symbol], 126) for symbol in RISK_SYMBOLS}
    ranked = sorted(
        ((symbol, score) for symbol, score in scores.items() if score is not None and score > 0),
        key=lambda item: item[1],
        reverse=True,
    )[:2]
    weights: dict[str, float] = {}
    if len(ranked) == 2:
        weights = {ranked[0][0]: 0.5, ranked[1][0]: 0.5}
    elif len(ranked) == 1:
        weights = {ranked[0][0]: 0.5, **_defensive(0.5)}
    else:
        weights = _defensive()
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=weights,
        rationale={
            "momentum_6m": {
                key: round(value, 6) if value is not None else None for key, value in scores.items()
            },
            "selected": [item[0] for item in ranked],
        },
    )


def moving_average_equal_weight(hfq: pd.DataFrame, signal_date: date) -> StrategyDecision:
    history = _history(hfq, signal_date)
    eligible: list[str] = []
    diagnostics: dict[str, dict] = {}
    for symbol in RISK_SYMBOLS:
        clean = history[symbol].dropna()
        if len(clean) < 200:
            diagnostics[symbol] = {"eligible": False, "reason": "insufficient_data"}
            continue
        current = float(clean.iloc[-1])
        average = float(clean.tail(200).mean())
        is_eligible = current > average
        diagnostics[symbol] = {
            "close": round(current, 6),
            "sma_200": round(average, 6),
            "eligible": is_eligible,
        }
        if is_eligible:
            eligible.append(symbol)
    weights = {symbol: round(1 / len(eligible), 10) for symbol in eligible} if eligible else _defensive()
    if weights:
        difference = 1 - sum(weights.values())
        weights[next(iter(weights))] += difference
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=weights,
        rationale={"assets": diagnostics, "selected": eligible},
    )


STRATEGY_FUNCTIONS = {
    "equity-bond-trend": equity_bond_trend,
    "relative-momentum-top-n": relative_momentum_top_n,
    "moving-average-equal-weight": moving_average_equal_weight,
}


def evaluate(slug: str, hfq: pd.DataFrame, signal_date: date) -> StrategyDecision:
    try:
        strategy = STRATEGY_FUNCTIONS[slug]
    except KeyError as exc:
        raise ValueError(f"未知策略: {slug}") from exc
    return strategy(hfq, signal_date)
