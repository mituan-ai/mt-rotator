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
            }
        ]
    )


@pytest.mark.django_db
def test_readiness_requires_raw_and_hfq(monkeypatch):
    expected = date(2025, 3, 31)
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    batch = seed_ready_day(expected)
    MarketBar.objects.filter(
        batch=batch,
        instrument_id="510300",
        adjustment=MarketBar.Adjustment.BACK,
    ).delete()

    status = current_data_status()
    assert status["ready"] is False
    item = next(row for row in status["instruments"] if row["symbol"] == "510300")
    assert item["raw_latest_date"] == expected
    assert item["hfq_latest_date"] is None


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

    raw, _ = load_snapshot_frames(snapshot)
    actions = corporate_actions_for_snapshot(snapshot)
    assert Decimal(raw["close"].at[pd.Timestamp(expected), "510300"]) == Decimal("4.000000")
    assert actions[0].value == Decimal("0.10000000")

    revised = create_snapshot(expected)
    revised_raw, _ = load_snapshot_frames(revised)
    revised_actions = corporate_actions_for_snapshot(revised)
    assert revised.digest != snapshot.digest
    assert Decimal(revised_raw["close"].at[pd.Timestamp(expected), "510300"]) == Decimal("4.500000")
    assert revised_actions[0].value == Decimal("0.20000000")
