from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.backtests.models import BacktestRun
from apps.backtests.tasks import (
    MAX_ATTEMPTS,
    _claim_backtest,
    _finish_backtest,
    recover_backtest_runs,
    run_backtest,
)
from apps.market.models import CorporateAction, MarketDataBatch
from apps.market.services import seed_instruments
from apps.market.tasks import update_market_data
from apps.paper.models import HoldingSnapshot, LedgerEntry, PaperAccount, PaperCycleRun, Position
from apps.paper.services import (
    _active_accounts_for_session,
    _claim_cycle,
    _finish_cycle,
    apply_actions_between,
    reconcile_paper_through,
)
from apps.paper.tasks import reconcile_paper_cycles, run_daily_paper_cycle
from apps.strategies.services import seed_strategy_catalog
from tests.factories import completed_batch, create_backtest_run


@pytest.mark.django_db
def test_paper_reconciliation_catches_up_once_and_reclaims_failed_cycle(user, monkeypatch):
    target = date(2025, 4, 1)
    generated = []
    account = PaperAccount.objects.create(user=user, strategy_version=seed_strategy_catalog()[0])
    monkeypatch.setattr(
        "apps.paper.services.current_data_status",
        lambda: {"ready": True, "expected_session": target},
    )
    monkeypatch.setattr(
        "apps.paper.services.create_snapshot",
        lambda session_date: SimpleNamespace(cutoff_date=session_date),
    )
    monkeypatch.setattr(
        "apps.paper.services.generate_all_daily_signals",
        lambda snapshot: generated.append(snapshot.cutoff_date) or [],
    )

    assert reconcile_paper_through(target) == {
        "status": "blocked",
        "reason": "market_data_import_pending",
    }
    completed_batch(expected=target)
    first = reconcile_paper_through(target)
    second = reconcile_paper_through(target)

    assert first == {"status": "ok", "processed": 1, "processed_through": "2025-04-01"}
    assert second["processed"] == 0
    assert generated == [target, target]
    assert PaperCycleRun.objects.filter(status=PaperCycleRun.Status.SUCCEEDED).count() == 1
    assert not account.nav_snapshots.exists()

    failed = PaperCycleRun.objects.get(session_date=target)
    failed.status = PaperCycleRun.Status.FAILED
    failed.error = "interrupted"
    failed.save(update_fields=["status", "error"])
    retry = reconcile_paper_through(target)
    failed.refresh_from_db()
    assert retry["processed"] == 1
    assert failed.status == PaperCycleRun.Status.SUCCEEDED
    assert failed.attempt_count == 2


