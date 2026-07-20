from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import pandas as pd

from apps.market.models import CorporateAction
from apps.paper.models import PaperAccount
from apps.paper.policy import material_change, resolve_stable_targets, scale_strategy_targets
from apps.strategies.engine import evaluate
from apps.strategies.execution import rebalance


def _bar_map(raw: pd.DataFrame, when) -> dict[str, dict[str, Decimal]]:
    result = {}
    row = raw.loc[when]
    for symbol in raw["open"].columns:
        values = {field: row.at[(field, symbol)] for field in ["open", "high", "low", "close", "volume"]}
        if any(pd.isna(value) for value in values.values()) or float(values["volume"]) <= 0:
            continue
        result[symbol] = {field: Decimal(str(value)) for field, value in values.items()}
    return result


def _apply_corporate_actions(
    *,
    when: date,
    cash: Decimal,
    positions: dict[str, int],
    holdings_history: dict[date, dict[str, int]],
    actions: list[CorporateAction],
) -> tuple[Decimal, dict[str, int], list[dict]]:
    events = []
    for action in actions:
        if (
            action.kind == CorporateAction.Kind.CASH_DIVIDEND
            and action.payment_date == when
            and action.record_date
        ):
            entitled = holdings_history.get(action.record_date, {}).get(action.instrument_id, 0)
            amount = (Decimal(entitled) * action.value).quantize(Decimal("0.01"))
            if amount > 0:
                cash += amount
                events.append(
                    {
                        "date": when.isoformat(),
                        "type": "dividend",
                        "symbol": action.instrument_id,
                        "amount": str(amount),
                    }
                )
        elif action.kind == CorporateAction.Kind.SPLIT and action.effective_date == when:
            held = positions.get(action.instrument_id, 0)
            if held > 0:
                positions[action.instrument_id] = int(Decimal(held) * action.value)
                events.append(
                    {
                        "date": when.isoformat(),
                        "type": "split",
                        "symbol": action.instrument_id,
                        "factor": str(action.value),
                    }
                )
    return cash, positions, events


