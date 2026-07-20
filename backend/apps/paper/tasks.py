import secrets

from celery import shared_task
from django.core.cache import cache

from apps.core.models import record_audit
from apps.market.models import MarketDataBatch
from apps.market.services import current_data_status

from .services import reconcile_paper_through


@shared_task(name="apps.paper.tasks.reconcile_paper_cycles")
def reconcile_paper_cycles() -> dict:
    token = secrets.token_urlsafe(16)
    lock_key = "lock:paper-reconcile"
    if not cache.add(lock_key, token, timeout=30 * 60):
        return {"status": "busy"}
    try:
        market = current_data_status()
        result = reconcile_paper_through(market["expected_session"])
        record_audit("paper.reconcile_finished", detail=result)
        return result
    except Exception as exc:
        record_audit("paper.reconcile_failed", detail={"error": str(exc)})
        raise
    finally:
        if cache.get(lock_key) == token:
            cache.delete(lock_key)


@shared_task(name="apps.paper.tasks.run_daily_paper_cycle")
def run_daily_paper_cycle(batch_id: str) -> dict:
    """Compatibility entry point for tasks queued by releases before cycle reconciliation."""
    batch = MarketDataBatch.objects.get(pk=batch_id)
    if batch.status != MarketDataBatch.Status.HEALTHY or not batch.expected_session:
        return {"status": "blocked", "reason": "market_data_not_healthy"}
    return reconcile_paper_through(batch.expected_session)
