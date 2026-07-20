from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Min, Sum
from django.utils import timezone

from apps.market.calendar import calendar, next_session, sessions_in_range
from apps.market.models import CorporateAction, Instrument, MarketBar
from apps.market.services import (
    create_snapshot,
    current_corporate_actions_between,
    current_data_status,
    market_session_import_complete,
)
from apps.strategies.execution import ExecutionItem, commission, estimated_price, rebalance
from apps.strategies.models import Signal, StrategyVersion
from apps.strategies.services import generate_all_daily_signals

from .advice import generate_account_advice
from .models import (
    AdviceSnapshot,
    Fill,
    HoldingSnapshot,
    LedgerEntry,
    NavSnapshot,
    Order,
    PaperAccount,
    PaperCycleRun,
    PaperRebalance,
    Position,
    PositionLot,
)


@transaction.atomic
def ensure_manual_account(user) -> PaperAccount:
    user = user.__class__.objects.select_for_update().get(pk=user.pk)
    existing = PaperAccount.objects.filter(
        user=user,
        mode=PaperAccount.Mode.MANUAL,
        status=PaperAccount.Status.ACTIVE,
    ).first()
    if existing:
        return existing
    strategy = StrategyVersion.objects.filter(active=True).order_by("name", "-published_at").first()
    account = PaperAccount.objects.create(
        user=user,
        strategy_version=strategy,
        mode=PaperAccount.Mode.MANUAL,
        risk_level=PaperAccount.RiskLevel.BALANCED,
    )
    LedgerEntry.objects.create(
        account=account,
        kind=LedgerEntry.Kind.DEPOSIT,
        amount=account.initial_capital,
        occurred_on=timezone.localdate(account.created_at),
        event_key=f"manual-initial:{account.id}",
        detail={"source": "manual_account_activation"},
    )
    return account


@transaction.atomic
def activate_account(*, user, strategy: StrategyVersion) -> PaperAccount:
    user = user.__class__.objects.select_for_update().get(pk=user.pk)
    if PaperAccount.objects.filter(
        user=user,
        strategy_version=strategy,
        mode=PaperAccount.Mode.LEGACY_AUTO,
        status=PaperAccount.Status.ACTIVE,
    ).exists():
        raise ValueError("该策略已经有运行中的历史自动账户")
    generation = (
        PaperAccount.objects.filter(user=user, strategy_version=strategy).aggregate(value=Max("generation"))[
            "value"
        ]
        or 0
    ) + 1
    account = PaperAccount.objects.create(
        user=user,
        strategy_version=strategy,
        generation=generation,
        mode=PaperAccount.Mode.LEGACY_AUTO,
    )
    LedgerEntry.objects.create(
        account=account,
        kind=LedgerEntry.Kind.DEPOSIT,
        amount=account.initial_capital,
        occurred_on=timezone.localdate(),
        event_key=f"account:{account.id}:deposit",
    )
    return account


@transaction.atomic
def restart_account(account: PaperAccount) -> PaperAccount:
    account = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if account.mode == PaperAccount.Mode.MANUAL:
        raise ValueError("自主账户不能通过重启清除历史")
    if account.status != PaperAccount.Status.ACTIVE or not account.strategy_version:
        raise ValueError("只有运行中的历史自动账户可以重启")
    account.status = PaperAccount.Status.ARCHIVED
    account.archived_at = timezone.now()
    account.save(update_fields=["status", "archived_at"])
    return activate_account(user=account.user, strategy=account.strategy_version)


@transaction.atomic
def update_account_preferences(
    account: PaperAccount,
    *,
    strategy: StrategyVersion | None = None,
    risk_level: str | None = None,
) -> PaperAccount:
    account = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if account.mode != PaperAccount.Mode.MANUAL or account.status != PaperAccount.Status.ACTIVE:
        raise ValueError("只有运行中的自主账户可以修改建议设置")
    update_fields = []
    if strategy is not None:
        if not strategy.active:
            raise ValueError("只能选择启用中的策略")
        account.strategy_version = strategy
        update_fields.append("strategy_version")
    if risk_level is not None:
        if risk_level not in {choice for choice, _ in PaperAccount.RiskLevel.choices}:
            raise ValueError("风险档位无效")
        account.risk_level = risk_level
        update_fields.append("risk_level")
    if update_fields:
        account.save(update_fields=update_fields)
    return account


