from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

REQUIRED_BAR_COLUMNS = {"日期", "开盘", "收盘", "最高", "最低", "成交量"}
DIVIDEND_FUND_TYPES = ["指数型-股票", "指数型-固收", "货币型-普通货币"]
SPLIT_FUND_TYPES = ["指数型-股票", "指数型-固收", "货币型"]


class ProviderError(RuntimeError):
    pass


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


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_BAR_COLUMNS - set(frame.columns)
    if missing:
        raise ProviderError(f"行情字段缺失: {sorted(missing)}")
    result = frame.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
    )[["trade_date", "open", "high", "low", "close", "volume"]].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    for column in ["open", "high", "low", "close", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result["trade_date"].duplicated().any():
        raise ProviderError("行情包含重复日期")
    prices = result[["open", "high", "low", "close"]]
    if (prices <= 0).any().any() or (result["volume"] < 0).any():
        raise ProviderError("行情包含非正价格或负成交量")
    if (
        (result["high"] < prices[["open", "close"]].max(axis=1))
        | (result["low"] > prices[["open", "close"]].min(axis=1))
    ).any():
        raise ProviderError("OHLC关系无效")
    return result.sort_values("trade_date").reset_index(drop=True)


class EastmoneyProvider:
    name = "eastmoney-akshare"

    def fetch_bars(self, symbol: str, start: date, end: date, adjustment: str) -> pd.DataFrame:
        adjust = "" if adjustment == "raw" else "hfq"
        try:
            frame = _akshare().fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=adjust,
            )
        except Exception as exc:
            raise ProviderError(f"{symbol} 行情下载失败: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError(f"{symbol} 行情为空")
        return normalize_bars(frame)

    def fetch_instrument_names(self) -> dict[str, str]:
        try:
            frame = _akshare().fund_etf_spot_em()
        except Exception as exc:
            raise ProviderError(f"ETF列表下载失败: {exc}") from exc
        if frame is None or frame.empty or not {"代码", "名称"}.issubset(frame.columns):
            raise ProviderError("ETF列表字段无效")
        return {str(row["代码"]).zfill(6): str(row["名称"]) for _, row in frame.iterrows()}

    def fetch_corporate_actions(self, year: int, symbols: set[str]) -> list[CorporateActionRecord]:
        records: list[CorporateActionRecord] = []
        ak = _akshare()
        try:
            dividend_frames = [ak.fund_fh_em(year=str(year), typ=kind) for kind in DIVIDEND_FUND_TYPES]
            split_frames = [ak.fund_cf_em(year=str(year), typ=kind) for kind in SPLIT_FUND_TYPES]
            dividends = pd.concat(dividend_frames, ignore_index=True)
            splits = pd.concat(split_frames, ignore_index=True)
        except Exception as exc:
            raise ProviderError(f"{year}年公司行动下载失败: {exc}") from exc
        if dividends is not None and not dividends.empty:
            for _, row in dividends.iterrows():
                symbol = str(row.get("基金代码", "")).zfill(6)
                if symbol not in symbols:
                    continue
                effective = _date_or_none(row.get("除息日期"))
                if not effective:
                    continue
                records.append(
                    CorporateActionRecord(
                        symbol=symbol,
                        kind="cash_dividend",
                        record_date=_date_or_none(row.get("权益登记日")),
                        effective_date=effective,
                        payment_date=_date_or_none(row.get("分红发放日")),
                        value=Decimal(str(row.get("分红", 0))),
                        detail={"source": "fund_fh_em", "year": year},
                    )
                )
        if splits is not None and not splits.empty:
            for _, row in splits.iterrows():
                symbol = str(row.get("基金代码", "")).zfill(6)
                if symbol not in symbols:
                    continue
                effective = _date_or_none(row.get("拆分折算日"))
                factor = _decimal_from_text(row.get("拆分折算"))
                if effective and factor and factor > 0:
                    records.append(
                        CorporateActionRecord(
                            symbol=symbol,
                            kind="split",
                            record_date=None,
                            effective_date=effective,
                            payment_date=None,
                            value=factor,
                            detail={"source": "fund_cf_em", "type": str(row.get("拆分类型", ""))},
                        )
                    )
        return records


class SinaValidator:
    name = "sina-akshare"

    def fetch_bars(self, symbol: str) -> pd.DataFrame:
        prefix = "sh" if symbol.startswith("5") else "sz"
        try:
            frame = _akshare().fund_etf_hist_sina(symbol=f"{prefix}{symbol}")
        except Exception as exc:
            raise ProviderError(f"新浪校验失败: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError("新浪校验行情为空")
        aliases = {
            "date": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "volume": "成交量",
        }
        return normalize_bars(frame.rename(columns=aliases))

    def fetch_dividends(self, symbol: str) -> pd.DataFrame:
        prefix = "sh" if symbol.startswith("5") else "sz"
        try:
            frame = _akshare().fund_etf_dividend_sina(symbol=f"{prefix}{symbol}")
        except Exception as exc:
            raise ProviderError(f"新浪分红校验失败: {exc}") from exc
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["date", "cumulative"])
        if not {"日期", "累计分红"}.issubset(frame.columns):
            raise ProviderError("新浪分红校验字段无效")
        result = frame.rename(columns={"日期": "date", "累计分红": "cumulative"})[
            ["date", "cumulative"]
        ].copy()
        result["date"] = pd.to_datetime(result["date"], errors="raise").dt.date
        result["cumulative"] = pd.to_numeric(result["cumulative"], errors="raise")
        return result.sort_values("date").reset_index(drop=True)


def _date_or_none(value) -> date | None:
    if value is None or pd.isna(value) or str(value).strip() in {"", "-"}:
        return None
    return pd.to_datetime(value).date()


def _decimal_from_text(value) -> Decimal | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return Decimal(match.group()) if match else None
