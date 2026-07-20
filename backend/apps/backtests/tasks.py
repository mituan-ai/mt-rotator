import secrets
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import record_audit

from .models import BacktestRun
from .services import execute_backtest

LEASE_MINUTES = 15
MAX_ATTEMPTS = 3
TERMINAL_STATUSES = {
    BacktestRun.Status.SUCCEEDED,
    BacktestRun.Status.FAILED,
    BacktestRun.Status.CANCELLED,
}


@transaction.atomic
def _claim_backtest(run_id: str) -> tuple[BacktestRun, str] | None:
    run = BacktestRun.objects.select_for_update().get(pk=run_id)
    now = timezone.now()
    if run.status in TERMINAL_STATUSES:
        return None
    if run.status == BacktestRun.Status.RUNNING and run.lease_expires_at and run.lease_expires_at > now:
        return None
    if (run.attempt_count or 0) >= MAX_ATTEMPTS:
        run.status = BacktestRun.Status.FAILED
        run.error = "Worker连续中断，已达到自动恢复上限"
        run.finished_at = now
        run.lease_token = ""
        run.lease_expires_at = None
        run.save(update_fields=["status", "error", "finished_at", "lease_token", "lease_expires_at"])
        return None
    token = secrets.token_urlsafe(24)
    run.status = BacktestRun.Status.RUNNING
    run.attempt_count = (run.attempt_count or 0) + 1
    run.lease_token = token
    run.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    run.started_at = now
    run.finished_at = None
    run.error = ""
    run.save(
        update_fields=[
            "status",
            "attempt_count",
            "lease_token",
            "lease_expires_at",
            "started_at",
            "finished_at",
            "error",
        ]
    )
    return run, token


@transaction.atomic
def _finish_backtest(run_id: str, token: str, *, result: dict | None = None, error: str = "") -> bool:
    run = BacktestRun.objects.select_for_update().get(pk=run_id)
    if run.status != BacktestRun.Status.RUNNING or run.lease_token != token:
        return False
    run.status = BacktestRun.Status.FAILED if error else BacktestRun.Status.SUCCEEDED
    run.error = error
    run.result = result or {}
    run.finished_at = timezone.now()
    run.lease_token = ""
    run.lease_expires_at = None
    run.save(
        update_fields=[
            "status",
            "error",
            "result",
            "finished_at",
            "lease_token",
            "lease_expires_at",
        ]
    )
    return True


@shared_task(name="apps.backtests.tasks.run_backtest")
def run_backtest(run_id: str) -> str:
    claimed = _claim_backtest(run_id)
    if claimed is None:
        return run_id
    run, token = claimed
    try:
        result = execute_backtest(run)
    except Exception as exc:
        _finish_backtest(run_id, token, error=str(exc))
    else:
        _finish_backtest(run_id, token, result=result)
    return run_id


@shared_task(name="apps.backtests.tasks.recover_backtest_runs")
def recover_backtest_runs() -> dict:
    now = timezone.now()
    candidates = list(
        BacktestRun.objects.filter(
            Q(status=BacktestRun.Status.QUEUED)
            | Q(status=BacktestRun.Status.RUNNING)
            & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
        ).values_list("id", flat=True)
    )
    dispatched = 0
    failed = 0
    for run_id in candidates:
        with transaction.atomic():
            run = BacktestRun.objects.select_for_update().get(pk=run_id)
            if (
                run.status == BacktestRun.Status.RUNNING
                and run.lease_expires_at
                and run.lease_expires_at > now
            ):
                continue
            if (run.attempt_count or 0) >= MAX_ATTEMPTS:
                run.status = BacktestRun.Status.FAILED
                run.error = "Worker连续中断，已达到自动恢复上限"
                run.finished_at = now
                run.lease_token = ""
                run.lease_expires_at = None
                run.save(
                    update_fields=[
                        "status",
                        "error",
                        "finished_at",
                        "lease_token",
                        "lease_expires_at",
                    ]
                )
                failed += 1
                continue
            run.status = BacktestRun.Status.QUEUED
            run.lease_token = ""
            run.lease_expires_at = None
            run.save(update_fields=["status", "lease_token", "lease_expires_at"])
        task = run_backtest.delay(str(run_id))
        BacktestRun.objects.filter(pk=run_id).update(task_id=task.id)
        dispatched += 1
    if dispatched or failed:
        record_audit("backtest.recovery_finished", detail={"dispatched": dispatched, "failed": failed})
    return {"dispatched": dispatched, "failed": failed}
