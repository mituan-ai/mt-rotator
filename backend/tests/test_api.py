from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.services import create_invitation


@pytest.mark.django_db
def test_invitation_registration_and_admin_permissions(admin_user, user):
    admin_client = APIClient()
    admin_client.force_authenticate(admin_user)
    response = admin_client.post(
        "/api/v1/auth/admin/invitations",
        {"email": "new@example.com", "note": "首批用户", "days": 7},
        format="json",
    )
    assert response.status_code == 201
    assert "#token=" in response.data["link"]
    token = response.data["link"].split("#token=", 1)[1]

    anonymous = APIClient()
    inspect_response = anonymous.post("/api/v1/auth/invitations/inspect", {"token": token}, format="json")
    assert inspect_response.status_code == 200
    assert inspect_response.data["email"] == "new@example.com"
    register_response = anonymous.post(
        "/api/v1/auth/register",
        {
            "token": token,
            "email": "NEW@example.com",
            "display_name": "新用户",
            "password": "Correct-Horse-Battery-Staple-2026",
        },
        format="json",
    )
    assert register_response.status_code == 201
    assert register_response.data["email"] == "new@example.com"

    normal_client = APIClient()
    normal_client.force_authenticate(user)
    denied = normal_client.get("/api/v1/auth/admin/users")
    assert denied.status_code == 403
    assert denied["Content-Type"].startswith("application/problem+json")


@pytest.mark.django_db
def test_reissuing_invitation_invalidates_previous_token(admin_user):
    created = create_invitation(email="reissue@example.com", created_by=admin_user)
    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(f"/api/v1/auth/admin/invitations/{created.invitation.id}/reissue")
    assert response.status_code == 201
    new_token = response.data["link"].split("#token=", 1)[1]

    anonymous = APIClient()
    assert (
        anonymous.post(
            "/api/v1/auth/invitations/inspect", {"token": created.token}, format="json"
        ).status_code
        == 400
    )
    assert (
        anonymous.post("/api/v1/auth/invitations/inspect", {"token": new_token}, format="json").status_code
        == 200
    )


@pytest.mark.django_db
def test_strategy_catalog_is_paginated_and_requires_authentication(user):
    from apps.market.services import seed_instruments
    from apps.strategies.services import seed_strategy_catalog

    seed_instruments()
    seed_strategy_catalog()
    anonymous = APIClient()
    assert anonymous.get("/api/v1/strategies/").status_code in {401, 403}

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/v1/strategies/")
    assert response.status_code == 200
    assert response.data["count"] == 3
    assert len(response.data["results"]) == 3


@pytest.mark.django_db
def test_user_objects_are_isolated_by_owner(user):
    from datetime import date

    from apps.accounts.models import User
    from apps.backtests.models import BacktestRun
    from apps.market.models import DatasetSnapshot
    from apps.market.services import seed_instruments
    from apps.paper.models import PaperAccount
    from apps.strategies.services import seed_strategy_catalog

    other = User.objects.create_user(
        email="other@example.com",
        password="Correct-Horse-Battery-Staple-2026",
        display_name="其他用户",
    )
    seed_instruments()
    strategy = seed_strategy_catalog()[0]
    snapshot = DatasetSnapshot.objects.create(
        cutoff_date=date(2025, 3, 31),
        digest="a" * 64,
        provider="test",
    )
    run = BacktestRun.objects.create(
        user=other,
        strategy_version=strategy,
        snapshot=snapshot,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 3, 31),
        input_hash="b" * 64,
    )
    account = PaperAccount.objects.create(user=other, strategy_version=strategy)

    client = APIClient()
    client.force_authenticate(user)
    assert client.get(f"/api/v1/backtests/{run.id}").status_code == 404
    assert client.get(f"/api/v1/paper/accounts/{account.id}").status_code == 404
    assert client.get("/api/v1/backtests/").data["count"] == 0
    accounts = client.get("/api/v1/paper/accounts").data
    assert accounts["count"] == 1
    assert accounts["results"][0]["mode"] == "manual"