def enqueue_signal_for_accounts(signal: Signal) -> int:
    count = 0
    for account in PaperAccount.objects.filter(
        strategy_version=signal.strategy_version,
        mode=PaperAccount.Mode.LEGACY_AUTO,
        status=PaperAccount.Status.ACTIVE,
    ):
        _, created = PaperRebalance.objects.get_or_create(
            account=account,
            signal=signal,
            defaults={
                "eligible_on": signal.tradable_on,
                "target_weights": signal.target_weights,
                "source": "signal",
            },
        )
        count += int(created)
    return count


def _signals_for_session(session_date: date, market_ready: bool) -> list[Signal]:
    if not market_ready:
        return []
    active_ids = set(StrategyVersion.objects.filter(active=True).values_list("id", flat=True))
    signals = list(
        Signal.objects.filter(signal_date=session_date, strategy_version_id__in=active_ids).select_related(
            "strategy_version"
        )
    )
    if {signal.strategy_version_id for signal in signals} != active_ids:
        signals = generate_all_daily_signals(create_snapshot(session_date))
    for signal in signals:
        enqueue_signal_for_accounts(signal)
    return signals


def _active_accounts_for_session(session_date: date) -> list[PaperAccount]:
    accounts = list(
        PaperAccount.objects.filter(
            status=PaperAccount.Status.ACTIVE,
            created_at__date__lte=session_date,
        ).select_related("strategy_version")
    )
    for account in accounts:
        if account.strategy_version and not account.strategy_version.active:
            replacement = (
                StrategyVersion.objects.filter(slug=account.strategy_version.slug, active=True)
                .order_by("-published_at")
                .first()
            )
            if replacement:
                account.strategy_version = replacement
                account.save(update_fields=["strategy_version"])
    return accounts


def _snapshot_accounts_and_advice(
    accounts: list[PaperAccount], signals: list[Signal], session_date: date
) -> None:
    signal_map = {signal.strategy_version_id: signal for signal in signals}
    for account in accounts:
        snapshot_account(account, session_date)
        if account.mode == PaperAccount.Mode.MANUAL and account.strategy_version_id in signal_map:
            generate_account_advice(account, signal_map[account.strategy_version_id], session_date)


def _needs_signal_or_advice_repair(accounts: list[PaperAccount], session_date: date) -> bool:
    active_ids = set(StrategyVersion.objects.filter(active=True).values_list("id", flat=True))
    existing_signal_ids = set(
        Signal.objects.filter(signal_date=session_date, strategy_version_id__in=active_ids).values_list(
            "strategy_version_id", flat=True
        )
    )
    if existing_signal_ids != active_ids:
        return True
    for account in accounts:
        if (
            account.mode == PaperAccount.Mode.MANUAL
            and account.strategy_version_id
            and not AdviceSnapshot.objects.filter(
                account=account,
                strategy_version_id=account.strategy_version_id,
                session_date=session_date,
            ).exists()
        ):
            return True
    return False


def _bars_for_date(trade_date: date) -> dict[str, dict[str, Decimal]]:
    rows = (
        MarketBar.objects.filter(
            batch__finished_at__isnull=False,
            adjustment=MarketBar.Adjustment.RAW,
            trade_date=trade_date,
        )
        .order_by("instrument_id", "created_at", "id")
        .values("instrument_id", "open", "high", "low", "close", "volume", "amount")
    )
    latest = {row["instrument_id"]: row for row in rows}
    return {
        row["instrument_id"]: {
            "open": Decimal(row["open"]),
            "high": Decimal(row["high"]),
            "low": Decimal(row["low"]),
            "close": Decimal(row["close"]),
            "volume": Decimal(row["volume"]),
            "amount": Decimal(row["amount"]),
        }
        for row in latest.values()
        if Decimal(row["volume"]) > 0
    }


def _latest_close(symbol: str) -> Decimal | None:
    value = (
        MarketBar.objects.filter(
            instrument_id=symbol,
            adjustment=MarketBar.Adjustment.RAW,
            is_current=True,
            batch__finished_at__isnull=False,
        )
        .order_by("-trade_date")
        .values_list("close", flat=True)
        .first()
    )
    return Decimal(value) if value is not None else None


