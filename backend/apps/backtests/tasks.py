from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import BacktestRun
from .services import execute_backtest


@shared_task(name="apps.backtests.tasks.run_backtest")
def run_backtest(run_id: str) -> str:
    with transaction.atomic():
        run = BacktestRun.objects.select_for_update().get(pk=run_id)
        if run.status != BacktestRun.Status.QUEUED:
            return run_id
        run.status = BacktestRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])
    try:
        result = execute_backtest(run)
    except Exception as exc:
        run.status = BacktestRun.Status.FAILED
        run.error = str(exc)
    else:
        run.status = BacktestRun.Status.SUCCEEDED
        run.result = result
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "result", "finished_at"])
    return run_id
