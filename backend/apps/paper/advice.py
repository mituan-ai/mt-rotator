from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db import transaction

from apps.market.calendar import next_session, sessions_in_range
from apps.market.models import Instrument, MarketBar
from apps.strategies.models import Signal

from .models import AdviceSnapshot, Fill, Order, PaperAccount, Position, PositionLot
from .policy import material_change, resolve_stable_targets, scale_strategy_targets

MIN_CONFIRMATION_SESSIONS = 2


def _prices_on_or_before(symbols: set[str], session_date: date) -> dict[str, Decimal]:
    rows = (
        MarketBar.objects.filter(
            instrument_id__in=symbols,
            adjustment=MarketBar.Adjustment.RAW,
            trade_date__lte=session_date,
            is_current=True,
            batch__finished_at__isnull=False,
        )
        .order_by("instrument_id", "-trade_date")
        .values("instrument_id", "close")
    )
    result: dict[str, Decimal] = {}
    for row in rows:
        result.setdefault(row["instrument_id"], Decimal(row["close"]))
    return result


def _consecutive(previous: AdviceSnapshot | None, session_date: date) -> bool:
    if not previous or previous.session_date >= session_date:
        return False
    return len(sessions_in_range(previous.session_date, session_date)) == MIN_CONFIRMATION_SESSIONS


def _session_age(start: date | None, through: date) -> int:
    if not start or start > through:
        return 0
    return max(len(sessions_in_range(start, through)) - 1, 0)


def _raw_targets(account: PaperAccount, signal: Signal) -> dict[str, Decimal]:
    selected = signal.rationale.get("selected") or list(signal.target_weights)
    return scale_strategy_targets(
        risk_level=account.risk_level,
        target_weights=signal.target_weights,
        selected=selected,
        market_state=signal.rationale.get("market_state", "neutral"),
    )


def _rounded_shares(value: Decimal, price: Decimal, lot_size: int) -> int:
    if value <= 0 or price <= 0:
        return 0
    shares = int((value / price).to_integral_value(rounding=ROUND_DOWN))
    return shares // lot_size * lot_size