def _estimated_order_value(side: str, shares: int, close: Decimal) -> Decimal:
    price = close * (Decimal("1.0005") if side == "buy" else Decimal("0.9995"))
    gross = (price * shares).quantize(Decimal("0.01"))
    return gross + commission(gross) if side == "buy" else gross - commission(gross)


@transaction.atomic
def create_user_order(
    *,
    account: PaperAccount,
    instrument: Instrument,
    side: str,
    shares: int,
    client_request_id: str,
) -> tuple[Order, bool]:
    account = PaperAccount.objects.select_for_update().get(pk=account.pk)
    existing = Order.objects.filter(
        account=account,
        client_request_id=client_request_id,
    ).first()
    if existing:
        if existing.instrument_id != instrument.symbol or existing.side != side or existing.shares != shares:
            raise ValueError("同一请求编号不能用于不同委托")
        return existing, False
    if account.mode != PaperAccount.Mode.MANUAL or account.status != PaperAccount.Status.ACTIVE:
        raise ValueError("只有运行中的自主账户可以提交委托")
    if side not in {"buy", "sell"}:
        raise ValueError("委托方向无效")
    if not instrument.enabled or not instrument.catalog_active or not instrument.trade_eligible:
        raise ValueError("该ETF当前不可交易")
    if shares <= 0 or shares % instrument.lot_size:
        raise ValueError(f"委托数量必须是{instrument.lot_size}份的正整数倍")
    close = _latest_close(instrument.symbol)
    if close is None:
        raise ValueError("该ETF缺少有效收盘价")
    eligible_on = next_session(timezone.localdate())
    reserved_cash = Decimal("0")
    if side == "sell":
        sellable = (
            PositionLot.objects.filter(
                account=account,
                instrument=instrument,
                remaining_shares__gt=0,
                available_on__lte=eligible_on,
            ).aggregate(value=Sum("remaining_shares"))["value"]
            or 0
        )
        pending_sell = (
            Order.objects.filter(
                account=account,
                instrument=instrument,
                side="sell",
                status=Order.Status.PENDING,
            ).aggregate(value=Sum("shares"))["value"]
            or 0
        )
        if shares > sellable - pending_sell:
            raise ValueError("可卖份额不足")
    else:
        reserved_cash = _estimated_order_value(side, shares, close)
        pending_reserved = Order.objects.filter(
            account=account,
            side="buy",
            status=Order.Status.PENDING,
        ).aggregate(value=Sum("reserved_cash"))["value"] or Decimal("0")
        pending_sell_orders = Order.objects.filter(
            account=account,
            side="sell",
            status=Order.Status.PENDING,
            eligible_on=eligible_on,
        ).select_related("instrument")
        expected_sell_proceeds = Decimal("0")
        for pending in pending_sell_orders:
            pending_close = _latest_close(pending.instrument_id)
            if pending_close:
                expected_sell_proceeds += _estimated_order_value("sell", pending.shares, pending_close)
        if reserved_cash > Decimal(account.cash) + expected_sell_proceeds - Decimal(pending_reserved):
            raise ValueError("可用现金不足")
    order = Order.objects.create(
        account=account,
        rebalance=None,
        instrument=instrument,
        side=side,
        shares=shares,
        eligible_on=eligible_on,
        expires_on=eligible_on,
        origin=Order.Origin.USER,
        status=Order.Status.PENDING,
        reserved_cash=reserved_cash,
        client_request_id=client_request_id,
        idempotency_key=f"user:{account.id}:{client_request_id}",
    )
    return order, True


@transaction.atomic
def cancel_user_order(order: Order) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.origin != Order.Origin.USER or order.status != Order.Status.PENDING:
        raise ValueError("只有待处理的用户委托可以撤销")
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancelled_at"])
    return order


def _reject_order(order: Order, reason: str, *, expired: bool = False) -> None:
    order.status = Order.Status.EXPIRED if expired else Order.Status.REJECTED
    order.rejection_reason = reason
    order.save(update_fields=["status", "rejection_reason"])