@pytest.mark.django_db
def test_paper_cycle_stale_attempt_cannot_overwrite_new_owner():
    session_date = date(2025, 3, 31)
    first = _claim_cycle(session_date)
    assert first is not None
    PaperCycleRun.objects.filter(pk=first.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    second = _claim_cycle(session_date)
    assert second is not None

    assert _finish_cycle(first, error="stale worker") is False
    assert _finish_cycle(second) is True
    second.refresh_from_db()
    assert second.status == PaperCycleRun.Status.SUCCEEDED
    assert second.error == ""
    assert second.attempt_count == 2


@pytest.mark.django_db
def test_active_account_moves_to_latest_version_of_same_strategy(user):
    current = seed_strategy_catalog()[0]
    current.active = False
    current.save(update_fields=["active"])
    replacement = type(current).objects.create(
        slug=current.slug,
        name=current.name,
        version="99.0.0",
        description=current.description,
        code_hash="replacement",
        active=True,
        locked=True,
    )
    account = PaperAccount.objects.create(
        user=user,
        strategy_version=current,
        mode=PaperAccount.Mode.MANUAL,
    )

    accounts = _active_accounts_for_session(timezone.localdate())

    account.refresh_from_db()
    assert accounts[0].id == account.id
    assert account.strategy_version == replacement


@pytest.mark.django_db
def test_non_session_dividend_is_caught_up_with_actual_payment_date(user):
    instruments = {item.symbol: item for item in seed_instruments()}
    account = PaperAccount.objects.create(user=user, strategy_version=seed_strategy_catalog()[0])
    Position.objects.create(
        account=account,
        instrument=instruments["510300"],
        shares=1000,
        average_cost=Decimal("4.000000"),
    )
    record_date = date(2025, 3, 28)
    payment_date = date(2025, 3, 30)
    HoldingSnapshot.objects.create(account=account, date=record_date, positions={"510300": 1000})
    CorporateAction.objects.create(
        instrument=instruments["510300"],
        batch=completed_batch(expected=date(2025, 3, 31)),
        kind=CorporateAction.Kind.CASH_DIVIDEND,
        record_date=record_date,
        effective_date=record_date,
        payment_date=payment_date,
        value=Decimal("0.10000000"),
    )

    apply_actions_between(account, date(2025, 3, 28), date(2025, 3, 31))
    entry = LedgerEntry.objects.get(account=account, kind=LedgerEntry.Kind.DIVIDEND)
    assert entry.occurred_on == payment_date
    assert entry.amount == Decimal("100.00")


@pytest.mark.django_db
def test_backtest_lease_prevents_stale_worker_from_overwriting_result(user):
    run = create_backtest_run(user)
    first = _claim_backtest(str(run.id))
    assert first is not None
    _, old_token = first
    BacktestRun.objects.filter(pk=run.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    second = _claim_backtest(str(run.id))
    assert second is not None
    _, current_token = second

    assert _finish_backtest(str(run.id), old_token, result={"worker": "old"}) is False
    assert _finish_backtest(str(run.id), current_token, result={"worker": "current"}) is True
    run.refresh_from_db()
    assert run.status == BacktestRun.Status.SUCCEEDED
    assert run.result == {"worker": "current"}
    assert run.attempt_count == 2


@pytest.mark.django_db
def test_backtest_task_succeeds_and_recovery_stops_after_limit(user, monkeypatch):
    successful = create_backtest_run(user)
    monkeypatch.setattr("apps.backtests.tasks.execute_backtest", lambda run: {"run": str(run.id)})
    run_backtest(str(successful.id))
    successful.refresh_from_db()
    assert successful.status == BacktestRun.Status.SUCCEEDED
    assert successful.attempt_count == 1

    exhausted = create_backtest_run(user)
    exhausted.status = BacktestRun.Status.RUNNING
    exhausted.attempt_count = MAX_ATTEMPTS
    exhausted.lease_token = "dead-worker"
    exhausted.lease_expires_at = timezone.now() - timedelta(seconds=1)
    exhausted.save(update_fields=["status", "attempt_count", "lease_token", "lease_expires_at"])
    result = recover_backtest_runs()
    exhausted.refresh_from_db()
    assert result["failed"] == 1
    assert exhausted.status == BacktestRun.Status.FAILED
    assert "恢复上限" in exhausted.error


@pytest.mark.django_db
def test_backtest_recovery_requeues_legacy_running_record_without_lease(user, monkeypatch):
    legacy = create_backtest_run(user)
    legacy.status = BacktestRun.Status.RUNNING
    legacy.attempt_count = None
    legacy.lease_token = None
    legacy.lease_expires_at = None
    legacy.save(update_fields=["status", "attempt_count", "lease_token", "lease_expires_at"])
    monkeypatch.setattr(
        "apps.backtests.tasks.run_backtest.delay",
        lambda run_id: SimpleNamespace(id=f"recovered-{run_id}"),
    )

    result = recover_backtest_runs()

    legacy.refresh_from_db()
    assert result == {"dispatched": 1, "failed": 0}
    assert legacy.status == BacktestRun.Status.QUEUED
    assert legacy.task_id == f"recovered-{legacy.id}"


@pytest.mark.django_db
def test_market_and_paper_tasks_report_blocking_failure_and_success(monkeypatch):
    expected = date(2025, 3, 31)
    interrupted = MarketDataBatch.objects.create(
        status=MarketDataBatch.Status.RUNNING,
        expected_session=expected,
        triggered_by="interrupted-worker",
    )
    healthy = completed_batch(expected=expected)
    monkeypatch.setattr("apps.market.tasks.import_market_data", lambda **kwargs: healthy)
    assert update_market_data() == str(healthy.id)
    interrupted.refresh_from_db()
    assert interrupted.status == MarketDataBatch.Status.FAILED
    assert interrupted.finished_at is not None
    assert interrupted.errors[0]["source"] == "recovery"

    monkeypatch.setattr(
        "apps.paper.tasks.current_data_status",
        lambda: {"ready": True, "expected_session": expected},
    )
    monkeypatch.setattr(
        "apps.paper.tasks.reconcile_paper_through",
        lambda target: {"status": "ok", "processed_through": target.isoformat()},
    )
    assert reconcile_paper_cycles()["status"] == "ok"
    assert run_daily_paper_cycle(str(healthy.id))["status"] == "ok"

    cache.set("lock:paper-reconcile", "other-worker", timeout=60)
    assert reconcile_paper_cycles()["status"] == "busy"
    cache.delete("lock:paper-reconcile")
    blocked = completed_batch(expected=expected, status="failed")
    assert run_daily_paper_cycle(str(blocked.id))["status"] == "blocked"

    def fail_import(**kwargs):
        MarketDataBatch.objects.create(
            status=MarketDataBatch.Status.RUNNING,
            expected_session=expected,
            triggered_by=kwargs["triggered_by"],
        )
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("apps.market.tasks.import_market_data", fail_import)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        update_market_data(triggered_by="failure-test")