@pytest.mark.django_db
def test_paper_cycle_admin_api_is_observable_and_protected(admin_user, user):
    from datetime import date

    from apps.paper.models import PaperCycleRun

    PaperCycleRun.objects.create(
        session_date=date(2025, 3, 31),
        status=PaperCycleRun.Status.SUCCEEDED,
        attempt_count=1,
    )
    member = APIClient()
    member.force_authenticate(user)
    assert member.get("/api/v1/paper/admin/cycles").status_code == 403
    assert member.post("/api/v1/paper/admin/reconcile").status_code == 403

    admin = APIClient()
    admin.force_authenticate(admin_user)
    response = admin.get("/api/v1/paper/admin/cycles")
    assert response.status_code == 200
    assert response.data["results"][0]["session_date"] == "2025-03-31"
    assert admin.post("/api/v1/paper/admin/reconcile").status_code == 202


@pytest.mark.django_db
def test_manual_order_api_is_idempotent_owned_and_cancellable(user, monkeypatch):
    from datetime import date

    from apps.market.calendar import next_session
    from apps.paper.models import Order
    from tests.factories import seed_ready_day

    submitted_on = date(2025, 3, 28)
    seed_ready_day(submitted_on)
    monkeypatch.setattr("apps.paper.services.timezone.localdate", lambda *args: submitted_on)
    client = APIClient()
    client.force_authenticate(user)
    account = client.get("/api/v1/paper/accounts").data["results"][0]
    payload = {
        "instrument": "510300",
        "side": "buy",
        "shares": 100,
        "client_request_id": "browser-request-0001",
    }

    created = client.post(f"/api/v1/paper/accounts/{account['id']}/orders", payload, format="json")
    repeated = client.post(f"/api/v1/paper/accounts/{account['id']}/orders", payload, format="json")
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == created.data["id"]
    assert created.data["eligible_on"] == next_session(submitted_on).isoformat()
    assert Order.objects.count() == 1

    cancelled = client.post(f"/api/v1/paper/accounts/{account['id']}/orders/{created.data['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "cancelled"

    other = APIClient()
    other.force_authenticate(
        user.__class__.objects.create_user(
            email="order-owner@example.com",
            password="Correct-Horse-Battery-Staple-2026",
            display_name="订单隔离用户",
        )
    )
    assert other.get(f"/api/v1/paper/accounts/{account['id']}/orders").status_code == 404


@pytest.mark.django_db
def test_current_advice_matches_selected_strategy_and_risk(user):
    from datetime import date

    from apps.market.calendar import next_session
    from apps.paper.models import AdviceSnapshot, PaperAccount
    from apps.paper.services import ensure_manual_account
    from apps.strategies.services import seed_strategy_catalog

    selected, other, *_ = seed_strategy_catalog()
    account = ensure_manual_account(user)
    account.strategy_version = selected
    account.risk_level = PaperAccount.RiskLevel.BALANCED
    account.save(update_fields=["strategy_version", "risk_level"])
    selected_date = date(2025, 3, 28)
    AdviceSnapshot.objects.create(
        account=account,
        strategy_version=selected,
        session_date=selected_date,
        expires_on=next_session(selected_date),
        risk_level=PaperAccount.RiskLevel.BALANCED,
    )
    AdviceSnapshot.objects.create(
        account=account,
        strategy_version=other,
        session_date=date(2025, 3, 31),
        expires_on=date(2025, 4, 1),
        risk_level=PaperAccount.RiskLevel.BALANCED,
    )
    client = APIClient()
    client.force_authenticate(user)

    current = client.get(f"/api/v1/paper/accounts/{account.id}/advice/current")
    assert current.status_code == 200
    assert current.data["strategy_slug"] == selected.slug
    assert current.data["session_date"] == selected_date.isoformat()

    account.risk_level = PaperAccount.RiskLevel.AGGRESSIVE
    account.save(update_fields=["risk_level"])
    assert client.get(f"/api/v1/paper/accounts/{account.id}/advice/current").status_code == 404