def _record_fill(order: Order, price: Decimal, fee: Decimal, trade_date: date) -> Fill:
    fill = Fill.objects.create(order=order, price=price, fee=fee, filled_on=trade_date, estimated=True)
    gross = (price * order.shares).quantize(Decimal("0.01"))
    LedgerEntry.objects.create(
        account=order.account,
        kind=LedgerEntry.Kind.BUY if order.side == "buy" else LedgerEntry.Kind.SELL,
        instrument=order.instrument,
        amount=-gross if order.side == "buy" else gross,
        quantity=order.shares if order.side == "buy" else -order.shares,
        occurred_on=trade_date,
        event_key=f"order:{order.id}:principal",
        detail={"estimated": True, "price": str(price), "origin": order.origin},
    )
    LedgerEntry.objects.create(
        account=order.account,
        kind=LedgerEntry.Kind.FEE,
        instrument=order.instrument,
        amount=-fee,
        occurred_on=trade_date,
        event_key=f"order:{order.id}:fee",
    )
    return fill


def _sync_position_from_lots(account: PaperAccount, instrument: Instrument) -> Position:
    lots = list(
        PositionLot.objects.filter(
            account=account,
            instrument=instrument,
            remaining_shares__gt=0,
        )
    )
    shares = sum(item.remaining_shares for item in lots)
    cost = sum((Decimal(item.remaining_shares) * item.unit_cost for item in lots), Decimal("0"))
    average = cost / shares if shares else Decimal("0")
    position, _ = Position.objects.get_or_create(account=account, instrument=instrument)
    position.shares = shares
    position.average_cost = average.quantize(Decimal("0.000001"))
    position.save(update_fields=["shares", "average_cost", "updated_at"])
    return position


@transaction.atomic
def _execute_user_order(order_id, trade_date: date, bars: dict[str, dict[str, Decimal]]) -> Order:
    order = Order.objects.select_for_update().select_related("account", "instrument").get(pk=order_id)
    if order.status != Order.Status.PENDING:
        return order
    account = PaperAccount.objects.select_for_update().get(pk=order.account_id)
    if account.status != PaperAccount.Status.ACTIVE or account.mode != PaperAccount.Mode.MANUAL:
        _reject_order(order, "账户不可用")
        return order
    if order.expires_on and trade_date > order.expires_on:
        _reject_order(order, "委托已过有效交易日", expired=True)
        return order
    bar = bars.get(order.instrument_id)
    if not bar:
        _reject_order(order, "eligible_session_missing_bar")
        return order
    price = estimated_price(order.side, bar["open"], bar["high"], bar["low"])
    gross = (price * order.shares).quantize(Decimal("0.01"))
    fee = commission(gross)

    if order.side == "sell":
        lots = list(
            PositionLot.objects.select_for_update()
            .filter(
                account=account,
                instrument=order.instrument,
                remaining_shares__gt=0,
                available_on__lte=trade_date,
            )
            .order_by("available_on", "acquired_on", "created_at")
        )
        if sum(item.remaining_shares for item in lots) < order.shares:
            _reject_order(order, "insufficient_sellable_shares")
            return order
        remaining = order.shares
        for lot in lots:
            consumed = min(lot.remaining_shares, remaining)
            lot.remaining_shares -= consumed
            lot.save(update_fields=["remaining_shares"])
            remaining -= consumed
            if remaining == 0:
                break
        account.cash = (Decimal(account.cash) + gross - fee).quantize(Decimal("0.01"))
    else:
        if gross + fee > Decimal(account.cash):
            _reject_order(order, "insufficient_cash_at_open")
            return order
        account.cash = (Decimal(account.cash) - gross - fee).quantize(Decimal("0.01"))

    order.status = Order.Status.FILLED
    order.rejection_reason = ""
    order.save(update_fields=["status", "rejection_reason"])
    account.save(update_fields=["cash"])
    fill = _record_fill(order, price, fee, trade_date)
    if order.side == "buy":
        available_on = (
            trade_date
            if order.instrument.settlement_cycle == Instrument.SettlementCycle.T0
            else next_session(trade_date)
        )
        PositionLot.objects.create(
            account=account,
            instrument=order.instrument,
            source_fill=fill,
            acquired_on=trade_date,
            available_on=available_on,
            quantity=order.shares,
            remaining_shares=order.shares,
            unit_cost=((gross + fee) / order.shares).quantize(Decimal("0.000001")),
        )
    _sync_position_from_lots(account, order.instrument)
    return order


