from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.market.providers import EastmoneyProvider, SinaValidator


@pytest.mark.live
def test_free_market_data_contracts_are_available():
    end = date.today()
    start = end - timedelta(days=30)
    primary = EastmoneyProvider()
    bars = primary.fetch_bars("510300", start, end, "raw")
    assert not bars.empty
    assert set(bars.columns) == {"trade_date", "open", "high", "low", "close", "volume"}
    assert "510300" in primary.fetch_instrument_names()

    validator = SinaValidator()
    assert not validator.fetch_bars("510300").empty
    dividends = validator.fetch_dividends("510300")
    assert set(dividends.columns) == {"date", "cumulative"}
