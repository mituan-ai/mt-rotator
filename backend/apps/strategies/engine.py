from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from apps.market.calendar import next_session

REFERENCE_SYMBOL = "510300"
WARMUP_SESSIONS = 252
MAX_RAW_CANDIDATES = 30
MAX_TARGETS = 8
CORRELATION_LIMIT = 0.95

# Synthetic fixtures and archived v1 backtests still use this compact sample.
RISK_SYMBOLS = ["510300", "510500", "159915", "510880", "515300"]
DEFENSIVE_WEIGHTS = {"511160": 0.70, "511990": 0.20, "511010": 0.10}


@dataclass(frozen=True)
class StrategyDecision:
    signal_date: date
    tradable_on: date
    target_weights: dict[str, float]
    rationale: dict


def _history(total_return: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    frame = total_return.loc[total_return.index <= pd.Timestamp(signal_date)].copy()
    if len(frame) < WARMUP_SESSIONS:
        raise ValueError(f"策略至少需要 {WARMUP_SESSIONS} 个交易日预热")
    return frame


def _momentum(series: pd.Series, periods: int) -> float | None:
    clean = series.dropna()
    if len(clean) <= periods:
        return None
    start = float(clean.iloc[-periods - 1])
    end = float(clean.iloc[-1])
    return end / start - 1 if start > 0 else None


def _volatility(series: pd.Series, periods: int = 60) -> float:
    returns = series.dropna().pct_change(fill_method=None).dropna().tail(periods)
    value = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    return max(value, 0.000001)


def _average_amount(amounts: pd.DataFrame | None, symbol: str) -> float:
    if amounts is None or symbol not in amounts:
        return 0.0
    values = amounts[symbol].dropna().tail(20)
    return float(values.mean()) if not values.empty else 0.0


def _deduplicate(
    history: pd.DataFrame,
    ranked: list[tuple[str, float]],
    amounts: pd.DataFrame | None,
) -> list[tuple[str, float]]:
    selected: list[tuple[str, float]] = []
    returns = history.pct_change(fill_method=None).tail(60)
    for candidate in ranked[:MAX_RAW_CANDIDATES]:
        symbol, _ = candidate
        correlated_indices = []
        for index, (selected_symbol, _) in enumerate(selected):
            pair = returns[[symbol, selected_symbol]].dropna()
            correlation = float(pair.corr().iloc[0, 1]) if len(pair) >= 40 else 0.0
            if correlation >= CORRELATION_LIMIT:
                correlated_indices.append(index)
        if not correlated_indices:
            selected.append(candidate)
            continue
        cluster = [selected[index] for index in correlated_indices]
        most_liquid = max(
            [*cluster, candidate],
            key=lambda item: (_average_amount(amounts, item[0]), item[1]),
        )
        if most_liquid == candidate:
            selected = [item for index, item in enumerate(selected) if index not in correlated_indices]
            selected.append(candidate)
    return sorted(selected, key=lambda item: item[1], reverse=True)[:MAX_TARGETS]


def _market_state(history: pd.DataFrame) -> tuple[str, dict]:
    if REFERENCE_SYMBOL not in history:
        raise ValueError("缺少沪深300ETF基准行情")
    benchmark = history[REFERENCE_SYMBOL].dropna()
    if len(benchmark) < 200:
        raise ValueError("沪深300ETF不足200个有效交易日")
    benchmark_close = float(benchmark.iloc[-1])
    benchmark_sma = float(benchmark.tail(200).mean())
    eligible = []
    above = 0
    for symbol in history.columns:
        clean = history[symbol].dropna()
        if len(clean) < 200:
            continue
        eligible.append(symbol)
        above += int(float(clean.iloc[-1]) > float(clean.tail(200).mean()))
    breadth = above / len(eligible) if eligible else 0.0
    checks = int(benchmark_close > benchmark_sma) + int(breadth >= 0.5)
    state = "strong" if checks == 2 else "neutral" if checks == 1 else "weak"
    return state, {
        "benchmark_close": round(benchmark_close, 6),
        "benchmark_sma_200": round(benchmark_sma, 6),
        "breadth_above_sma_200": round(breadth, 6),
    }


def _normalize_weights(
    history: pd.DataFrame, selected: list[tuple[str, float]], *, equal_weight: bool
) -> dict[str, float]:
    if not selected:
        return {}
    if equal_weight:
        raw = {symbol: 1.0 for symbol, _ in selected}
    else:
        raw = {symbol: 1 / _volatility(history[symbol]) for symbol, _ in selected}
    total = sum(raw.values())
    weights = {symbol: round(value / total, 10) for symbol, value in raw.items()}
    first = next(iter(weights))
    weights[first] = round(weights[first] + 1 - sum(weights.values()), 10)
    return weights


def equity_bond_trend(
    total_return: pd.DataFrame, signal_date: date, amounts: pd.DataFrame | None = None
) -> StrategyDecision:
    history = _history(total_return, signal_date)
    market_state, market = _market_state(history)
    benchmark_risk_on = market["benchmark_close"] > market["benchmark_sma_200"]
    scores = {
        symbol: _momentum(history[symbol], 126)
        for symbol in history.columns
        if history[symbol].count() >= WARMUP_SESSIONS
    }
    ranked = sorted(
        ((symbol, score) for symbol, score in scores.items() if score is not None and score > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    selected = _deduplicate(history, ranked, amounts) if benchmark_risk_on else []
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=_normalize_weights(history, selected, equal_weight=False),
        rationale={
            "market_state": market_state,
            **market,
            "selected": [symbol for symbol, _ in selected],
            "scores": {symbol: round(score, 6) for symbol, score in ranked[:MAX_RAW_CANDIDATES]},
        },
    )


def relative_momentum_top_n(
    total_return: pd.DataFrame, signal_date: date, amounts: pd.DataFrame | None = None
) -> StrategyDecision:
    history = _history(total_return, signal_date)
    market_state, market = _market_state(history)
    ranked: list[tuple[str, float]] = []
    diagnostics = {}
    for symbol in history.columns:
        values = [_momentum(history[symbol], period) for period in [21, 63, 126, 252]]
        complete_values = [value for value in values if value is not None]
        if len(complete_values) != 4 or complete_values[2] <= 0:
            continue
        score = sum(
            weight * value for weight, value in zip([0.15, 0.25, 0.35, 0.25], complete_values, strict=True)
        )
        ranked.append((symbol, score))
        diagnostics[symbol] = [round(value, 6) for value in complete_values]
    ranked.sort(key=lambda item: item[1], reverse=True)
    selected = _deduplicate(history, ranked, amounts)
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=_normalize_weights(history, selected, equal_weight=False),
        rationale={
            "market_state": market_state,
            **market,
            "selected": [symbol for symbol, _ in selected],
            "momentum_1_3_6_12m": {symbol: diagnostics[symbol] for symbol, _ in ranked[:MAX_RAW_CANDIDATES]},
        },
    )


def moving_average_equal_weight(
    total_return: pd.DataFrame, signal_date: date, amounts: pd.DataFrame | None = None
) -> StrategyDecision:
    history = _history(total_return, signal_date)
    market_state, market = _market_state(history)
    ranked = []
    diagnostics = {}
    for symbol in history.columns:
        clean = history[symbol].dropna()
        if len(clean) < WARMUP_SESSIONS:
            continue
        current = float(clean.iloc[-1])
        average = float(clean.tail(200).mean())
        momentum = _momentum(clean, 126)
        if current <= average or momentum is None:
            continue
        strength = current / average - 1 + momentum
        ranked.append((symbol, strength))
        diagnostics[symbol] = {
            "close": round(current, 6),
            "sma_200": round(average, 6),
            "momentum_6m": round(momentum, 6),
        }
    ranked.sort(key=lambda item: item[1], reverse=True)
    selected = _deduplicate(history, ranked, amounts)
    return StrategyDecision(
        signal_date=signal_date,
        tradable_on=next_session(signal_date),
        target_weights=_normalize_weights(history, selected, equal_weight=True),
        rationale={
            "market_state": market_state,
            **market,
            "selected": [symbol for symbol, _ in selected],
            "assets": {symbol: diagnostics[symbol] for symbol, _ in ranked[:MAX_RAW_CANDIDATES]},
        },
    )


STRATEGY_FUNCTIONS = {
    "equity-bond-trend": equity_bond_trend,
    "relative-momentum-top-n": relative_momentum_top_n,
    "moving-average-equal-weight": moving_average_equal_weight,
}


def evaluate(
    slug: str,
    total_return: pd.DataFrame,
    signal_date: date,
    amounts: pd.DataFrame | None = None,
) -> StrategyDecision:
    try:
        strategy = STRATEGY_FUNCTIONS[slug]
    except KeyError as exc:
        raise ValueError(f"未知策略: {slug}") from exc
    return strategy(total_return, signal_date, amounts)
