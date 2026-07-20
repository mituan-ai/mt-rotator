from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.market.calendar import next_session, sessions_in_range
from apps.market.models import DatasetSnapshot, Instrument, MarketBar
from apps.market.services import seed_instruments
from apps.paper.advice import generate_account_advice
from apps.paper.models import AdviceSnapshot, NavSnapshot, Order, PositionLot
from apps.paper.ranking import build_leaderboard
from apps.paper.services import create_user_order, ensure_manual_account, process_user_orders_for_date
from apps.strategies.models import Signal
from apps.strategies.services import seed_strategy_catalog
from tests.factories import completed_batch


def _make_tradable(instrument: Instrument, expected: date) -> None:
    instrument.data_status = Instrument.DataStatus.READY
    instrument.last_bar_date = expected
    instrument.average_amount_20d = Decimal("20000000")
    instrument.trade_eligible = True
    instrument.advice_eligible = True
    instrument.metadata = {**instrument.metadata, "valid_bar_count": 252}
    instrument.save()


def _bar(instrument: Instrument, when: date, close: str = "4.000000") -> MarketBar:
    value = Decimal(close)
    return MarketBar.objects.create(
        instrument=instrument,
        batch=completed_batch(expected=when),
        trade_date=when,
        adjustment=MarketBar.Adjustment.RAW,
        open=value,
        high=value + Decimal("0.1"),
        low=value - Decimal("0.1"),
        close=value,
        volume=Decimal("1000000"),
        amount=Decimal("20000000"),
    )


@pytest.mark.django_db
def test_user_order_is_idempotent_and_creates_t1_lot(user, monkeypatch):
    instrument = {item.symbol: item for item in seed_instruments()}["510300"]
    strategy = seed_strategy_catalog()[0]
    account = ensure_manual_account(user)
    account.strategy_version = strategy
    account.save(update_fields=["strategy_version"])
    submitted_on = date(2025, 3, 28)
    trade_date = next_session(submitted_on)
    _make_tradable(instrument, submitted_on)
    _bar(instrument, submitted_on)
    monkeypatch.setattr("apps.paper.services.timezone.localdate", lambda *args: submitted_on)

    order, created = create_user_order(
        account=account,
        instrument=instrument,
        side="buy",
        shares=1000,
        client_request_id="client-order-0001",
    )
    repeated, repeated_created = create_user_order(
        account=account,
        instrument=instrument,
        side="buy",
        shares=1000,
        client_request_id="client-order-0001",
    )
    assert created is True
    assert repeated_created is False
    assert repeated.id == order.id
    assert order.eligible_on == trade_date

    _bar(instrument, trade_date, "4.100000")
    assert process_user_orders_for_date(trade_date) == 1
    order.refresh_from_db()
    lot = PositionLot.objects.get(source_fill__order=order)
    assert order.status == Order.Status.FILLED
    assert lot.remaining_shares == 1000
    assert lot.available_on == next_session(trade_date)
    assert account.orders.count() == 1


@pytest.mark.django_db
def test_opening_gap_rejects_the_whole_buy_without_negative_cash(user, monkeypatch):
    instrument = {item.symbol: item for item in seed_instruments()}["510300"]
    account = ensure_manual_account(user)
    submitted_on = date(2025, 3, 28)
    trade_date = next_session(submitted_on)
    _make_tradable(instrument, submitted_on)
    _bar(instrument, submitted_on, "4.000000")
    monkeypatch.setattr("apps.paper.services.timezone.localdate", lambda *args: submitted_on)
    order, _ = create_user_order(
        account=account,
        instrument=instrument,
        side="buy",
        shares=24900,
        client_request_id="opening-gap-order",
    )
    _bar(instrument, trade_date, "5.000000")

    assert process_user_orders_for_date(trade_date) == 1
    order.refresh_from_db()
    account.refresh_from_db()
    assert order.status == Order.Status.REJECTED
    assert order.rejection_reason == "insufficient_cash_at_open"
    assert account.cash == Decimal("100000.00")
    assert not PositionLot.objects.filter(account=account).exists()


@pytest.mark.django_db
def test_advice_requires_two_consecutive_sessions_before_buying(user):
    instrument = {item.symbol: item for item in seed_instruments()}["510300"]
    strategy = seed_strategy_catalog()[0]
    account = ensure_manual_account(user)
    account.strategy_version = strategy
    account.save(update_fields=["strategy_version"])
    first_date = date(2025, 3, 28)
    second_date = next_session(first_date)
    _make_tradable(instrument, second_date)
    _bar(instrument, first_date)
    _bar(instrument, second_date, "4.050000")
    for when in [first_date, second_date]:
        NavSnapshot.objects.create(account=account, date=when, value=100000, cash=100000)
    first_snapshot = DatasetSnapshot.objects.create(
        cutoff_date=first_date,
        digest="1" * 64,
        provider="test",
        metadata={"symbols": ["510300"]},
    )
    second_snapshot = DatasetSnapshot.objects.create(
        cutoff_date=second_date,
        digest="2" * 64,
        provider="test",
        metadata={"symbols": ["510300"]},
    )
    rationale = {"selected": ["510300"], "market_state": "strong"}
    first_signal = Signal.objects.create(
        strategy_version=strategy,
        snapshot=first_snapshot,
        signal_date=first_date,
        tradable_on=second_date,
        target_weights={"510300": 1.0},
        rationale=rationale,
    )
    second_signal = Signal.objects.create(
        strategy_version=strategy,
        snapshot=second_snapshot,
        signal_date=second_date,
        tradable_on=next_session(second_date),
        target_weights={"510300": 1.0},
        rationale=rationale,
    )

    first = generate_account_advice(account, first_signal, first_date)
    second = generate_account_advice(account, second_signal, second_date)
    assert first.recommendations[0]["action"] == "watch"
    assert first.recommendations[0]["actionable"] is False
    assert second.recommendations[0]["action"] == "buy"
    assert second.recommendations[0]["actionable"] is True
    assert AdviceSnapshot.objects.count() == 2


@pytest.mark.django_db
def test_leaderboard_is_named_and_uses_common_date(user):
    other = User.objects.create_user(
        email="ranker@example.com",
        password="Correct-Horse-Battery-Staple-2026",
        display_name="参赛者",
    )
    strategy = seed_strategy_catalog()[0]
    first = ensure_manual_account(user)
    second = ensure_manual_account(other)
    first.strategy_version = strategy
    second.strategy_version = strategy
    first.save(update_fields=["strategy_version"])
    second.save(update_fields=["strategy_version"])
    dates = sessions_in_range(date(2025, 1, 2), date(2025, 2, 28))[:25]
    for index, when in enumerate(dates):
        NavSnapshot.objects.create(
            account=first,
            date=when,
            value=Decimal("100000") + index * Decimal("500"),
            cash=100000,
        )
        NavSnapshot.objects.create(
            account=second,
            date=when,
            value=Decimal("100000") + index * Decimal("200"),
            cash=100000,
        )

    board = build_leaderboard("all")
    assert board["as_of_date"] == dates[-1]
    assert board["results"][0]["display_name"] == user.display_name
    assert board["results"][0]["rank"] == 1
    assert "@" not in board["results"][0]["display_name"]
