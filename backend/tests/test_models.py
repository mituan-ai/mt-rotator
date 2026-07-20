from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.market.services import seed_instruments
from apps.strategies.services import seed_strategy_catalog


@pytest.mark.django_db
def test_published_strategy_is_immutable():
    seed_instruments()
    version = seed_strategy_catalog()[0]
    version.parameters = {"changed": True}
    with pytest.raises(ValidationError, match="不可修改"):
        version.save()


@pytest.mark.django_db
def test_account_restart_archives_instead_of_deleting(user, monkeypatch):
    from apps.paper.models import LedgerEntry, PaperAccount
    from apps.paper.services import activate_account, restart_account
    from apps.strategies.services import seed_strategy_catalog

    seed_instruments()
    strategy = seed_strategy_catalog()[0]
    monkeypatch.setattr(
        "apps.paper.services.current_data_status",
        lambda: {"ready": False, "expected_session": None},
    )
    first = activate_account(user=user, strategy=strategy)
    second = restart_account(first)
    first.refresh_from_db()
    assert first.status == PaperAccount.Status.ARCHIVED
    assert second.generation == 2
    assert LedgerEntry.objects.filter(account=first, kind=LedgerEntry.Kind.DEPOSIT).count() == 1
    assert LedgerEntry.objects.filter(account=second, kind=LedgerEntry.Kind.DEPOSIT).count() == 1
