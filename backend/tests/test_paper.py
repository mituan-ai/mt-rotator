from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.market.models import CorporateAction, MarketBar
from apps.market.services import seed_instruments
from apps.paper.models import (
    Fill,
    HoldingSnapshot,
    LedgerEntry,
    Order,
    PaperAccount,
    PaperRebalance,
    Position,
)
from apps.paper.services import apply_actions_for_date, process_rebalance
from apps.strategies.services import seed_strategy_catalog
from tests.factories import completed_batch


@pytest.mark.django_db
def test_daily_corporate_actions_are_idempotent_and_adjust_cost(user):
    instruments = {item.symbol: item for item in seed_instruments()}
    strategy = seed_strategy_catalog()[0]
    account = PaperAccount.objects.create(user=user, strategy_version=strategy, cash=Decimal("1000"))
    position = Position.objects.create(
        account=account,
        instrument=instruments["510300"],
        shares=1000,
        average_cost=Decimal("4.000000"),
    )
    record_date = date(2025, 3, 20)
    payment_date = date(2025, 3, 28)
    HoldingSnapshot.objects.create(account=account, date=record_date, positions={"510300": 1000})
    batch = completed_batch(expected=payment_date)
    CorporateAction.objects.create(
        instrument=instruments["510300"],
        batch=batch,
        kind=CorporateAction.Kind.CASH_DIVIDEND,
        record_date=record_date,
        effective_date=date(2025, 3, 21),
        payment_date=payment_date,
        value=Decimal("0.10000000"),
    )
    split_date = date(2025, 3, 31)
    CorporateAction.objects.create(
        instrument=instruments["510300"],
        batch=batch,
        kind=CorporateAction.Kind.SPLIT,
        effective_date=split_date,
        value=Decimal("2.00000000"),
    )

    apply_actions_for_date(account, payment_date)
    apply_actions_for_date(account, payment_date)
    account.refresh_from_db()
    assert account.cash == Decimal("1100.00")
    assert LedgerEntry.objects.filter(account=account, kind=LedgerEntry.Kind.DIVIDEND).count() == 1

    apply_actions_for_date(account, split_date)
    apply_actions_for_date(account, split_date)
    position.refresh_from_db()
    assert position.shares == 2000
    assert position.average_cost == Decimal("2.000000")
    assert LedgerEntry.objects.filter(account=account, kind=LedgerEntry.Kind.SPLIT).count() == 1


@pytest.mark.django_db
def test_rebalance_task_is_idempotent(user):
    instruments = {item.symbol: item for item in seed_instruments()}
    strategy = seed_strategy_catalog()[0]
    trade_date = date(2025, 3, 31)
    batch = completed_batch(expected=trade_date)
    MarketBar.objects.create(
        instrument=instruments["510300"],
        batch=batch,
        trade_date=trade_date,
        adjustment=MarketBar.Adjustment.RAW,
        open=Decimal("4.000000"),
        high=Decimal("4.100000"),
        low=Decimal("3.900000"),
        close=Decimal("4.050000"),
        volume=Decimal("1000000"),
    )
    account = PaperAccount.objects.create(user=user, strategy_version=strategy)
    rebalance_item = PaperRebalance.objects.create(
        account=account,
        eligible_on=trade_date,
        target_weights={"510300": 0.5},
        source="activation",
    )

    process_rebalance(rebalance_item, trade_date)
    process_rebalance(rebalance_item, trade_date)

    assert Order.objects.filter(account=account).count() == 1
    assert Fill.objects.filter(order__account=account).count() == 1
    assert LedgerEntry.objects.filter(account=account).count() == 2