def process_user_orders_for_date(trade_date: date) -> int:
    Order.objects.filter(
        origin=Order.Origin.USER,
        status=Order.Status.PENDING,
        expires_on__lt=trade_date,
    ).update(status=Order.Status.EXPIRED, rejection_reason="委托已过有效交易日")
    bars = _bars_for_date(trade_date)
    orders = list(
        Order.objects.filter(
            origin=Order.Origin.USER,
            status=Order.Status.PENDING,
            eligible_on=trade_date,
        ).order_by("account_id", "created_at", "id")
    )
    orders.sort(key=lambda item: (str(item.account_id), 0 if item.side == "sell" else 1, item.created_at))
    for order in orders:
        _execute_user_order(order.id, trade_date, bars)
    return len(orders)


def _record_legacy_execution(
    account: PaperAccount, item: ExecutionItem, rebalance_item: PaperRebalance, trade_date: date
) -> None:
    key = f"rebalance:{rebalance_item.id}:{item.symbol}:{item.side}:{item.status}:{item.shares}"
    order = Order.objects.create(
        account=account,
        rebalance=rebalance_item,
        instrument_id=item.symbol,
        side=item.side,
        shares=item.shares,
        eligible_on=trade_date,
        expires_on=trade_date,
        origin=Order.Origin.LEGACY_REBALANCE,
        status=item.status,
        rejection_reason=item.reason,
        idempotency_key=key,
    )
    if item.status != Order.Status.FILLED or item.price is None:
        return
    _record_fill(order, item.price, item.fee, trade_date)


def _apply_actions(account: PaperAccount, after: date, through: date) -> None:
    for action, event_date in current_corporate_actions_between(after, through):
        event_key = (
            f"action:{account.id}:{action.instrument_id}:{action.kind}:{action.effective_date.isoformat()}"
        )
        if LedgerEntry.objects.filter(event_key=event_key).exists():
            continue
        position = Position.objects.filter(account=account, instrument=action.instrument).first()
        if action.kind == CorporateAction.Kind.CASH_DIVIDEND and action.record_date:
            snapshot = HoldingSnapshot.objects.filter(account=account, date=action.record_date).first()
            shares = int((snapshot.positions if snapshot else {}).get(action.instrument_id, 0))
            amount = (Decimal(shares) * action.value).quantize(Decimal("0.01"))
            if amount > 0:
                account.cash += amount
                LedgerEntry.objects.create(
                    account=account,
                    kind=LedgerEntry.Kind.DIVIDEND,
                    instrument=action.instrument,
                    amount=amount,
                    quantity=shares,
                    occurred_on=event_date,
                    event_key=event_key,
                )
        elif action.kind == CorporateAction.Kind.SPLIT and position and position.shares:
            previous_shares = position.shares
            position.shares = int(Decimal(previous_shares) * action.value)
            position.average_cost = (position.average_cost / action.value).quantize(Decimal("0.000001"))
            position.save(update_fields=["shares", "average_cost", "updated_at"])
            for lot in PositionLot.objects.filter(
                account=account,
                instrument=action.instrument,
                remaining_shares__gt=0,
            ):
                lot.quantity = int(Decimal(lot.quantity) * action.value)
                lot.remaining_shares = int(Decimal(lot.remaining_shares) * action.value)
                lot.unit_cost = (lot.unit_cost / action.value).quantize(Decimal("0.000001"))
                lot.save(update_fields=["quantity", "remaining_shares", "unit_cost"])
            LedgerEntry.objects.create(
                account=account,
                kind=LedgerEntry.Kind.SPLIT,
                instrument=action.instrument,
                quantity=position.shares - previous_shares,
                occurred_on=event_date,
                event_key=event_key,
                detail={"factor": str(action.value)},
            )
    account.save(update_fields=["cash"])


@transaction.atomic
def apply_actions_for_date(account: PaperAccount, trade_date: date) -> None:
    locked = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if locked.status == PaperAccount.Status.ACTIVE:
        _apply_actions(locked, trade_date - timedelta(days=1), trade_date)


@transaction.atomic
def apply_actions_between(account: PaperAccount, after: date, through: date) -> None:
    locked = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if locked.status == PaperAccount.Status.ACTIVE:
        _apply_actions(locked, after, through)


