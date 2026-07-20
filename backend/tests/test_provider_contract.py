from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.market.providers import SinaProvider


@pytest.mark.live
def test_free_sina_market_data_contracts_are_available():
    end = date.today()
    start = end - timedelta(days=30)
    provider = SinaProvider()
    catalog = provider.fetch_catalog()
    assert len(catalog) > 500
    assert any(item.symbol == "510300" for item in catalog)
    bars = provider.fetch_bars("510300", start, end)
    assert not bars.empty
    assert set(bars.columns) == {"trade_date", "open", "high", "low", "close", "volume", "amount"}
    assert isinstance(provider.fetch_dividends("510300"), list)
