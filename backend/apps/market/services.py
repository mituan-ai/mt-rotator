from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .calendar import latest_expected_session, sessions_in_range
from .models import CorporateAction, DatasetSnapshot, Instrument, MarketBar, MarketDataBatch
from .providers import EastmoneyProvider, ProviderError, SinaValidator

INSTRUMENT_SEED = {
    "510300": ("沪深300ETF华泰柏瑞", Instrument.Exchange.SHANGHAI),
    "510500": ("中证500ETF南方", Instrument.Exchange.SHANGHAI),
    "159915": ("创业板ETF易方达", Instrument.Exchange.SHENZHEN),
    "510880": ("红利ETF华泰柏瑞", Instrument.Exchange.SHANGHAI),
    "515300": ("300红利低波ETF嘉实", Instrument.Exchange.SHANGHAI),
    "511160": ("国债ETF东财", Instrument.Exchange.SHANGHAI),
    "511990": ("华宝添益ETF", Instrument.Exchange.SHANGHAI),
    "511010": ("国债ETF国泰", Instrument.Exchange.SHANGHAI),
}
REQUIRED_SYMBOLS = tuple(INSTRUMENT_SEED)


def seed_instruments() -> list[Instrument]:
    result = []
    for symbol, (name, exchange) in INSTRUMENT_SEED.items():
        item, _ = Instrument.objects.update_or_create(
            symbol=symbol,
            defaults={"name": name, "exchange": exchange, "lot_size": 100, "enabled": True},
        )
        result.append(item)
    return result


def _same_bar(current: MarketBar, row) -> bool:
    return all(
        getattr(current, field)
        == Decimal(str(row[field])).quantize(Decimal("0.000001" if field != "volume" else "0.01"))
        for field in ["open", "high", "low", "close", "volume"]
    )


@transaction.atomic
def store_bars(
    *, instrument: Instrument, batch: MarketDataBatch, adjustment: str, frame: pd.DataFrame
) -> int:
    created = 0
    existing = {
        item.trade_date: item
        for item in MarketBar.objects.select_for_update().filter(
            instrument=instrument,
            adjustment=adjustment,
            trade_date__in=list(frame["trade_date"]),
            is_current=True,
        )
    }
    for row in frame.to_dict("records"):
        current = existing.get(row["trade_date"])
        if current and _same_bar(current, row):
            continue
        if current:
            current.is_current = False
            current.save(update_fields=["is_current"])
        MarketBar.objects.create(
            instrument=instrument,
            batch=batch,
            trade_date=row["trade_date"],
            adjustment=adjustment,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
        )
        created += 1
    return created


def _cross_validate(symbol: str, primary: pd.DataFrame, warnings: list[dict], errors: list[dict]) -> None:
    try:
        secondary = SinaValidator().fetch_bars(symbol).tail(20)
    except ProviderError as exc:
        warnings.append({"symbol": symbol, "source": "sina", "message": str(exc)})
        return
    left = (
        primary[["trade_date", "close"]]
        .tail(20)
        .merge(secondary[["trade_date", "close"]], on="trade_date", suffixes=("_primary", "_secondary"))
    )
    if len(left) < 10:
        warnings.append({"symbol": symbol, "source": "sina", "message": "重叠交易日不足10天"})
        return
    difference = ((left["close_primary"] - left["close_secondary"]).abs() / left["close_primary"]).max()
    if float(difference) > 0.001:
        errors.append(
            {"symbol": symbol, "source": "cross_validation", "message": f"收盘价差异 {difference:.4%}"}
        )


