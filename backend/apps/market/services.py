from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from .calendar import calendar, latest_expected_session
from .models import CorporateAction, DatasetSnapshot, Instrument, MarketBar, MarketDataBatch
from .providers import CatalogRecord, CorporateActionRecord, ProviderError, SinaProvider
from .settlement import SETTLEMENT_RULES_VERSION, settlement_cycle_for

HISTORY_MONTHS = 24
MIN_TRADE_BARS = 20
MIN_ADVICE_BARS = 252
MIN_AVERAGE_AMOUNT = Decimal("10000000")
MIN_SIGNAL_COVERAGE = Decimal("0.95")
REFERENCE_SYMBOL = "510300"

# Kept only to seed a usable catalog before the first network import and to
# preserve compatibility with existing snapshots. Runtime eligibility is dynamic.
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
        item, _ = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={
                "name": name,
                "exchange": exchange,
                "lot_size": 100,
                "enabled": True,
                "settlement_cycle": settlement_cycle_for(symbol),
            },
        )
        result.append(item)
    return result


def _asset_class(name: str, symbol: str) -> str:
    normalized = name.casefold()
    if symbol.startswith("513") or any(
        word in normalized for word in ["纳指", "恒生", "港股", "日经", "德国", "法国", "标普"]
    ):
        return Instrument.AssetClass.CROSS_BORDER
    if "黄金" in normalized or symbol.startswith("518"):
        return Instrument.AssetClass.GOLD
    if any(word in normalized for word in ["豆粕", "有色", "能源化工", "商品", "原油"]):
        return Instrument.AssetClass.COMMODITY
    if any(word in normalized for word in ["货币", "现金", "添益", "保证金"]):
        return Instrument.AssetClass.MONEY
    if symbol.startswith("511") or any(
        word in normalized for word in ["国债", "政金债", "信用债", "可转债", "公司债"]
    ):
        return Instrument.AssetClass.BOND
    return Instrument.AssetClass.EQUITY


def _quantized(field: str, value: Any) -> Decimal:
    places = Decimal("0.000001") if field in {"open", "high", "low", "close"} else Decimal("0.01")
    return Decimal(str(value)).quantize(places)


def _same_bar(current: MarketBar, row: dict[str, Any]) -> bool:
    return all(
        getattr(current, field) == _quantized(field, row[field])
        for field in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ]
    )


@transaction.atomic
def store_bars(
    *, instrument: Instrument, batch: MarketDataBatch, adjustment: str, frame: pd.DataFrame
) -> int:
    created = 0
    records = frame.to_dict("records")
    existing = {
        item.trade_date: item
        for item in MarketBar.objects.select_for_update().filter(
            instrument=instrument,
            adjustment=adjustment,
            trade_date__in=[row["trade_date"] for row in records],
            is_current=True,
        )
    }
    for row in records:
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
            open=_quantized("open", row["open"]),
            high=_quantized("high", row["high"]),
            low=_quantized("low", row["low"]),
            close=_quantized("close", row["close"]),
            volume=_quantized("volume", row["volume"]),
            amount=_quantized("amount", row["amount"]),
        )
        created += 1
    return created


def _previous_session(value: date) -> date:
    timestamp = pd.Timestamp(value)
    try:
        session = calendar().date_to_session(timestamp, direction="previous")
    except ValueError:
        return (timestamp - pd.offsets.BDay(1)).date()
    if session.date() == value:
        session = calendar().previous_session(session)
    return session.date()


