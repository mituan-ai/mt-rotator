from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.market.calendar import next_session
from apps.market.models import CorporateAction, MarketBar
from apps.market.services import current_corporate_actions_for_date, current_data_status
from apps.strategies.execution import ExecutionItem, rebalance
from apps.strategies.models import Signal, StrategyVersion

from .models import (
    Fill,
    HoldingSnapshot,
    LedgerEntry,
    NavSnapshot,
    Order,
    PaperAccount,
    PaperRebalance,
    Position,
)


@transaction.atomic
def activate_account(*, user, strategy: StrategyVersion) -> PaperAccount:
    user = user.__class__.objects.select_for_update().get(pk=user.pk)
    if PaperAccount.objects.filter(
        user=user, strategy_version=strategy, status=PaperAccount.Status.ACTIVE
    ).exists():
        raise ValueError("该策略已经有运行中的模拟账户")
    generation = (
        PaperAccount.objects.filter(user=user, strategy_version=strategy).aggregate(value=Max("generation"))[
            "value"
        ]
        or 0
    ) + 1
    account = PaperAccount.objects.create(user=user, strategy_version=strategy, generation=generation)
    LedgerEntry.objects.create(
        account=account,
        kind=LedgerEntry.Kind.DEPOSIT,
        amount=account.initial_capital,
        occurred_on=timezone.localdate(),
        event_key=f"account:{account.id}:deposit",
    )
    latest_signal = strategy.signals.first()
    status = current_data_status()
    if latest_signal and status["ready"]:
        PaperRebalance.objects.create(
            account=account,
            signal=None,
            eligible_on=next_session(status["expected_session"]),
            target_weights=latest_signal.target_weights,
            source="activation",
        )
    return account


@transaction.atomic
def restart_account(account: PaperAccount) -> PaperAccount:
    account = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if account.status != PaperAccount.Status.ACTIVE:
        raise ValueError("只有运行中的账户可以重启")
    account.status = PaperAccount.Status.ARCHIVED
    account.archived_at = timezone.now()
    account.save(update_fields=["status", "archived_at"])
    return activate_account(user=account.user, strategy=account.strategy_version)


def enqueue_signal_for_accounts(signal: Signal) -> int:
    count = 0
    for account in PaperAccount.objects.filter(
        strategy_version=signal.strategy_version,
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


def _bars_for_date(trade_date: date) -> dict[str, dict[str, Decimal]]:
    rows = (
        MarketBar.objects.filter(
            batch__finished_at__isnull=False,
            adjustment=MarketBar.Adjustment.RAW,
            trade_date=trade_date,
        )
        .order_by("instrument_id", "created_at", "id")
        .values("instrument_id", "open", "high", "low", "close", "volume")
    )
    latest = {row["instrument_id"]: row for row in rows}
    return {
        row["instrument_id"]: {
            "open": Decimal(row["open"]),
            "high": Decimal(row["high"]),
            "low": Decimal(row["low"]),
            "close": Decimal(row["close"]),
            "volume": Decimal(row["volume"]),
        }
        for row in latest.values()
        if Decimal(row["volume"]) > 0
    }


def _record_execution(
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
        status=item.status,
        rejection_reason=item.reason,
        idempotency_key=key,
    )
    if item.status != "filled" or item.price is None:
        return
    Fill.objects.create(order=order, price=item.price, fee=item.fee, filled_on=trade_date, estimated=True)
    gross = (item.price * item.shares).quantize(Decimal("0.01"))
    LedgerEntry.objects.create(
        account=account,
        kind=LedgerEntry.Kind.BUY if item.side == "buy" else LedgerEntry.Kind.SELL,
        instrument_id=item.symbol,
        amount=-gross if item.side == "buy" else gross,
        quantity=item.shares if item.side == "buy" else -item.shares,
        occurred_on=trade_date,
        event_key=f"order:{order.id}:principal",
        detail={"estimated": True, "price": str(item.price)},
    )
    LedgerEntry.objects.create(
        account=account,
        kind=LedgerEntry.Kind.FEE,
        instrument_id=item.symbol,
        amount=-item.fee,
        occurred_on=trade_date,
        event_key=f"order:{order.id}:fee",
    )


def _apply_actions(account: PaperAccount, trade_date: date) -> None:
    actions = current_corporate_actions_for_date(trade_date)
    for action in actions:
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
                    occurred_on=trade_date,
                    event_key=event_key,
                )
        elif action.kind == CorporateAction.Kind.SPLIT and position and position.shares:
            previous_shares = position.shares
            position.shares = int(Decimal(previous_shares) * action.value)
            if action.value > 0:
                position.average_cost = (position.average_cost / action.value).quantize(Decimal("0.000001"))
            position.save(update_fields=["shares", "average_cost", "updated_at"])
            LedgerEntry.objects.create(
                account=account,
                kind=LedgerEntry.Kind.SPLIT,
                instrument=action.instrument,
                quantity=position.shares - previous_shares,
                occurred_on=trade_date,
                event_key=event_key,
                detail={"factor": str(action.value)},
            )
    account.save(update_fields=["cash"])


