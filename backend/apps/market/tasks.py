import secrets
from collections.abc import Iterator
from contextlib import contextmanager

from celery import shared_task
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from apps.core.models import record_audit

from .models import MarketDataBatch
from .services import import_market_data, repair_instrument_data

MARKET_UPDATE_LOCK_ID = 1_297_364_821


@contextmanager
def _market_update_lock() -> Iterator[bool]:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [MARKET_UPDATE_LOCK_ID])
            acquired = bool(cursor.fetchone()[0])
        try:
            yield acquired
        finally:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [MARKET_UPDATE_LOCK_ID])
        return

    lock_token = secrets.token_urlsafe(16)
    acquired = cache.add("lock:market-update", lock_token, timeout=2 * 60 * 60)
    try:
        yield acquired
    finally:
        if acquired and cache.get("lock:market-update") == lock_token:
            cache.delete("lock:market-update")


def _recover_interrupted_batches() -> None:
    for batch in MarketDataBatch.objects.filter(status=MarketDataBatch.Status.RUNNING):
        message = "前一次行情任务被中断，已保留完成部分并从断点继续"
        batch.status = MarketDataBatch.Status.FAILED
        batch.errors = [*batch.errors, {"source": "recovery", "message": message}]
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "errors", "finished_at"])
        record_audit("market.batch_recovered", target=batch, detail={"message": message})


@shared_task(name="apps.market.tasks.update_market_data")
def update_market_data(triggered_by: str = "scheduler", full_refresh: bool = False) -> str:
    with _market_update_lock() as acquired:
        if not acquired:
            return "already-running"
        _recover_interrupted_batches()
        try:
            batch = import_market_data(triggered_by=triggered_by, full_refresh=full_refresh)
        except Exception as exc:
            failed_batch = MarketDataBatch.objects.filter(
                status=MarketDataBatch.Status.RUNNING,
                triggered_by=triggered_by,
            ).first()
            if failed_batch:
                failed_batch.status = MarketDataBatch.Status.FAILED
                failed_batch.errors = [*failed_batch.errors, {"source": "pipeline", "message": str(exc)}]
                failed_batch.finished_at = timezone.now()
                failed_batch.save(update_fields=["status", "errors", "finished_at"])
                record_audit("market.batch_failed", target=failed_batch, detail={"error": str(exc)})
            raise
    record_audit(
        "market.batch_finished", target=batch, detail={"status": batch.status, "rows": batch.row_count}
    )
    return str(batch.id)


@shared_task(name="apps.market.tasks.repair_market_instrument")
def repair_market_instrument(symbol: str, triggered_by: str) -> str:
    with _market_update_lock() as acquired:
        if not acquired:
            return "already-running"
        _recover_interrupted_batches()
        batch = repair_instrument_data(symbol, triggered_by=triggered_by)
    record_audit(
        "market.instrument_repaired",
        target=batch,
        detail={"symbol": symbol, "status": batch.status},
    )
    return str(batch.id)