@transaction.atomic
def generate_account_advice(account: PaperAccount, signal: Signal, session_date: date) -> AdviceSnapshot:
    account = PaperAccount.objects.select_for_update().get(pk=account.pk)
    existing = AdviceSnapshot.objects.filter(
        account=account,
        strategy_version=signal.strategy_version,
        session_date=session_date,
    ).first()
    if existing:
        return existing
    if account.mode != PaperAccount.Mode.MANUAL or account.status != PaperAccount.Status.ACTIVE:
        raise ValueError("只有运行中的自主账户可以生成建议")
    if account.strategy_version_id != signal.strategy_version_id:
        raise ValueError("信号与账户当前建议策略不一致")

    positions = {
        item.instrument_id: item
        for item in Position.objects.select_for_update().filter(account=account, shares__gt=0)
    }
    pending = list(Order.objects.filter(account=account, status=Order.Status.PENDING).order_by("created_at"))
    pending_buy: dict[str, int] = {}
    pending_sell: dict[str, int] = {}
    for order in pending:
        target = pending_buy if order.side == "buy" else pending_sell
        target[order.instrument_id] = target.get(order.instrument_id, 0) + order.shares

    raw_targets = _raw_targets(account, signal)
    symbols = set(raw_targets) | set(positions) | set(pending_buy) | set(pending_sell)
    prices = _prices_on_or_before(symbols, session_date)
    latest_nav = account.nav_snapshots.filter(date=session_date).first()
    nav = Decimal(latest_nav.value) if latest_nav else Decimal(account.cash)
    if nav <= 0:
        raise ValueError("账户净值无效，不能生成建议")

    previous = (
        AdviceSnapshot.objects.filter(
            account=account,
            strategy_version=signal.strategy_version,
            session_date__lt=session_date,
        )
        .order_by("-session_date")
        .first()
    )
    prior_raw = (
        previous.input_summary.get("raw_targets", {})
        if previous and _consecutive(previous, session_date)
        else {}
    )
    current_weights: dict[str, Decimal] = {}
    holding_ages: dict[str, int] = {}
    cooldown_ages: dict[str, int | None] = {}
    for symbol in symbols:
        position = positions.get(symbol)
        held = position.shares if position else 0
        effective = max(held + pending_buy.get(symbol, 0) - pending_sell.get(symbol, 0), 0)
        price = prices.get(symbol)
        current_weight = Decimal(effective) * price / nav if price else Decimal("0")
        current_weights[symbol] = current_weight
        latest_lot = (
            PositionLot.objects.filter(account=account, instrument_id=symbol, remaining_shares__gt=0)
            .order_by("-acquired_on")
            .first()
        )
        holding_ages[symbol] = _session_age(latest_lot.acquired_on if latest_lot else None, session_date)
        latest_sell = (
            Fill.objects.filter(
                order__account=account,
                order__instrument_id=symbol,
                order__side="sell",
            )
            .order_by("-filled_on")
            .first()
        )
        cooldown_ages[symbol] = (
            _session_age(latest_sell.filled_on, session_date) if not held and latest_sell else None
        )

    resolution = resolve_stable_targets(
        raw_targets=raw_targets,
        current_weights=current_weights,
        prior_raw_targets={symbol: Decimal(str(weight)) for symbol, weight in prior_raw.items()},
        holding_ages=holding_ages,
        cooldown_ages=cooldown_ages,
    )
    stable_targets, states = resolution.targets, resolution.states
    instruments = {item.symbol: item for item in Instrument.objects.filter(symbol__in=symbols)}
    for symbol in symbols:
        if instruments[symbol].data_status != Instrument.DataStatus.READY:
            stable_targets[symbol] = current_weights.get(symbol, Decimal("0"))
            states[symbol] = "data_stale"

    recommendations = []
    next_trade_date = next_session(session_date)
    available_cash = Decimal(account.cash) - sum(
        (order.reserved_cash for order in pending if order.side == "buy"), Decimal("0")
    )
    ordered_symbols = [*raw_targets, *sorted(symbols - set(raw_targets))]
    for symbol in ordered_symbols:
        instrument = instruments[symbol]
        price = prices.get(symbol)
        position = positions.get(symbol)
        held = position.shares if position else 0
        effective = max(held + pending_buy.get(symbol, 0) - pending_sell.get(symbol, 0), 0)
        target_weight = stable_targets.get(symbol, Decimal("0"))
        desired = _rounded_shares(nav * target_weight, price, instrument.lot_size) if price else effective
        gap = desired - effective
        current_weight = Decimal(effective) * price / nav if price else Decimal("0")
        trade_value = abs(Decimal(gap) * price) if price else Decimal("0")
        state = states[symbol]
        action = state
        quantity = abs(gap)
        actionable = state in {"buy", "sell"}
        reason = "策略目标与当前持仓一致"

        if not price:
            action, quantity, actionable, reason = "hold", 0, False, "缺少有效估值价格"
        elif pending_buy.get(symbol) or pending_sell.get(symbol):
            action, quantity, actionable, reason = "hold", 0, False, "已有待处理委托"
        elif state == "watch":
            action, quantity, actionable, reason = "watch", 0, False, "候选首次出现，等待连续确认"
        elif state == "cooldown":
            action, quantity, actionable, reason = "cooldown", 0, False, "卖出后仍在冷却期"
        elif state == "data_stale":
            action, quantity, actionable, reason = "hold", 0, False, "该ETF数据陈旧，不生成买卖建议"
        elif not material_change(
            target_weight=target_weight,
            current_weight=current_weight,
            trade_value=trade_value,
        ):
            action, quantity, actionable, reason = "hold", 0, False, "调整幅度不足，避免低价值换手"
        elif gap > 0:
            affordable = _rounded_shares(max(available_cash, Decimal("0")), price, instrument.lot_size)
            quantity = min(gap, affordable)
            if quantity <= 0:
                action, actionable, reason = "hold", False, "可用现金不足"
            else:
                action, actionable, reason = "buy", True, "连续信号确认且低于目标仓位"
                available_cash -= Decimal(quantity) * price
        elif gap < 0:
            sellable = sum(
                PositionLot.objects.filter(
                    account=account,
                    instrument_id=symbol,
                    remaining_shares__gt=0,
                    available_on__lte=next_trade_date,
                ).values_list("remaining_shares", flat=True)
            )
            quantity = min(-gap, sellable)
            if quantity <= 0:
                action, actionable, reason = "waiting", False, "持仓尚未达到可卖日期"
            else:
                action = "reduce" if target_weight > 0 else "sell"
                actionable, reason = True, "连续退出信号确认且高于目标仓位"

        recommendations.append(
            {
                "symbol": symbol,
                "name": instrument.name,
                "action": action,
                "quantity": quantity,
                "actionable": actionable,
                "current_shares": held,
                "effective_shares": effective,
                "current_weight": str(current_weight.quantize(Decimal("0.000001"))),
                "target_weight": str(target_weight.quantize(Decimal("0.000001"))),
                "estimated_price": str(price) if price else None,
                "reason": reason,
                "valid_on": next_trade_date.isoformat(),
            }
        )

    return AdviceSnapshot.objects.create(
        account=account,
        strategy_version=signal.strategy_version,
        signal=signal,
        session_date=session_date,
        expires_on=next_trade_date,
        risk_level=account.risk_level,
        target_weights={symbol: str(weight) for symbol, weight in stable_targets.items() if weight > 0},
        recommendations=recommendations,
        input_summary={
            "cash": str(account.cash),
            "nav": str(nav),
            "raw_targets": {symbol: str(weight) for symbol, weight in raw_targets.items()},
            "positions": {symbol: item.shares for symbol, item in positions.items()},
            "pending_order_ids": [str(order.id) for order in pending],
            "market_state": signal.rationale.get("market_state", "neutral"),
        },
    )
