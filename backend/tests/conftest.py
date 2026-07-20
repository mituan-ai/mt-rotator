from __future__ import annotations

import os

import pytest

os.environ.setdefault("MT_TESTING", "1")


@pytest.fixture
def admin_user(db):
    from apps.accounts.models import User

    return User.objects.create_superuser(
        email="admin@example.com",
        password="Correct-Horse-Battery-Staple-2026",
        display_name="管理员",
    )


@pytest.fixture
def user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="user@example.com",
        password="Correct-Horse-Battery-Staple-2026",
        display_name="用户",
    )