def _cross_validate_dividends(*, start: date, warnings: list[dict], errors: list[dict]) -> None:
    validator = SinaValidator()
    for symbol in REQUIRED_SYMBOLS:
        try:
            secondary = validator.fetch_dividends(symbol)
        except ProviderError as exc:
            warnings.append({"symbol": symbol, "source": "sina_dividend", "message": str(exc)})
            continue
        primary = CorporateAction.objects.filter(
            instrument_id=symbol,
            kind=CorporateAction.Kind.CASH_DIVIDEND,
            is_current=True,
            effective_date__gte=start,
        )
        if secondary.empty:
            if primary.exists():
                warnings.append(
                    {"symbol": symbol, "source": "sina_dividend", "message": "新浪无可用分红记录"}
                )
            continue
        latest_date = secondary.iloc[-1]["date"]
        baseline_rows = secondary.loc[secondary["date"] < start, "cumulative"]
        baseline = Decimal(str(baseline_rows.iloc[-1])) if not baseline_rows.empty else Decimal("0")
        secondary_total = Decimal(str(secondary.iloc[-1]["cumulative"])) - baseline
        primary_total = sum(
            (action.value for action in primary.filter(effective_date__lte=latest_date)),
            Decimal("0"),
        )
        if abs(primary_total - secondary_total) > Decimal("0.000001"):
            errors.append(
                {
                    "symbol": symbol,
                    "source": "dividend_cross_validation",
                    "message": f"累计分红不一致，主源 {primary_total}，校验源 {secondary_total}",
                }
            )


def _validate_coverage(
    symbol: str,
    adjustment: str,
    frame: pd.DataFrame,
    expected: date,
    errors: list[dict],
) -> bool:
    valid = True
    actual = set(frame["trade_date"])
    first = min(actual)
    missing = sorted(set(sessions_in_range(first, expected)) - actual)
    if missing:
        valid = False
        errors.append(
            {
                "symbol": symbol,
                "adjustment": adjustment,
                "message": f"缺少 {len(missing)} 个交易日，首个缺口 {missing[0]}",
            }
        )
    if frame.iloc[-1]["trade_date"] != expected:
        valid = False
        errors.append(
            {
                "symbol": symbol,
                "adjustment": adjustment,
                "message": f"最新日期 {frame.iloc[-1]['trade_date']}，预期 {expected}",
            }
        )
    if adjustment == MarketBar.Adjustment.BACK:
        returns = frame["close"].pct_change(fill_method=None).abs()
        abnormal = returns[returns > 0.5]
        if not abnormal.empty:
            valid = False
            errors.append(
                {
                    "symbol": symbol,
                    "adjustment": adjustment,
                    "message": f"发现 {len(abnormal)} 个超过50%的后复权单日变动",
                }
            )
    return valid