@transaction.atomic
def _store_actions(*, batch: MarketDataBatch, records: Iterable[CorporateActionRecord]) -> int:
    created = 0
    for record in records:
        record_date = record.record_date or _previous_session(record.effective_date)
        current = (
            CorporateAction.objects.select_for_update()
            .filter(
                instrument_id=record.symbol,
                kind=record.kind,
                effective_date=record.effective_date,
                is_current=True,
            )
            .first()
        )
        detail = {**record.detail, "record_date_estimated": record.record_date is None}
        if current and all(
            [
                current.record_date == record_date,
                current.payment_date == record.payment_date,
                current.value == record.value,
                current.source_detail == detail,
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
            record_date=record_date,
            effective_date=record.effective_date,
            payment_date=record.payment_date,
            value=record.value,
            source_detail=detail,
        )
        created += 1
    return created


def _catalog_frame(record: CatalogRecord, expected: date) -> pd.DataFrame:
    return pd.DataFrame([{"trade_date": expected, **(record.bar or {})}])


def _upsert_catalog(records: list[CatalogRecord]) -> dict[str, Instrument]:
    symbols = {record.symbol for record in records}
    Instrument.objects.filter(catalog_active=True).exclude(symbol__in=symbols).update(
        catalog_active=False,
        data_status=Instrument.DataStatus.STALE,
        trade_eligible=False,
        advice_eligible=False,
        data_error="当前新浪ETF目录中不存在",
    )
    result: dict[str, Instrument] = {}
    for record in records:
        instrument, created = Instrument.objects.get_or_create(
            symbol=record.symbol,
            defaults={
                "name": record.name,
                "exchange": record.exchange,
                "lot_size": 100,
                "asset_class": _asset_class(record.name, record.symbol),
                "settlement_cycle": settlement_cycle_for(record.symbol),
            },
        )
        instrument.name = record.name
        instrument.exchange = record.exchange
        instrument.catalog_active = True
        instrument.asset_class = _asset_class(record.name, record.symbol)
        if created or not instrument.metadata.get("settlement_override"):
            instrument.settlement_cycle = settlement_cycle_for(record.symbol)
        instrument.metadata = {
            **instrument.metadata,
            "catalog_source": SinaProvider.name,
            "settlement_rules_version": SETTLEMENT_RULES_VERSION,
        }
        instrument.save(
            update_fields=[
                "name",
                "exchange",
                "catalog_active",
                "asset_class",
                "settlement_cycle",
                "metadata",
                "updated_at",
            ]
        )
        result[record.symbol] = instrument
    return result


def _refresh_instrument_health(instrument: Instrument, expected: date, error: str = "") -> None:
    bars = list(
        MarketBar.objects.filter(
            instrument=instrument,
            adjustment=MarketBar.Adjustment.RAW,
            is_current=True,
        ).order_by("-trade_date")[:MIN_ADVICE_BARS]
    )
    count = MarketBar.objects.filter(
        instrument=instrument,
        adjustment=MarketBar.Adjustment.RAW,
        is_current=True,
    ).count()
    latest = bars[0].trade_date if bars else None
    recent = bars[:MIN_TRADE_BARS]
    average_amount = (
        sum((item.amount for item in recent), Decimal("0")) / len(recent) if recent else Decimal("0")
    )
    listed_on = (
        MarketBar.objects.filter(
            instrument=instrument,
            adjustment=MarketBar.Adjustment.RAW,
            is_current=True,
        ).aggregate(value=Min("trade_date"))["value"]
        or instrument.listed_on
    )
    metadata = dict(instrument.metadata)
    chronological = list(reversed(bars))
    for previous, current in zip(chronological, chronological[1:], strict=False):
        ratio = current.close / previous.close if previous.close else Decimal("1")
        has_split = CorporateAction.objects.filter(
            instrument=instrument,
            kind=CorporateAction.Kind.SPLIT,
            effective_date=current.trade_date,
            is_current=True,
        ).exists()
        if (ratio > Decimal("1.5") or ratio < Decimal("0.5")) and not has_split:
            metadata["corporate_action_pending"] = True
            error = error or f"{current.trade_date} 出现疑似份额折算价格跳变"
            break
    blocked = metadata.get("corporate_action_pending", False)
    status = (
        Instrument.DataStatus.BLOCKED
        if blocked
        else Instrument.DataStatus.READY
        if latest == expected
        else Instrument.DataStatus.STALE
        if latest
        else Instrument.DataStatus.MISSING
    )
    trade_eligible = bool(
        instrument.enabled
        and instrument.catalog_active
        and status == Instrument.DataStatus.READY
        and count >= MIN_TRADE_BARS
        and average_amount >= MIN_AVERAGE_AMOUNT
    )
    instrument.listed_on = listed_on
    instrument.last_bar_date = latest
    instrument.average_amount_20d = average_amount.quantize(Decimal("0.01"))
    instrument.data_status = status
    instrument.data_error = error
    instrument.trade_eligible = trade_eligible
    instrument.advice_eligible = trade_eligible and count >= MIN_ADVICE_BARS
    instrument.metadata = {**metadata, "valid_bar_count": count}
    instrument.save(
        update_fields=[
            "listed_on",
            "last_bar_date",
            "average_amount_20d",
            "data_status",
            "data_error",
            "trade_eligible",
            "advice_eligible",
            "metadata",
            "updated_at",
        ]
    )


def _history_start(expected: date, requested: date | None) -> date:
    minimum = expected - relativedelta(months=HISTORY_MONTHS)
    return max(minimum, requested) if requested else minimum


def import_market_data(
    *,
    triggered_by: str = "scheduler",
    start: date | None = None,
    full_refresh: bool = False,
) -> MarketDataBatch:
    expected = latest_expected_session()
    batch = MarketDataBatch.objects.create(
        expected_session=expected,
        triggered_by=triggered_by,
        provider=SinaProvider.name,
    )
    provider = SinaProvider()
    errors: list[dict] = []
    warnings: list[dict] = []
    row_count = 0
    revision_count = 0
    action_revision_count = 0

    try:
        records = provider.fetch_catalog()
    except ProviderError as exc:
        Instrument.objects.filter(catalog_active=True).update(
            data_status=Instrument.DataStatus.STALE,
            data_error=str(exc),
            trade_eligible=False,
            advice_eligible=False,
        )
        batch.status = MarketDataBatch.Status.FAILED
        batch.errors = [{"source": "catalog", "message": str(exc)}]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "errors", "finished_at"])
        return batch

    instruments = _upsert_catalog(records)
    history_start = _history_start(expected, start)
    previous_session = _previous_session(expected)
    request_interval = getattr(provider, "request_interval_seconds", 0)
    for record in records:
        instrument = instruments[record.symbol]
        item_error = ""
        if record.bar:
            frame = _catalog_frame(record, expected)
            row_count += 1
            revision_count += store_bars(
                instrument=instrument,
                batch=batch,
                adjustment=MarketBar.Adjustment.RAW,
                frame=frame,
            )
        else:
            warnings.append({"symbol": record.symbol, "message": "目录中没有有效收盘行情"})

        history_attempted = bool(instrument.metadata.get("history_backfilled"))
        needs_history = bool(
            full_refresh
            or not history_attempted
            or record.bar is None
            or (instrument.last_bar_date and instrument.last_bar_date < previous_session)
        )
        metadata = dict(instrument.metadata)
        if needs_history:
            try:
                history = provider.fetch_bars(record.symbol, history_start, expected)
                row_count += len(history)
                revision_count += store_bars(
                    instrument=instrument,
                    batch=batch,
                    adjustment=MarketBar.Adjustment.RAW,
                    frame=history,
                )
                metadata.update(
                    {
                        "history_backfilled": True,
                        "history_start": history_start.isoformat(),
                        "history_checked_on": expected.isoformat(),
                    }
                )
            except ProviderError as exc:
                item_error = str(exc)
                errors.append({"symbol": record.symbol, "message": item_error})
            finally:
                if request_interval:
                    time.sleep(request_interval)

        needs_actions = bool(
            needs_history
            or (instrument.trade_eligible and metadata.get("actions_checked_on") != expected.isoformat())
        )
        if needs_actions:
            try:
                action_revision_count += _store_actions(
                    batch=batch,
                    records=provider.fetch_dividends(record.symbol),
                )
                metadata["actions_checked_on"] = expected.isoformat()
            except ProviderError as exc:
                warnings.append({"symbol": record.symbol, "source": "dividends", "message": str(exc)})
            finally:
                if request_interval:
                    time.sleep(request_interval)
        if metadata != instrument.metadata:
            instrument.metadata = metadata
            instrument.save(update_fields=["metadata", "updated_at"])
        _refresh_instrument_health(instrument, expected, item_error)

    ready_count = Instrument.objects.filter(
        catalog_active=True, data_status=Instrument.DataStatus.READY
    ).count()
    batch.row_count = row_count
    batch.errors = errors[:200]
    batch.warnings = warnings[:200]
    batch.metadata = {
        "catalog_count": len(records),
        "ready_count": ready_count,
        "history_start": history_start.isoformat(),
        "history_months": HISTORY_MONTHS,
        "revision_count": revision_count,
        "corporate_action_revision_count": action_revision_count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "full_refresh": full_refresh,
    }
    batch.finished_at = timezone.now()
    batch.status = (
        MarketDataBatch.Status.FAILED
        if ready_count == 0
        else MarketDataBatch.Status.DEGRADED
        if errors
        else MarketDataBatch.Status.HEALTHY
    )
    batch.save(update_fields=["row_count", "errors", "warnings", "metadata", "finished_at", "status"])
    return batch


