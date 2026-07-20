import secrets

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.core.models import record_audit

from .models import MarketDataBatch
from .services import import_market_data


@shared_task(name="apps.market.tasks.update_market_data")
def update_market_data(triggered_by: str = "scheduler", full_refresh: bool = False) -> str:
    lock_token = secrets.token_urlsafe(16)
    if not cache.add("lock:market-update", lock_token, timeout=2 * 60 * 60):
        return "already-running"
    try:
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
    finally:
        if cache.get("lock:market-update") == lock_token:
            cache.delete("lock:market-update")
    record_audit(
        "market.batch_finished", target=batch, detail={"status": batch.status, "rows": batch.row_count}
    )
    if batch.status == batch.Status.HEALTHY:
        from apps.paper.tasks import run_daily_paper_cycle

        run_daily_paper_cycle.delay(str(batch.id))
    return str(batch.id)