def import_market_data(
    *,
    triggered_by: str = "scheduler",
    start: date = date(2010, 1, 1),
    full_refresh: bool = False,
) -> MarketDataBatch:
    instruments = seed_instruments()
    expected = latest_expected_session()
    batch = MarketDataBatch.objects.create(expected_session=expected, triggered_by=triggered_by)
    errors: list[dict] = []
    warnings: list[dict] = []
    row_count = 0
    revision_count = 0
    successful_frames = 0
    provider = EastmoneyProvider()
    bars_backfilled = MarketDataBatch.objects.filter(
        status=MarketDataBatch.Status.HEALTHY,
        metadata__bars_backfilled=True,
    ).exists()
    fetch_start = start if full_refresh or not bars_backfilled else expected - timedelta(days=90)
    bar_sync_ok = True

    try:
        names = provider.fetch_instrument_names()
        for instrument in instruments:
            if instrument.symbol not in names:
                errors.append({"symbol": instrument.symbol, "message": "ETF列表中不存在"})
            elif names[instrument.symbol] != instrument.name:
                instrument.name = names[instrument.symbol]
                instrument.save(update_fields=["name", "updated_at"])
    except ProviderError as exc:
        warnings.append({"source": "instrument_names", "message": str(exc)})

    for instrument in instruments:
        frames: dict[str, pd.DataFrame] = {}
        for adjustment in [MarketBar.Adjustment.RAW, MarketBar.Adjustment.BACK]:
            try:
                frame = provider.fetch_bars(instrument.symbol, fetch_start, expected, adjustment)
                bar_sync_ok = (
                    _validate_coverage(instrument.symbol, adjustment, frame, expected, errors) and bar_sync_ok
                )
                row_count += len(frame)
                revision_count += store_bars(
                    instrument=instrument, batch=batch, adjustment=adjustment, frame=frame
                )
                successful_frames += 1
                frames[adjustment] = frame
            except Exception as exc:
                bar_sync_ok = False
                errors.append({"symbol": instrument.symbol, "adjustment": adjustment, "message": str(exc)})
        raw_frame = frames.get(MarketBar.Adjustment.RAW)
        hfq_frame = frames.get(MarketBar.Adjustment.BACK)
        if raw_frame is not None:
            first_date = raw_frame.iloc[0]["trade_date"]
            if instrument.listed_on != first_date and (fetch_start == start or instrument.listed_on is None):
                instrument.listed_on = first_date
                instrument.save(update_fields=["listed_on", "updated_at"])
            error_count = len(errors)
            _cross_validate(instrument.symbol, raw_frame, warnings, errors)
            bar_sync_ok = bar_sync_ok and len(errors) == error_count
        if (
            raw_frame is not None
            and hfq_frame is not None
            and set(raw_frame["trade_date"]) != set(hfq_frame["trade_date"])
        ):
            bar_sync_ok = False
            errors.append(
                {
                    "symbol": instrument.symbol,
                    "source": "adjustment_alignment",
                    "message": "不复权与后复权交易日期不一致",
                }
            )

    history_backfilled = MarketDataBatch.objects.filter(
        status=MarketDataBatch.Status.HEALTHY,
        metadata__corporate_actions_backfilled=True,
    ).exists()
    actions_checked = MarketDataBatch.objects.filter(
        status=MarketDataBatch.Status.HEALTHY,
        metadata__corporate_actions_checked_on=expected.isoformat(),
    ).exists()
    action_years = (
        []
        if actions_checked and not full_refresh
        else list(range(start.year, expected.year + 1))
        if full_refresh or not history_backfilled
        else [expected.year]
    )
    action_sync_ok = True
    for year in action_years:
        try:
            action_records = provider.fetch_corporate_actions(year, set(REQUIRED_SYMBOLS))
            for record in action_records:
                current = CorporateAction.objects.filter(
                    instrument_id=record.symbol,
                    kind=record.kind,
                    effective_date=record.effective_date,
                    is_current=True,
                ).first()
                if current and all(
                    [
                        current.record_date == record.record_date,
                        current.payment_date == record.payment_date,
                        current.value == record.value,
                        current.source_detail == record.detail,
                    ]
                ):
                    continue
                if current:
                    current.is_current = False
                    current.save(update_fields=["is_current"])
                CorporateAction.objects.create(
                    instrument_id=record.symbol,
                    batch=batch,
                    kind=record.kind,
                    record_date=record.record_date,
                    effective_date=record.effective_date,
                    payment_date=record.payment_date,
                    value=record.value,
                    source_detail=record.detail,
                )
        except ProviderError as exc:
            action_sync_ok = False
            errors.append({"source": "corporate_actions", "year": year, "message": str(exc)})
    if action_sync_ok and action_years:
        _cross_validate_dividends(start=start, warnings=warnings, errors=errors)
    action_history_complete = bool(action_years) and action_years[0] == start.year

    batch.row_count = row_count
    batch.errors = errors
    batch.warnings = warnings
    batch.metadata = {
        "bar_start": fetch_start.isoformat(),
        "bars_backfilled": bars_backfilled or (fetch_start == start and bar_sync_ok),
        "revision_count": revision_count,
        "corporate_action_years": action_years,
        "corporate_actions_backfilled": history_backfilled or (action_sync_ok and action_history_complete),
        "corporate_actions_checked_on": expected.isoformat() if action_sync_ok else None,
        "full_refresh": full_refresh,
    }
    batch.finished_at = timezone.now()
    batch.status = (
        MarketDataBatch.Status.FAILED
        if successful_frames == 0
        else MarketDataBatch.Status.DEGRADED
        if errors
        else MarketDataBatch.Status.HEALTHY
    )
    batch.save(update_fields=["row_count", "errors", "warnings", "metadata", "finished_at", "status"])
    return batch