def repair_instrument_data(symbol: str, *, triggered_by: str) -> MarketDataBatch:
    instrument = Instrument.objects.get(symbol=symbol, catalog_active=True)
    expected = latest_expected_session()
    batch = MarketDataBatch.objects.create(
        expected_session=expected,
        triggered_by=triggered_by,
        provider=SinaProvider.name,
    )
    provider = SinaProvider()
    try:
        frame = provider.fetch_bars(symbol, _history_start(expected, None), expected)
        revisions = store_bars(
            instrument=instrument,
            batch=batch,
            adjustment=MarketBar.Adjustment.RAW,
            frame=frame,
        )
        action_revisions = _store_actions(batch=batch, records=provider.fetch_dividends(symbol))
        instrument.metadata = {**instrument.metadata, "history_backfilled": True}
        instrument.save(update_fields=["metadata", "updated_at"])
        _refresh_instrument_health(instrument, expected)
        batch.status = MarketDataBatch.Status.HEALTHY
        batch.row_count = len(frame)
        batch.metadata = {
            "symbol": symbol,
            "revision_count": revisions,
            "corporate_action_revision_count": action_revisions,
        }
    except ProviderError as exc:
        _refresh_instrument_health(instrument, expected, str(exc))
        batch.status = MarketDataBatch.Status.FAILED
        batch.errors = [{"symbol": symbol, "message": str(exc)}]
    batch.finished_at = timezone.now()
    batch.save(update_fields=["status", "row_count", "errors", "metadata", "finished_at"])
    return batch