def run_event_backtest(
    *,
    strategy_slug: str,
    raw: pd.DataFrame,
    hfq: pd.DataFrame,
    start_date: date,
    end_date: date,
    actions: list[CorporateAction] | None = None,
    initial_capital: Decimal = Decimal("100000"),
) -> dict:
    if raw.empty or hfq.empty:
        raise ValueError("数据快照为空")
    dates = [timestamp for timestamp in raw.index if start_date <= timestamp.date() <= end_date]
    if not dates:
        raise ValueError("回测区间没有交易日")

    cash = initial_capital
    positions: dict[str, int] = {}
    pending: dict | None = None
    nav_records: list[dict] = []
    trades: list[dict] = []
    allocations: list[dict] = []
    rejected: list[dict] = []
    corporate_events: list[dict] = []
    holdings: list[dict] = []
    holdings_history: dict[date, dict[str, int]] = {}
    acquired_index: dict[str, int] = {}
    sold_index: dict[str, int] = {}
    previous_raw_targets: dict[str, Decimal] = {}
    actions = actions or []
    total_fees = Decimal("0")
    last_closes: dict[str, Decimal] = {}

    for date_index, timestamp in enumerate(dates):
        current_date = timestamp.date()
        cash, positions, events = _apply_corporate_actions(
            when=current_date,
            cash=cash,
            positions=positions,
            holdings_history=holdings_history,
            actions=actions,
        )
        corporate_events.extend(events)
        bars = _bar_map(raw, timestamp)
        last_closes.update({symbol: bar["close"] for symbol, bar in bars.items()})

        if pending and pending["tradable_on"] == current_date:
            positions_before = dict(positions)
            execution = rebalance(
                cash=cash, positions=positions, target_weights=pending["target_weights"], bars=bars
            )
            cash, positions = execution.cash, execution.positions
            for item in execution.items:
                record = {
                    "signal_date": pending["signal_date"].isoformat(),
                    "date": current_date.isoformat(),
                    "symbol": item.symbol,
                    "side": item.side,
                    "shares": item.shares,
                    "price": str(item.price) if item.price is not None else None,
                    "fee": str(item.fee),
                    "status": item.status,
                    "reason": item.reason,
                    "estimated": True,
                }
                (trades if item.status == "filled" else rejected).append(record)
                total_fees += item.fee
                if (
                    item.status == "filled"
                    and item.side == "buy"
                    and positions_before.get(item.symbol, 0) == 0
                ):
                    acquired_index[item.symbol] = date_index
                if item.status == "filled" and item.side == "sell" and positions.get(item.symbol, 0) == 0:
                    sold_index[item.symbol] = date_index
            pending = None

        close_value = cash
        for symbol, shares in positions.items():
            close = bars.get(symbol, {}).get("close") or last_closes.get(symbol)
            if close is None:
                raise ValueError(f"{current_date} 缺少持仓 {symbol} 的可用估值价格")
            close_value += Decimal(shares) * close
        nav_records.append({"date": current_date.isoformat(), "value": float(close_value)})
        holdings_history[current_date] = dict(positions)
        holdings.append(
            {
                "date": current_date.isoformat(),
                "cash": str(cash.quantize(Decimal("0.01"))),
                "positions": {symbol: shares for symbol, shares in positions.items() if shares > 0},
            }
        )

        try:
            amounts = raw.get("amount", None)
            decision = evaluate(strategy_slug, hfq, current_date, amounts)
        except ValueError:
            continue
        raw_targets = scale_strategy_targets(
            risk_level=PaperAccount.RiskLevel.BALANCED,
            target_weights=decision.target_weights,
            selected=decision.rationale.get("selected") or list(decision.target_weights),
            market_state=decision.rationale.get("market_state", "neutral"),
        )
        current_weights = {
            symbol: Decimal(shares) * last_closes[symbol] / close_value
            for symbol, shares in positions.items()
            if shares > 0 and symbol in last_closes and close_value > 0
        }
        resolution = resolve_stable_targets(
            raw_targets=raw_targets,
            current_weights=current_weights,
            prior_raw_targets=previous_raw_targets,
            holding_ages={
                symbol: date_index - acquired_index.get(symbol, date_index) for symbol in positions
            },
            cooldown_ages={
                symbol: date_index - sold_at
                for symbol, sold_at in sold_index.items()
                if not positions.get(symbol)
            },
        )
        target_weights = {}
        for symbol in set(resolution.targets) | set(current_weights):
            target = resolution.targets.get(symbol, Decimal("0"))
            current = current_weights.get(symbol, Decimal("0"))
            trade_value = abs(target - current) * close_value
            target_weights[symbol] = float(
                target
                if material_change(
                    target_weight=target,
                    current_weight=current,
                    trade_value=trade_value,
                )
                else current
            )
        previous_raw_targets = raw_targets
        pending = {
            "signal_date": current_date,
            "tradable_on": decision.tradable_on,
            "target_weights": target_weights,
        }
        allocations.append(
            {
                "signal_date": current_date.isoformat(),
                "tradable_on": decision.tradable_on.isoformat(),
                "target_weights": target_weights,
                "raw_target_weights": {symbol: str(weight) for symbol, weight in raw_targets.items()},
                "rationale": decision.rationale,
            }
        )

    nav = pd.Series({item["date"]: item["value"] for item in nav_records}, dtype=float)
    metrics = calculate_metrics(nav, initial_capital, total_fees, trades)
    return {
        "assumptions": {
            "initial_capital": str(initial_capital),
            "signal_timing": "daily_close_with_confirmation",
            "fill_timing": "next_session_open",
            "commission_rate": "0.0003",
            "minimum_commission": "5.00",
            "slippage_bps": 5,
            "lot_size": 100,
            "estimated_fills": True,
        },
        "metrics": metrics,
        "nav": nav_records,
        "allocations": allocations,
        "holdings": holdings,
        "trades": trades,
        "rejected_orders": rejected,
        "corporate_actions": corporate_events,
    }


def calculate_metrics(nav: pd.Series, initial_capital: Decimal, fees: Decimal, trades: list[dict]) -> dict:
    if nav.empty:
        raise ValueError("回测没有净值记录")
    returns = nav.pct_change().dropna()
    total_return = float(nav.iloc[-1] / float(initial_capital) - 1)
    years = max(len(nav) / 242, 1 / 242)
    annualized_return = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1
    volatility = float(returns.std(ddof=1) * math.sqrt(242)) if len(returns) > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(242))
        if len(returns) > 1 and returns.std(ddof=1)
        else 0.0
    )
    downside = returns[returns < 0]
    sortino = (
        float(returns.mean() / downside.std(ddof=1) * math.sqrt(242))
        if len(downside) > 1 and downside.std(ddof=1)
        else 0.0
    )
    drawdown = nav / nav.cummax() - 1
    max_drawdown = float(drawdown.min())
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    turnover = sum(float(item["shares"]) * float(item["price"] or 0) for item in trades) / max(
        float(initial_capital), 1
    )
    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "volatility": round(volatility, 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "turnover": round(turnover, 4),
        "fees": str(fees.quantize(Decimal("0.01"))),
        "filled_orders": len(trades),
    }
