from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.accounts.models import Invitation, User
from apps.accounts.services import create_invitation, inspect_invitation, register_with_invitation


@pytest.mark.django_db
def test_invitation_is_hashed_single_use_and_email_bound(admin_user):
    created = create_invitation(email="Invited@Example.com", created_by=admin_user)
    assert created.token not in created.invitation.token_hash
    assert "#token=" in created.link
    assert inspect_invitation(created.token).email == "invited@example.com"

    with pytest.raises(ValidationError, match="邮箱与邀请不一致"):
        register_with_invitation(
            token=created.token,
            email="wrong@example.com",
            display_name="错误用户",
            password="Correct-Horse-Battery-Staple-2026",
        )

    user = register_with_invitation(
        token=created.token,
        email="INVITED@example.com",
        display_name="受邀用户",
        password="Correct-Horse-Battery-Staple-2026",
    )
    assert user.email == "invited@example.com"
    assert Invitation.objects.get(pk=created.invitation.pk).used_by == user
    with pytest.raises(ValidationError, match="邀请已使用"):
        register_with_invitation(
            token=created.token,
            email="invited@example.com",
            display_name="第二用户",
            password="Correct-Horse-Battery-Staple-2026",
        )


@pytest.mark.django_db
def test_user_email_is_case_insensitive_unique(admin_user):
    with pytest.raises(IntegrityError):
        User.objects.create_user(
            email="ADMIN@EXAMPLE.COM",
            password="Correct-Horse-Battery-Staple-2026",
            display_name="重复",
        )