@transaction.atomic
def update_instrument_controls(
    instrument: Instrument,
    *,
    enabled: bool | None = None,
    settlement_cycle: str | None = None,
    asset_class: str | None = None,
) -> Instrument:
    instrument = Instrument.objects.select_for_update().get(pk=instrument.pk)
    update_fields = ["updated_at"]
    if enabled is not None:
        instrument.enabled = enabled
        update_fields.append("enabled")
    if settlement_cycle is not None:
        instrument.settlement_cycle = settlement_cycle
        instrument.metadata = {
            **instrument.metadata,
            "settlement_override": True,
            "settlement_rules_version": SETTLEMENT_RULES_VERSION,
        }
        update_fields.extend(["settlement_cycle", "metadata"])
    if asset_class is not None:
        instrument.asset_class = asset_class
        update_fields.append("asset_class")
    instrument.save(update_fields=list(dict.fromkeys(update_fields)))
    _refresh_instrument_health(instrument, latest_expected_session(), instrument.data_error)
    return instrument


@transaction.atomic
def record_manual_corporate_action(
    instrument: Instrument,
    *,
    kind: str,
    effective_date: date,
    value: Decimal,
    record_date: date | None = None,
    payment_date: date | None = None,
) -> CorporateAction:
    batch = MarketDataBatch.objects.create(
        provider="manual-admin",
        status=MarketDataBatch.Status.HEALTHY,
        expected_session=latest_expected_session(),
        row_count=1,
        metadata={"manual_corporate_action": True},
        finished_at=timezone.now(),
        triggered_by="admin",
    )
    current = (
        CorporateAction.objects.select_for_update()
        .filter(
            instrument=instrument,
            kind=kind,
            effective_date=effective_date,
            is_current=True,
        )
        .first()
    )
    if current:
        current.is_current = False
        current.save(update_fields=["is_current"])
    action = CorporateAction.objects.create(
        instrument=instrument,
        batch=batch,
        kind=kind,
        record_date=record_date,
        effective_date=effective_date,
        payment_date=payment_date,
        value=value,
        source_detail={"source": "manual-admin"},
    )
    if kind == CorporateAction.Kind.SPLIT:
        instrument.metadata = {**instrument.metadata, "corporate_action_pending": False}
        instrument.save(update_fields=["metadata", "updated_at"])
        _refresh_instrument_health(instrument, latest_expected_session())
    return action