def current_data_status() -> dict:
    expected = latest_expected_session()
    rows = (
        MarketBar.objects.filter(
            batch__finished_at__isnull=False,
            instrument_id__in=REQUIRED_SYMBOLS,
        )
        .values("instrument_id", "adjustment")
        .annotate(latest=Max("trade_date"))
    )
    dates = {(row["instrument_id"], row["adjustment"]): row["latest"] for row in rows}
    catalog = {item.symbol: item for item in Instrument.objects.filter(symbol__in=REQUIRED_SYMBOLS)}
    instruments = []
    ready = True
    for symbol in sorted(REQUIRED_SYMBOLS):
        item = catalog.get(symbol)
        raw_latest = dates.get((symbol, MarketBar.Adjustment.RAW))
        hfq_latest = dates.get((symbol, MarketBar.Adjustment.BACK))
        available = [value for value in [raw_latest, hfq_latest] if value]
        state = (
            "ready"
            if item and raw_latest == expected and hfq_latest == expected
            else "stale"
            if available
            else "missing"
        )
        ready = ready and state == "ready"
        instruments.append(
            {
                "symbol": symbol,
                "name": item.name if item else INSTRUMENT_SEED[symbol][0],
                "latest_date": min(available) if available else None,
                "raw_latest_date": raw_latest,
                "hfq_latest_date": hfq_latest,
                "state": state,
            }
        )
    last_batch = MarketDataBatch.objects.exclude(status=MarketDataBatch.Status.RUNNING).first()
    ready = ready and bool(last_batch and last_batch.status == MarketDataBatch.Status.HEALTHY)
    return {
        "ready": ready,
        "expected_session": expected,
        "source": "东方财富，经 AKShare 获取",
        "validation_source": "新浪财经",
        "adjustments": ["raw", "hfq"],
        "last_batch": {
            "id": last_batch.id,
            "status": last_batch.status,
            "finished_at": last_batch.finished_at,
            "errors": last_batch.errors,
            "warnings": last_batch.warnings,
        }
        if last_batch
        else None,
        "instruments": instruments,
    }


def _bars_as_of(
    *, adjustment: str, as_of: datetime, symbols: tuple[str, ...] = REQUIRED_SYMBOLS
) -> pd.DataFrame:
    rows = (
        MarketBar.objects.filter(
            adjustment=adjustment,
            instrument_id__in=symbols,
            created_at__lte=as_of,
            batch__finished_at__lte=as_of,
        )
        .order_by("instrument_id", "trade_date", "created_at", "id")
        .values("id", "instrument_id", "trade_date", "open", "high", "low", "close", "volume")
    )
    latest: dict[tuple[str, date], Any] = {}
    for bar_row in rows:
        latest[(bar_row["instrument_id"], bar_row["trade_date"])] = bar_row
    if not latest:
        return pd.DataFrame()
    records = list(latest.values())
    if adjustment == MarketBar.Adjustment.BACK:
        result = (
            pd.DataFrame(records)
            .pivot(index="trade_date", columns="instrument_id", values="close")
            .sort_index()
        )
        result.index = pd.to_datetime(result.index)
        return result
    frames = {}
    for field in ["open", "high", "low", "close", "volume"]:
        frames[field] = (
            pd.DataFrame(records)
            .pivot(index="trade_date", columns="instrument_id", values=field)
            .sort_index()
        )
    result = pd.concat(frames, axis=1)
    result.index = pd.to_datetime(result.index)
    return result


def _snapshot_as_of(snapshot: DatasetSnapshot) -> datetime:
    value = snapshot.metadata.get("data_as_of")
    return datetime.fromisoformat(value) if value else snapshot.created_at