@transaction.atomic
def process_rebalance(rebalance_item: PaperRebalance, trade_date: date) -> PaperRebalance:
    rebalance_item = (
        PaperRebalance.objects.select_for_update().select_related("account").get(pk=rebalance_item.pk)
    )
    if rebalance_item.status != PaperRebalance.Status.PENDING:
        return rebalance_item
    account = PaperAccount.objects.select_for_update().get(pk=rebalance_item.account_id)
    if account.status != PaperAccount.Status.ACTIVE or account.mode != PaperAccount.Mode.LEGACY_AUTO:
        rebalance_item.status = PaperRebalance.Status.FAILED
        rebalance_item.error = "历史自动账户已归档"
        rebalance_item.save(update_fields=["status", "error"])
        return rebalance_item
    current_positions = {item.instrument_id: item for item in account.positions.all()}
    positions = {symbol: item.shares for symbol, item in current_positions.items() if item.shares > 0}
    result = rebalance(
        cash=Decimal(account.cash),
        positions=positions,
        target_weights=rebalance_item.target_weights,
        bars=_bars_for_date(trade_date),
    )
    for item in result.items:
        _record_legacy_execution(account, item, rebalance_item, trade_date)
    account.cash = result.cash
    account.save(update_fields=["cash"])
    for symbol, shares in result.positions.items():
        position, _ = Position.objects.get_or_create(account=account, instrument_id=symbol)
        position.shares = shares
        if not shares:
            position.average_cost = Decimal("0")
        position.save(update_fields=["shares", "average_cost", "updated_at"])
    rebalance_item.status = PaperRebalance.Status.PROCESSED
    rebalance_item.processed_at = timezone.now()
    rebalance_item.save(update_fields=["status", "processed_at"])
    snapshot_account(account, trade_date)
    return rebalance_item


def _closing_prices_on_or_before(symbols: set[str], trade_date: date) -> dict[str, Decimal]:
    rows = (
        MarketBar.objects.filter(
            instrument_id__in=symbols,
            adjustment=MarketBar.Adjustment.RAW,
            trade_date__lte=trade_date,
            is_current=True,
            batch__finished_at__isnull=False,
        )
        .order_by("instrument_id", "-trade_date")
        .values("instrument_id", "close")
    )
    prices: dict[str, Decimal] = {}
    for row in rows:
        prices.setdefault(row["instrument_id"], Decimal(row["close"]))
    return prices


def snapshot_account(account: PaperAccount, trade_date: date) -> NavSnapshot:
    account = PaperAccount.objects.get(pk=account.pk)
    positions = {item.instrument_id: item.shares for item in account.positions.filter(shares__gt=0)}
    prices = _closing_prices_on_or_before(set(positions), trade_date)
    missing = set(positions) - set(prices)
    if missing:
        raise ValueError(f"缺少持仓估值价格: {', '.join(sorted(missing))}")
    value = Decimal(account.cash) + sum(
        (Decimal(shares) * prices[symbol] for symbol, shares in positions.items()), Decimal("0")
    )
    HoldingSnapshot.objects.get_or_create(account=account, date=trade_date, defaults={"positions": positions})
    nav, _ = NavSnapshot.objects.get_or_create(
        account=account,
        date=trade_date,
        defaults={"value": value.quantize(Decimal("0.01")), "cash": account.cash},
    )
    return nav


def _session_on_or_after(value: date) -> date:
    return calendar().date_to_session(value, direction="next").date()


def _first_cycle_session(target: date) -> date:
    unresolved = (
        PaperCycleRun.objects.filter(session_date__lte=target)
        .exclude(status=PaperCycleRun.Status.SUCCEEDED)
        .order_by("session_date")
        .first()
    )
    if unresolved:
        return unresolved.session_date
    last_success = (
        PaperCycleRun.objects.filter(status=PaperCycleRun.Status.SUCCEEDED, session_date__lt=target)
        .order_by("-session_date")
        .first()
    )
    if last_success:
        return next_session(last_success.session_date)

    candidates = [target]
    earliest_order = Order.objects.filter(
        origin=Order.Origin.USER,
        status=Order.Status.PENDING,
        eligible_on__lte=target,
    ).aggregate(value=Min("eligible_on"))["value"]
    if earliest_order:
        candidates.append(earliest_order)
    earliest_rebalance = PaperRebalance.objects.filter(
        status=PaperRebalance.Status.PENDING,
        eligible_on__lte=target,
    ).aggregate(value=Min("eligible_on"))["value"]
    if earliest_rebalance:
        candidates.append(earliest_rebalance)
    for account in PaperAccount.objects.filter(status=PaperAccount.Status.ACTIVE):
        latest_nav = account.nav_snapshots.aggregate(value=Max("date"))["value"]
        if latest_nav and latest_nav < target:
            candidates.append(next_session(latest_nav))
        elif not latest_nav:
            candidates.append(_session_on_or_after(timezone.localdate(account.created_at)))
    return min(candidates)