def current_data_status() -> dict:
    expected = latest_expected_session()
    instruments = list(Instrument.objects.filter(catalog_active=True, enabled=True).order_by("symbol"))
    batch_complete = market_session_import_complete(expected)

    def effective_status(item: Instrument) -> str:
        if item.data_status == Instrument.DataStatus.READY and (
            item.last_bar_date != expected or not batch_complete
        ):
            return Instrument.DataStatus.STALE
        return item.data_status

    candidate = [
        item
        for item in instruments
        if int(item.metadata.get("valid_bar_count", 0)) >= MIN_TRADE_BARS
        and item.average_amount_20d >= MIN_AVERAGE_AMOUNT
    ]
    ready_candidates = [item for item in candidate if effective_status(item) == Instrument.DataStatus.READY]
    coverage = Decimal(len(ready_candidates)) / len(candidate) if candidate else Decimal("0")
    reference = next((item for item in instruments if item.symbol == REFERENCE_SYMBOL), None)
    ready = bool(
        reference
        and effective_status(reference) == Instrument.DataStatus.READY
        and candidate
        and coverage >= MIN_SIGNAL_COVERAGE
    )
    counts = {
        "catalog": len(instruments),
        "trade_eligible": sum(
            item.trade_eligible and effective_status(item) == Instrument.DataStatus.READY
            for item in instruments
        ),
        "advice_eligible": sum(
            item.advice_eligible and effective_status(item) == Instrument.DataStatus.READY
            for item in instruments
        ),
        "ready": sum(effective_status(item) == Instrument.DataStatus.READY for item in instruments),
        "stale": sum(effective_status(item) == Instrument.DataStatus.STALE for item in instruments),
        "missing": sum(effective_status(item) == Instrument.DataStatus.MISSING for item in instruments),
        "blocked": sum(effective_status(item) == Instrument.DataStatus.BLOCKED for item in instruments),
    }
    problematic = [
        {
            "symbol": item.symbol,
            "name": item.name,
            "latest_date": item.last_bar_date,
            "state": effective_status(item),
            "error": item.data_error,
        }
        for item in instruments
        if effective_status(item) != Instrument.DataStatus.READY
    ][:100]
    last_batch = MarketDataBatch.objects.exclude(status=MarketDataBatch.Status.RUNNING).first()
    return {
        "ready": ready,
        "expected_session": expected,
        "source": "新浪财经，经 AKShare 获取",
        "validation_source": "内部字段、日期与覆盖率校验",
        "adjustments": ["raw", "total_return"],
        "coverage": str(coverage.quantize(Decimal("0.0001"))),
        "counts": counts,
        "last_batch": {
            "id": last_batch.id,
            "status": last_batch.status,
            "finished_at": last_batch.finished_at,
            "errors": last_batch.errors,
            "warnings": last_batch.warnings,
        }
        if last_batch
        else None,
        "instruments": problematic,
    }


def market_session_import_complete(target: date) -> bool:
    return MarketDataBatch.objects.filter(
        expected_session__gte=target,
        status__in=[MarketDataBatch.Status.HEALTHY, MarketDataBatch.Status.DEGRADED],
        finished_at__isnull=False,
        metadata__catalog_count__gt=0,
    ).exists()


def _bars_as_of(*, adjustment: str, as_of: datetime, symbols: Iterable[str]) -> pd.DataFrame:
    rows = (
        MarketBar.objects.filter(
            adjustment=adjustment,
            instrument_id__in=list(symbols),
            created_at__lte=as_of,
            batch__finished_at__lte=as_of,
        )
        .order_by("instrument_id", "trade_date", "created_at", "id")
        .values(
            "id",
            "instrument_id",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        )
    )
    latest: dict[tuple[str, date], Any] = {}
    for row in rows:
        latest[(row["instrument_id"], row["trade_date"])] = row
    if not latest:
        return pd.DataFrame()
    records = list(latest.values())
    frames = {
        field: pd.DataFrame(records)
        .pivot(index="trade_date", columns="instrument_id", values=field)
        .sort_index()
        for field in ["open", "high", "low", "close", "volume", "amount"]
    }
    result = pd.concat(frames, axis=1)
    result.index = pd.to_datetime(result.index)
    return result


def _snapshot_as_of(snapshot: DatasetSnapshot) -> datetime:
    value = snapshot.metadata.get("data_as_of")
    return datetime.fromisoformat(value) if value else snapshot.created_at


