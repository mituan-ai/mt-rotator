from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

REQUIRED_BAR_COLUMNS = {"trade_date", "open", "high", "low", "close", "volume"}
BAR_ALIASES = {
    "日期": "trade_date",
    "date": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogRecord:
    symbol: str
    name: str
    exchange: str
    bar: dict[str, Decimal] | None


@dataclass(frozen=True)
class CorporateActionRecord:
    symbol: str
    kind: str
    record_date: date | None
    effective_date: date
    payment_date: date | None
    value: Decimal
    detail: dict


def _akshare():
    import akshare as ak

    return ak


def _number(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in {"", "-", "--", "None", "nan"}:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.rename(columns=BAR_ALIASES).copy()
    missing = REQUIRED_BAR_COLUMNS - set(result.columns)
    if missing:
        raise ProviderError(f"行情字段缺失: {sorted(missing)}")
    if "amount" not in result:
        result["amount"] = 0
    result = result[["trade_date", "open", "high", "low", "close", "volume", "amount"]]
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result["trade_date"].duplicated().any():
        raise ProviderError("行情包含重复日期")
    prices = result[["open", "high", "low", "close"]]
    if (prices <= 0).any().any() or (result[["volume", "amount"]] < 0).any().any():
        raise ProviderError("行情包含非正价格或负成交量/成交额")
    invalid_ohlc = (result["high"] < prices.max(axis=1)) | (result["low"] > prices.min(axis=1))
    if invalid_ohlc.any():
        raise ProviderError("OHLC关系无效")
    return result.sort_values("trade_date").reset_index(drop=True)


def _symbol_parts(value: object) -> tuple[str, str] | None:
    raw = str(value).strip().lower()
    symbol = raw[-6:]
    if not symbol.isdigit():
        return None
    if raw.startswith("sh") or symbol.startswith("5"):
        return symbol, "XSHG"
    if raw.startswith("sz") or symbol.startswith("1"):
        return symbol, "XSHE"
    return None


class SinaProvider:
    name = "sina-akshare"
    request_interval_seconds = 0.2

    def fetch_catalog(self) -> list[CatalogRecord]:
        try:
            frame = _akshare().fund_etf_category_sina(symbol="ETF基金")
        except Exception as exc:
            raise ProviderError(f"ETF目录下载失败: {exc}") from exc
        required = {"代码", "名称", "最新价", "今开", "最高", "最低", "成交量", "成交额"}
        if frame is None or frame.empty or not required.issubset(frame.columns):
            raise ProviderError("ETF目录字段无效")

        records: list[CatalogRecord] = []
        for row in frame.to_dict("records"):
            parts = _symbol_parts(row.get("代码"))
            if not parts:
                continue
            symbol, exchange = parts
            values = {
                "open": _number(row.get("今开")),
                "high": _number(row.get("最高")),
                "low": _number(row.get("最低")),
                "close": _number(row.get("最新价")),
                "volume": _number(row.get("成交量")),
                "amount": _number(row.get("成交额")),
            }
            bar = None
            complete_values = {field: value for field, value in values.items() if value is not None}
            if (
                len(complete_values) == len(values)
                and all(complete_values[field] > 0 for field in ["open", "high", "low", "close"])
                and all(complete_values[field] >= 0 for field in ["volume", "amount"])
            ):
                bar = complete_values
            records.append(
                CatalogRecord(
                    symbol=symbol,
                    name=str(row.get("名称", symbol)).strip()[:80],
                    exchange=exchange,
                    bar=bar,
                )
            )
        if not records:
            raise ProviderError("ETF目录没有有效代码")
        return records

    def fetch_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        prefix = "sh" if symbol.startswith("5") else "sz"
        try:
            frame = _akshare().fund_etf_hist_sina(symbol=f"{prefix}{symbol}")
        except Exception as exc:
            raise ProviderError(f"{symbol} 行情下载失败: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError(f"{symbol} 行情为空")
        normalized = normalize_bars(frame)
        result = normalized.loc[
            (normalized["trade_date"] >= start) & (normalized["trade_date"] <= end)
        ].reset_index(drop=True)
        if result.empty:
            raise ProviderError(f"{symbol} 在请求区间内没有行情")
        return result

    def fetch_dividends(self, symbol: str) -> list[CorporateActionRecord]:
        prefix = "sh" if symbol.startswith("5") else "sz"
        try:
            frame = _akshare().fund_etf_dividend_sina(symbol=f"{prefix}{symbol}")
        except Exception as exc:
            raise ProviderError(f"{symbol} 分红下载失败: {exc}") from exc
        if frame is None or frame.empty:
            return []
        if not {"日期", "累计分红"}.issubset(frame.columns):
            raise ProviderError("新浪分红字段无效")
        values = frame.rename(columns={"日期": "date", "累计分红": "cumulative"})[
            ["date", "cumulative"]
        ].copy()
        values["date"] = pd.to_datetime(values["date"], errors="raise").dt.date
        values["cumulative"] = pd.to_numeric(values["cumulative"], errors="raise")
        values = values.sort_values("date").reset_index(drop=True)

        records: list[CorporateActionRecord] = []
        previous = Decimal("0")
        for row in values.to_dict("records"):
            cumulative = Decimal(str(row["cumulative"]))
            delta = cumulative - previous
            previous = cumulative
            if delta <= 0:
                continue
            effective_date = row["date"]
            records.append(
                CorporateActionRecord(
                    symbol=symbol,
                    kind="cash_dividend",
                    record_date=None,
                    effective_date=effective_date,
                    payment_date=effective_date,
                    value=delta,
                    detail={
                        "source": "fund_etf_dividend_sina",
                        "cumulative": str(cumulative),
                        "payment_date_estimated": True,
                    },
                )
            )
        return records