@transaction.atomic
def _claim_cycle(session_date: date, lease_minutes: int = 15) -> PaperCycleRun | None:
    now = timezone.now()
    run, _ = PaperCycleRun.objects.select_for_update().get_or_create(session_date=session_date)
    if run.status == PaperCycleRun.Status.SUCCEEDED:
        return None
    if run.status == PaperCycleRun.Status.RUNNING and run.lease_expires_at and run.lease_expires_at > now:
        return None
    run.status = PaperCycleRun.Status.RUNNING
    run.attempt_count += 1
    run.lease_expires_at = now + timedelta(minutes=lease_minutes)
    run.started_at = now
    run.finished_at = None
    run.error = ""
    run.save(
        update_fields=[
            "status",
            "attempt_count",
            "lease_expires_at",
            "started_at",
            "finished_at",
            "error",
        ]
    )
    return run


def _finish_cycle(run: PaperCycleRun, *, error: str = "") -> bool:
    updated = PaperCycleRun.objects.filter(
        pk=run.pk,
        status=PaperCycleRun.Status.RUNNING,
        attempt_count=run.attempt_count,
    ).update(
        status=PaperCycleRun.Status.FAILED if error else PaperCycleRun.Status.SUCCEEDED,
        error=error,
        finished_at=timezone.now(),
        lease_expires_at=None,
    )
    return updated == 1


def reconcile_paper_through(target_session: date) -> dict:
    status = current_data_status()
    if target_session > status["expected_session"]:
        return {"status": "blocked", "reason": "market_session_not_complete"}
    if not market_session_import_complete(target_session):
        return {"status": "blocked", "reason": "market_data_import_pending"}
    start = _first_cycle_session(target_session)
    previous_success = (
        PaperCycleRun.objects.filter(
            status=PaperCycleRun.Status.SUCCEEDED,
            session_date__lt=start,
        )
        .order_by("-session_date")
        .first()
    )
    previous_date = previous_success.session_date if previous_success else start - timedelta(days=1)
    completed = 0
    for session_date in sessions_in_range(start, target_session):
        run = _claim_cycle(session_date)
        if run is None:
            existing = PaperCycleRun.objects.get(session_date=session_date)
            if existing.status != PaperCycleRun.Status.SUCCEEDED:
                return {"status": "busy", "processed": completed}
            accounts = _active_accounts_for_session(session_date)
            if status["ready"] and _needs_signal_or_advice_repair(accounts, session_date):
                signals = _signals_for_session(session_date, True)
                _snapshot_accounts_and_advice(accounts, signals, session_date)
            previous_date = session_date
            continue
        try:
            signals = _signals_for_session(session_date, status["ready"])
            accounts = _active_accounts_for_session(session_date)
            for account in accounts:
                apply_actions_between(account, previous_date, session_date)
            process_user_orders_for_date(session_date)
            for item in PaperRebalance.objects.filter(
                account__mode=PaperAccount.Mode.LEGACY_AUTO,
                status=PaperRebalance.Status.PENDING,
                eligible_on__lte=session_date,
            ).order_by("eligible_on", "created_at"):
                process_rebalance(item, item.eligible_on)
            _snapshot_accounts_and_advice(accounts, signals, session_date)
        except Exception as exc:
            _finish_cycle(run, error=str(exc))
            raise
        if not _finish_cycle(run):
            return {"status": "busy", "processed": completed}
        previous_date = session_date
        completed += 1
    return {"status": "ok", "processed": completed, "processed_through": target_session.isoformat()}


def paper_cycle_status(target_session: date) -> dict:
    latest = (
        PaperCycleRun.objects.filter(status=PaperCycleRun.Status.SUCCEEDED).order_by("-session_date").first()
    )
    processed_through = latest.session_date if latest else None
    if processed_through and processed_through >= target_session:
        pending = 0
    else:
        start = _first_cycle_session(target_session)
        pending = len(sessions_in_range(start, target_session))
    return {
        "status": "fresh" if pending == 0 else "stale",
        "processed_through": processed_through,
        "pending_sessions": pending,
    }