def _visible_revision_ids(
    *, as_of: datetime, cutoff: date, symbols: list[str]
) -> tuple[list[str], list[str]]:
    bar_rows = (
        MarketBar.objects.filter(
            instrument_id__in=symbols,
            trade_date__lte=cutoff,
            adjustment=MarketBar.Adjustment.RAW,
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
            instrument_id__in=symbols,
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
        raise ValueError("主要ETF行情覆盖不足，不能创建新的策略快照")
    cutoff = min(cutoff_date or status["expected_session"], status["expected_session"])
    symbols = list(
        Instrument.objects.filter(advice_eligible=True, catalog_active=True, enabled=True)
        .order_by("symbol")
        .values_list("symbol", flat=True)
    )
    if REFERENCE_SYMBOL not in symbols:
        symbols.append(REFERENCE_SYMBOL)
        symbols.sort()
    as_of = timezone.now()
    bar_ids, action_ids = _visible_revision_ids(as_of=as_of, cutoff=cutoff, symbols=symbols)
    digest = hashlib.sha256(
        json.dumps(
            {
                "provider": SinaProvider.name,
                "cutoff": cutoff.isoformat(),
                "symbols": symbols,
                "bars": bar_ids,
                "actions": action_ids,
                "rules": SETTLEMENT_RULES_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    snapshot, _ = DatasetSnapshot.objects.get_or_create(
        digest=digest,
        defaults={
            "cutoff_date": cutoff,
            "provider": SinaProvider.name,
            "metadata": {
                "symbols": symbols,
                "universe": symbols,
                "universe_rule": {
                    "minimum_bars": MIN_ADVICE_BARS,
                    "minimum_average_amount_20d": str(MIN_AVERAGE_AMOUNT),
                },
                "bar_count": len(bar_ids),
                "corporate_action_count": len(action_ids),
                "data_as_of": as_of.isoformat(),
            },
        },
    )
    return snapshot


def _total_return_frame(raw: pd.DataFrame, actions: list[CorporateAction]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    closes = raw["close"].astype(float)
    result = pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
    action_map: dict[tuple[str, date], tuple[float, float]] = {}
    for action in actions:
        key = (action.instrument_id, action.effective_date)
        dividend, split = action_map.get(key, (0.0, 1.0))
        if action.kind == CorporateAction.Kind.CASH_DIVIDEND:
            dividend += float(action.value)
        elif action.kind == CorporateAction.Kind.SPLIT:
            split *= float(action.value)
        action_map[key] = (dividend, split)
    for symbol in closes.columns:
        series = closes[symbol].dropna()
        if series.empty:
            continue
        returns = series.pct_change(fill_method=None)
        for timestamp in series.index[1:]:
            dividend, split = action_map.get((symbol, timestamp.date()), (0.0, 1.0))
            previous = series.shift(1).loc[timestamp]
            if previous and (dividend or split != 1.0):
                returns.loc[timestamp] = (series.loc[timestamp] * split + dividend) / previous - 1
        total_return = (1 + returns.fillna(0)).cumprod() * series.iloc[0]
        result.loc[total_return.index, symbol] = total_return
    return result


def load_snapshot_frames(snapshot: DatasetSnapshot) -> tuple[pd.DataFrame, pd.DataFrame]:
    as_of = _snapshot_as_of(snapshot)
    symbols = snapshot.metadata.get("symbols") or list(
        Instrument.objects.filter(advice_eligible=True).values_list("symbol", flat=True)
    )
    raw = _bars_as_of(adjustment=MarketBar.Adjustment.RAW, as_of=as_of, symbols=symbols)
    cutoff = pd.Timestamp(snapshot.cutoff_date)
    raw = raw.loc[raw.index <= cutoff]
    actions = corporate_actions_for_snapshot(snapshot)
    total_return = _total_return_frame(raw, actions)
    return raw, total_return


def corporate_actions_for_snapshot(
    snapshot: DatasetSnapshot, *, through: date | None = None
) -> list[CorporateAction]:
    cutoff = min(through or snapshot.cutoff_date, snapshot.cutoff_date)
    as_of = _snapshot_as_of(snapshot)
    symbols = snapshot.metadata.get("symbols") or []
    rows = (
        CorporateAction.objects.filter(
            instrument_id__in=symbols,
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
    return [action for action, _ in current_corporate_actions_between(when - timedelta(days=1), when)]


def current_corporate_actions_between(after: date, through: date) -> list[tuple[CorporateAction, date]]:
    rows = (
        CorporateAction.objects.filter(batch__finished_at__isnull=False)
        .select_related("instrument")
        .order_by("instrument_id", "kind", "effective_date", "created_at", "id")
    )
    latest: dict[tuple[str, str, date], CorporateAction] = {}
    for action in rows:
        latest[(action.instrument_id, action.kind, action.effective_date)] = action
    due = []
    for action in latest.values():
        event_date = (
            action.payment_date
            if action.kind == CorporateAction.Kind.CASH_DIVIDEND
            else action.effective_date
        )
        if event_date and after < event_date <= through:
            due.append((action, event_date))
    return sorted(due, key=lambda item: (item[1], item[0].instrument_id, item[0].kind))
