from __future__ import annotations

import io
import zipfile
from datetime import date
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.backtests.models import BacktestRun
from apps.paper.models import PaperCycleRun
from tests.factories import create_backtest_run, seed_ready_day


@pytest.mark.django_db
def test_backtest_api_lifecycle_and_exports(user, monkeypatch):
    run = create_backtest_run(user)
    client = APIClient()
    client.force_authenticate(user)
    monkeypatch.setattr("apps.backtests.views.create_backtest", lambda **kwargs: run)
    monkeypatch.setattr(
        "apps.backtests.views.run_backtest.delay", lambda run_id: SimpleNamespace(id=f"task-{run_id}")
    )

    created = client.post(
        "/api/v1/backtests/",
        {
            "strategy_version_id": str(run.strategy_version_id),
            "start_date": "2024-01-01",
            "end_date": "2025-03-31",
        },
        format="json",
    )
    assert created.status_code == 202
    assert created.data["job_id"].startswith("task-")
    assert client.get("/api/v1/backtests/").data["count"] == 1
    assert client.get(f"/api/v1/backtests/{run.id}").status_code == 200

    cancelled = client.post(f"/api/v1/backtests/{run.id}/cancel")
    assert cancelled.status_code == 200
    run.status = BacktestRun.Status.SUCCEEDED
    run.result = {
        "metrics": {"return": 0.1},
        "nav": [{"date": "2025-03-31", "value": 110000}],
        "holdings": [],
        "trades": [{"symbol": "510300", "shares": 100}],
        "allocations": [],
        "rejected_orders": [],
    }
    run.save(update_fields=["status", "result"])
    exported_json = client.get(f"/api/v1/backtests/{run.id}/export?format=json")
    assert exported_json.status_code == 200
    exported_csv = client.get(f"/api/v1/backtests/{run.id}/export?format=csv")
    assert exported_csv.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported_csv.content)) as archive:
        assert {"metrics.json", "nav.csv", "trades.csv"}.issubset(archive.namelist())
    assert client.get(f"/api/v1/backtests/{run.id}/export?format=xml").status_code == 400


@pytest.mark.django_db
def test_health_market_and_paper_cycle_admin_endpoints(admin_user, monkeypatch):
    expected = date(2025, 3, 31)
    batch = seed_ready_day(expected)
    PaperCycleRun.objects.create(
        session_date=expected,
        status=PaperCycleRun.Status.SUCCEEDED,
        attempt_count=1,
    )
    monkeypatch.setattr("apps.market.services.latest_expected_session", lambda: expected)
    client = APIClient()
    client.force_authenticate(admin_user)

    assert APIClient().get("/api/v1/health/live").status_code == 200
    assert APIClient().get("/api/v1/health/ready").status_code == 200
    freshness = APIClient().get("/api/v1/health/data")
    assert freshness.status_code == 200
    assert freshness.data["paper_status"] == "fresh"
    assert client.get("/api/v1/market/status").data["ready"] is True
    assert client.get("/api/v1/market/instruments").data["count"] == 8
    bars = client.get("/api/v1/market/instruments/510300/bars?adjustment=raw")
    assert bars.status_code == 200
    assert bars.data["bars"][0]["date"] == "2025-03-31"
    assert client.get("/api/v1/market/instruments/510300/bars?adjustment=bad").status_code == 400

    monkeypatch.setattr(
        "apps.market.views.update_market_data.delay", lambda *args: SimpleNamespace(id="market-task")
    )
    assert client.get("/api/v1/market/admin/batches").data["results"][0]["id"] == str(batch.id)
    queued = client.post("/api/v1/market/admin/batches", {"full_refresh": False}, format="json")
    assert queued.status_code == 202
    assert queued.data["job_id"] == "market-task"
    assert client.get("/api/v1/paper/admin/cycles?status=unknown").status_code == 400
