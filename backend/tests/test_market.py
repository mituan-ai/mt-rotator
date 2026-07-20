from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from apps.market.providers import (
    DIVIDEND_FUND_TYPES,
    SPLIT_FUND_TYPES,
    EastmoneyProvider,
    ProviderError,
    normalize_bars,
)


def test_normalize_bars_rejects_duplicate_dates_and_invalid_ohlc():
    frame = pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-02"],
            "开盘": [1, 1],
            "最高": [2, 2],
            "最低": [0.5, 0.5],
            "收盘": [1.5, 1.5],
            "成交量": [100, 100],
        }
    )
    with pytest.raises(ProviderError, match="重复日期"):
        normalize_bars(frame)

    frame.loc[1, "日期"] = "2025-01-03"
    frame.loc[1, "最高"] = 0.8
    with pytest.raises(ProviderError, match="OHLC"):
        normalize_bars(frame)


def test_normalize_bars_has_canonical_columns():
    frame = pd.DataFrame(
        {
            "日期": ["2025-01-02"],
            "开盘": [1],
            "最高": [2],
            "最低": [0.5],
            "收盘": [1.5],
            "成交量": [100],
        }
    )
    result = normalize_bars(frame)
    assert list(result.columns) == ["trade_date", "open", "high", "low", "close", "volume"]


def test_corporate_action_provider_limits_queries_to_relevant_fund_types(monkeypatch):
    class FakeAkshare:
        def __init__(self):
            self.dividend_types = []
            self.split_types = []

        def fund_fh_em(self, *, year, typ):
            self.dividend_types.append(typ)
            return pd.DataFrame(
                [
                    {
                        "基金代码": "510300",
                        "权益登记日": "2025-06-17",
                        "除息日期": "2025-06-18",
                        "分红": 0.088,
                        "分红发放日": "2025-06-27",
                    }
                ]
                if typ == "指数型-股票"
                else []
            )

        def fund_cf_em(self, *, year, typ):
            self.split_types.append(typ)
            return pd.DataFrame(
                [
                    {
                        "基金代码": "510300",
                        "拆分折算日": "2025-07-01",
                        "拆分折算": 2,
                        "拆分类型": "份额折算",
                    }
                ]
                if typ == "指数型-股票"
                else []
            )

    fake = FakeAkshare()
    monkeypatch.setattr("apps.market.providers._akshare", lambda: fake)
    records = EastmoneyProvider().fetch_corporate_actions(2025, {"510300"})

    assert fake.dividend_types == DIVIDEND_FUND_TYPES
    assert fake.split_types == SPLIT_FUND_TYPES
    assert [item.kind for item in records] == ["cash_dividend", "split"]


@pytest.mark.django_db
def test_unchanged_incremental_import_remains_healthy(monkeypatch):
    from apps.market.models import MarketDataBatch
    from apps.market.services import INSTRUMENT_SEED, import_market_data

    expected = date(2025, 3, 31)
    frame = pd.DataFrame(
        {
            "trade_date": [expected],
            "open": [4.0],
            "high": [4.1],
            "low": [3.9],
            "close": [4.0],
            "volume": [1_000_000],
        }
    )

    class FakePrimary:
        def fetch_instrument_names(self):
            return {symbol: name for symbol, (name, _) in INSTRUMENT_SEED.items()}

        def fetch_bars(self, symbol, start, end, adjustment):
            return frame.copy()

        def fetch_corporate_actions(self, year, symbols):
            return []

    class FakeValidator:
        def fetch_bars(self, symbol):
            return frame.copy()

        def fetch_dividends(self, symbol):
            return pd.DataFrame(columns=["date", "cumulative"])

    monkeypatch.setattr("apps.market.services.EastmoneyProvider", FakePrimary)
    monkeypatch.setattr("apps.market.services.SinaValidator", FakeValidator)
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    monkeypatch.setattr("apps.market.services.sessions_in_range", lambda start, end: [expected])

    first = import_market_data(start=expected)
    second = import_market_data(start=expected)

    assert first.status == MarketDataBatch.Status.HEALTHY
    assert second.status == MarketDataBatch.Status.HEALTHY
    assert first.row_count == second.row_count == 16
    assert second.metadata["revision_count"] == 0
