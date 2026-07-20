from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from apps.market.calendar import latest_expected_session
from apps.market.models import MarketDataBatch
from apps.market.providers import CatalogRecord, ProviderError, SinaProvider, normalize_bars
from apps.market.services import _previous_session


def test_latest_expected_session_does_not_advance_before_market_close(monkeypatch):
    zone = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(
        "apps.market.calendar.timezone.localtime",
        lambda: datetime(2025, 4, 1, 14, 59, tzinfo=zone),
    )
    assert latest_expected_session() == date(2025, 3, 31)

    monkeypatch.setattr(
        "apps.market.calendar.timezone.localtime",
        lambda: datetime(2025, 4, 1, 15, 0, tzinfo=zone),
    )
    assert latest_expected_session() == date(2025, 4, 1)


def test_pre_calendar_corporate_action_uses_previous_business_day():
    assert _previous_session(date(2006, 5, 19)) == date(2006, 5, 18)


def test_normalize_bars_rejects_duplicate_dates_and_invalid_ohlc():
    frame = pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-02"],
            "开盘": [1, 1],
            "最高": [2, 2],
            "最低": [0.5, 0.5],
            "收盘": [1.5, 1.5],
            "成交量": [100, 100],
            "成交额": [1000, 1000],
        }
    )
    with pytest.raises(ProviderError, match="重复日期"):
        normalize_bars(frame)
    frame.loc[1, "日期"] = "2025-01-03"
    frame.loc[1, "最高"] = 0.8
    with pytest.raises(ProviderError, match="OHLC"):
        normalize_bars(frame)


def test_sina_provider_normalizes_catalog_history_and_dividends(monkeypatch):
    class FakeAkshare:
        def fund_etf_category_sina(self, *, symbol):
            assert symbol == "ETF基金"
            return pd.DataFrame(
                [
                    {
                        "代码": "sh510300",
                        "名称": "沪深300ETF",
                        "最新价": 4,
                        "今开": 3.9,
                        "最高": 4.1,
                        "最低": 3.8,
                        "成交量": 100,
                        "成交额": 2000,
                    }
                ]
            )

        def fund_etf_hist_sina(self, *, symbol):
            assert symbol == "sh510300"
            return pd.DataFrame(
                [
                    {
                        "date": "2025-01-02",
                        "open": 3.9,
                        "high": 4.1,
                        "low": 3.8,
                        "close": 4,
                        "volume": 100,
                        "amount": 2000,
                    }
                ]
            )

        def fund_etf_dividend_sina(self, *, symbol):
            return pd.DataFrame(
                [{"日期": "2024-01-18", "累计分红": 0.1}, {"日期": "2025-06-18", "累计分红": 0.18}]
            )

    monkeypatch.setattr("apps.market.providers._akshare", lambda: FakeAkshare())
    provider = SinaProvider()
    catalog = provider.fetch_catalog()
    assert catalog[0].symbol == "510300"
    bars = provider.fetch_bars("510300", date(2025, 1, 1), date(2025, 1, 3))
    assert list(bars.columns) == ["trade_date", "open", "high", "low", "close", "volume", "amount"]
    dividends = provider.fetch_dividends("510300")
    assert [item.value for item in dividends] == [Decimal("0.1"), Decimal("0.08")]


@pytest.mark.django_db
def test_incremental_sina_import_is_revision_safe(monkeypatch):
    from apps.market.services import import_market_data

    expected = date(2025, 3, 31)
    history = pd.DataFrame(
        [
            {
                "trade_date": expected,
                "open": 4,
                "high": 4.1,
                "low": 3.9,
                "close": 4,
                "volume": 1_000_000,
                "amount": 20_000_000,
            }
        ]
    )

    class FakeProvider:
        name = "sina-akshare"

        def fetch_catalog(self):
            return [
                CatalogRecord(
                    "510300",
                    "沪深300ETF",
                    "XSHG",
                    {
                        key: Decimal(str(value))
                        for key, value in history.iloc[0].items()
                        if key != "trade_date"
                    },
                )
            ]

        def fetch_bars(self, symbol, start, end):
            return history.copy()

        def fetch_dividends(self, symbol):
            return []

    monkeypatch.setattr("apps.market.services.SinaProvider", FakeProvider)
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    first = import_market_data()
    second = import_market_data()
    assert first.status == MarketDataBatch.Status.HEALTHY
    assert second.status == MarketDataBatch.Status.HEALTHY
    assert second.metadata["revision_count"] == 0