@transaction.atomic
def apply_actions_for_date(account: PaperAccount, trade_date: date) -> None:
    locked = PaperAccount.objects.select_for_update().get(pk=account.pk)
    if locked.status == PaperAccount.Status.ACTIVE:
        _apply_actions(locked, trade_date)


@transaction.atomic
def process_rebalance(rebalance_item: PaperRebalance, trade_date: date) -> PaperRebalance:
    rebalance_item = (
        PaperRebalance.objects.select_for_update().select_related("account").get(pk=rebalance_item.pk)
    )
    if rebalance_item.status != PaperRebalance.Status.PENDING:
        return rebalance_item
    account = PaperAccount.objects.select_for_update().get(pk=rebalance_item.account_id)
    if account.status != PaperAccount.Status.ACTIVE:
        rebalance_item.status = PaperRebalance.Status.FAILED
        rebalance_item.error = "账户已归档"
        rebalance_item.save(update_fields=["status", "error"])
        return rebalance_item
    _apply_actions(account, trade_date)
    current_positions = {item.instrument_id: item for item in account.positions.all()}
    positions = {symbol: item.shares for symbol, item in current_positions.items() if item.shares > 0}
    result = rebalance(
        cash=Decimal(account.cash),
        positions=positions,
        target_weights=rebalance_item.target_weights,
        bars=_bars_for_date(trade_date),
    )
    for item in result.items:
        _record_execution(account, item, rebalance_item, trade_date)
        if item.status != "filled" or item.price is None:
            continue
        position = current_positions.get(item.symbol)
        old_shares = position.shares if position else 0
        old_average = position.average_cost if position else Decimal("0")
        if item.side == "buy":
            new_shares = old_shares + item.shares
            new_average = (
                Decimal(old_shares) * old_average + Decimal(item.shares) * item.price + item.fee
            ) / Decimal(new_shares)
        else:
            new_shares = max(old_shares - item.shares, 0)
            new_average = old_average if new_shares else Decimal("0")
        if position:
            position.shares = new_shares
            position.average_cost = new_average
        else:
            current_positions[item.symbol] = Position(
                account=account,
                instrument_id=item.symbol,
                shares=new_shares,
                average_cost=new_average,
            )
    account.cash = result.cash
    account.save(update_fields=["cash"])
    for symbol, shares in result.positions.items():
        position = current_positions.get(symbol)
        if position:
            position.shares = shares
            position.save()
        else:
            Position.objects.create(account=account, instrument_id=symbol, shares=shares)
    rebalance_item.status = PaperRebalance.Status.PROCESSED
    rebalance_item.processed_at = timezone.now()
    rebalance_item.save(update_fields=["status", "processed_at"])
    snapshot_account(account, trade_date)
    return rebalance_item


def snapshot_account(account: PaperAccount, trade_date: date) -> NavSnapshot:
    account = PaperAccount.objects.get(pk=account.pk)
    bars = _bars_for_date(trade_date)
    positions = {item.instrument_id: item.shares for item in account.positions.filter(shares__gt=0)}
    value = Decimal(account.cash)
    for symbol, shares in positions.items():
        if symbol in bars:
            value += Decimal(shares) * bars[symbol]["close"]
    HoldingSnapshot.objects.get_or_create(account=account, date=trade_date, defaults={"positions": positions})
    nav, _ = NavSnapshot.objects.get_or_create(
        account=account,
        date=trade_date,
        defaults={"value": value.quantize(Decimal("0.01")), "cash": account.cash},
    )
    return nav
