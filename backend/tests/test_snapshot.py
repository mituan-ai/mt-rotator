from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from apps.market.models import CorporateAction, MarketBar
from apps.market.services import (
    corporate_actions_for_snapshot,
    create_snapshot,
    current_data_status,
    load_snapshot_frames,
    store_bars,
)
from tests.factories import completed_batch, seed_ready_day


def one_bar(trade_date: date, close: str) -> pd.DataFrame:
    value = Decimal(close)
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "open": value,
                "high": value + Decimal("0.1"),
                "low": value - Decimal("0.1"),
                "close": value,
                "volume": Decimal("1000000"),
                "amount": Decimal("20000000"),
            }
        ]
    )


@pytest.mark.django_db
def test_reference_instrument_failure_blocks_new_snapshots_only(monkeypatch):
    expected = date(2025, 3, 31)
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    seed_ready_day(expected)
    from apps.market.models import Instrument

    reference = Instrument.objects.get(symbol="510300")
    reference.data_status = Instrument.DataStatus.STALE
    reference.trade_eligible = False
    reference.advice_eligible = False
    reference.save()
    MarketBar.objects.filter(
        instrument_id="510300",
    ).delete()

    status = current_data_status()
    assert status["ready"] is False
    item = next(row for row in status["instruments"] if row["symbol"] == "510300")
    assert item["state"] == "stale"


@pytest.mark.django_db
def test_snapshot_keeps_bar_and_action_revisions_immutable(monkeypatch):
    expected = date(2025, 3, 31)
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    first_batch = seed_ready_day(expected, close=Decimal("4.000000"))
    first_action = CorporateAction.objects.create(
        instrument_id="510300",
        batch=first_batch,
        kind=CorporateAction.Kind.CASH_DIVIDEND,
        record_date=date(2025, 3, 20),
        effective_date=date(2025, 3, 21),
        payment_date=date(2025, 3, 28),
        value=Decimal("0.10000000"),
    )
    snapshot = create_snapshot(expected)

    revision_batch = completed_batch(expected=expected)
    store_bars(
        instrument=first_action.instrument,
        batch=revision_batch,
        adjustment=MarketBar.Adjustment.RAW,
        frame=one_bar(expected, "4.500000"),
    )
    first_action.is_current = False
    first_action.save(update_fields=["is_current"])
    CorporateAction.objects.create(
        instrument_id="510300",
        batch=revision_batch,
        kind=CorporateAction.Kind.CASH_DIVIDEND,
        record_date=date(2025, 3, 20),
        effective_date=date(2025, 3, 21),
        payment_date=date(2025, 3, 28),
        value=Decimal("0.20000000"),
    )

    raw, total_return = load_snapshot_frames(snapshot)
    actions = corporate_actions_for_snapshot(snapshot)
    assert Decimal(raw["close"].at[pd.Timestamp(expected), "510300"]) == Decimal("4.000000")
    assert not total_return.empty
    assert actions[0].value == Decimal("0.10000000")

    revised = create_snapshot(expected)
    revised_raw, _ = load_snapshot_frames(revised)
    revised_actions = corporate_actions_for_snapshot(revised)
    assert revised.digest != snapshot.digest
    assert Decimal(revised_raw["close"].at[pd.Timestamp(expected), "510300"]) == Decimal("4.500000")
    assert revised_actions[0].value == Decimal("0.20000000")
