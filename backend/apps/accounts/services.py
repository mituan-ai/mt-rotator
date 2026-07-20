from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import record_audit

from .models import Invitation, User, normalize_email_address


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreatedInvitation:
    invitation: Invitation
    token: str
    link: str


def create_invitation(*, email: str, created_by: User, note: str = "", days: int = 7) -> CreatedInvitation:
    normalized = normalize_email_address(email)
    validate_email(normalized)
    if User.objects.filter(email=normalized).exists():
        raise ValidationError("该邮箱已经注册")
    if Invitation.objects.filter(
        email=normalized,
        revoked_at__isnull=True,
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists():
        raise ValidationError("该邮箱已有有效邀请，请撤销或重新签发")
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        email=normalized,
        token_hash=token_digest(token),
        note=note.strip(),
        expires_at=timezone.now() + timedelta(days=days),
        created_by=created_by,
    )
    link = f"{settings.PUBLIC_BASE_URL}/register#token={token}"
    return CreatedInvitation(invitation=invitation, token=token, link=link)


def inspect_invitation(token: str) -> Invitation:
    try:
        invitation = Invitation.objects.get(token_hash=token_digest(token))
    except Invitation.DoesNotExist as exc:
        raise ValidationError("邀请无效") from exc
    if invitation.state != "active":
        raise ValidationError(f"邀请不可用：{invitation.state}")
    return invitation


@transaction.atomic
def register_with_invitation(
    *, token: str, email: str, display_name: str, password: str, request=None
) -> User:
    try:
        invitation = Invitation.objects.select_for_update().get(token_hash=token_digest(token))
    except Invitation.DoesNotExist as exc:
        raise ValidationError("邀请无效") from exc
    if invitation.state != "active":
        raise ValidationError("邀请已使用、过期或撤销")
    normalized = normalize_email_address(email)
    if normalized != invitation.email:
        raise ValidationError("邮箱与邀请不一致")
    candidate = User(email=normalized, display_name=display_name.strip())
    validate_password(password, candidate)
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=normalized,
                password=password,
                display_name=display_name.strip(),
            )
    except IntegrityError as exc:
        raise ValidationError("该邮箱已经注册") from exc
    now = timezone.now()
    invitation.used_at = now
    invitation.used_by = user
    invitation.save(update_fields=["used_at", "used_by"])
    record_audit("auth.register", actor=user, target=user, request=request)
    return user


@transaction.atomic
def revoke_invitation(invitation: Invitation) -> Invitation:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.state != "active":
        raise ValidationError("只有有效邀请可以撤销")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    return invitation


@transaction.atomic
def reissue_invitation(invitation: Invitation, *, created_by: User) -> CreatedInvitation:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.state == "active":
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at"])
    if User.objects.filter(email=invitation.email).exists():
        raise ValidationError("该邮箱已经注册")
    return create_invitation(email=invitation.email, created_by=created_by, note=invitation.note)
