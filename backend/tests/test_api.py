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
    assert client.get("/api/v1/paper/accounts").data["count"] == 0