def _visible_revision_ids(*, as_of: datetime, cutoff: date) -> tuple[list[str], list[str]]:
    bar_rows = (
        MarketBar.objects.filter(
            instrument_id__in=REQUIRED_SYMBOLS,
            trade_date__lte=cutoff,
            created_at__lte=as_of,
            batch__finished_at__lte=as_of,
        )
        .order_by("instrument_id", "trade_date", "adjustment", "created_at", "id")
        .values("id", "instrument_id", "trade_date", "adjustment")
    )
    bars: dict[tuple[str, date, str], str] = {}
    for bar_row in bar_rows:
        bars[(bar_row["instrument_id"], bar_row["trade_date"], bar_row["adjustment"])] = str(bar_row["id"])
    action_rows = (
        CorporateAction.objects.filter(
            instrument_id__in=REQUIRED_SYMBOLS,
            effective_date__lte=cutoff,
            created_at__lte=as_of,
            batch__finished_at__lte=as_of,
        )
        .order_by("instrument_id", "kind", "effective_date", "created_at", "id")
        .values("id", "instrument_id", "kind", "effective_date")
    )
    actions: dict[tuple[str, str, date], str] = {}
    for action_row in action_rows:
        actions[(action_row["instrument_id"], action_row["kind"], action_row["effective_date"])] = str(
            action_row["id"]
        )
    return sorted(bars.values()), sorted(actions.values())


def create_snapshot(cutoff_date: date | None = None) -> DatasetSnapshot:
    status = current_data_status()
    if not status["ready"]:
        raise ValueError("行情未就绪，不能创建数据快照")
    cutoff = min(cutoff_date or status["expected_session"], status["expected_session"])
    as_of = timezone.now()
    bar_ids, action_ids = _visible_revision_ids(as_of=as_of, cutoff=cutoff)
    digest_hash = hashlib.sha256(
        json.dumps(
            {
                "provider": "eastmoney-akshare",
                "cutoff": cutoff.isoformat(),
                "bars": bar_ids,
                "actions": action_ids,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    digest = digest_hash.hexdigest()
    snapshot, _ = DatasetSnapshot.objects.get_or_create(
        digest=digest,
        defaults={
            "cutoff_date": cutoff,
            "provider": "eastmoney-akshare",
            "metadata": {
                "symbols": list(REQUIRED_SYMBOLS),
                "bar_count": len(bar_ids),
                "corporate_action_count": len(action_ids),
                "data_as_of": as_of.isoformat(),
            },
        },
    )
    return snapshot


def load_snapshot_frames(snapshot: DatasetSnapshot) -> tuple[pd.DataFrame, pd.DataFrame]:
    as_of = _snapshot_as_of(snapshot)
    raw = _bars_as_of(adjustment=MarketBar.Adjustment.RAW, as_of=as_of)
    hfq = _bars_as_of(adjustment=MarketBar.Adjustment.BACK, as_of=as_of)
    cutoff = pd.Timestamp(snapshot.cutoff_date)
    raw = raw.loc[raw.index <= cutoff]
    hfq = hfq.loc[hfq.index <= cutoff]
    return raw, hfq


def corporate_actions_for_snapshot(
    snapshot: DatasetSnapshot, *, through: date | None = None
) -> list[CorporateAction]:
    cutoff = min(through or snapshot.cutoff_date, snapshot.cutoff_date)
    as_of = _snapshot_as_of(snapshot)
    rows = (
        CorporateAction.objects.filter(
            instrument_id__in=REQUIRED_SYMBOLS,
            effective_date__lte=cutoff,
            created_at__lte=as_of,
            batch__finished_at__lte=as_of,
        )
        .select_related("instrument")
        .order_by("instrument_id", "kind", "effective_date", "created_at", "id")
    )
    latest: dict[tuple[str, str, date], CorporateAction] = {}
    for action in rows:
        latest[(action.instrument_id, action.kind, action.effective_date)] = action
    return list(latest.values())


def current_corporate_actions_for_date(when: date) -> list[CorporateAction]:
    rows = (
        CorporateAction.objects.filter(
            instrument_id__in=REQUIRED_SYMBOLS,
            batch__finished_at__isnull=False,
        )
        .select_related("instrument")
        .order_by("instrument_id", "kind", "effective_date", "created_at", "id")
    )
    latest: dict[tuple[str, str, date], CorporateAction] = {}
    for action in rows:
        latest[(action.instrument_id, action.kind, action.effective_date)] = action
    return [
        action
        for action in latest.values()
        if (
            action.kind == CorporateAction.Kind.CASH_DIVIDEND
            and action.payment_date == when
            or action.kind == CorporateAction.Kind.SPLIT
            and action.effective_date == when
        )
    ]
