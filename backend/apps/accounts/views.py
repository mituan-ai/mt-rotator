from __future__ import annotations

import csv
import io

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import record_audit
from apps.core.pagination import DefaultPagination
from apps.core.permissions import IsAdministrator

from .models import Invitation, User
from .serializers import (
    InvitationCreateSerializer,
    InvitationSerializer,
    InviteInspectSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .services import (
    create_invitation,
    inspect_invitation,
    register_with_invitation,
    reissue_invitation,
    revoke_invitation,
)


def _as_api_validation(exc: DjangoValidationError) -> ValidationError:
    return ValidationError(exc.messages if hasattr(exc, "messages") else str(exc))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


class InviteInspectView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "invite_inspect"

    def post(self, request):
        serializer = InviteInspectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invitation = inspect_invitation(serializer.validated_data["token"])
        except DjangoValidationError as exc:
            raise _as_api_validation(exc) from exc
        return Response({"email": invitation.email, "expires_at": invitation.expires_at})


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "register"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            user = register_with_invitation(request=request, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _as_api_validation(exc) from exc
        login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if not user:
            record_audit(
                "auth.login_failed", request=request, detail={"email": serializer.validated_data["email"]}
            )
            raise AuthenticationFailed("邮箱或密码错误")
        if not user.is_active:
            raise AuthenticationFailed("账户已停用")
        login(request, user)
        record_audit("auth.login", actor=user, target=user, request=request)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    def post(self, request):
        record_audit("auth.logout", actor=request.user, target=request.user, request=request)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class PasswordChangeView(APIView):
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["current_password"]):
            raise ValidationError({"current_password": ["当前密码错误"]})
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        record_audit("auth.password_changed", actor=request.user, target=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationListCreateView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def get(self, request):
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(Invitation.objects.select_related("created_by").all(), request)
        return paginator.get_paginated_response(InvitationSerializer(page, many=True).data)

    def post(self, request):
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_invitation(created_by=request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise _as_api_validation(exc) from exc
        record_audit(
            "admin.invitation_created", actor=request.user, target=result.invitation, request=request
        )
        return Response(
            {**InvitationSerializer(result.invitation).data, "link": result.link},
            status=status.HTTP_201_CREATED,
        )


class InvitationImportView(APIView):
    permission_classes = [IsAdministrator]
    parser_classes = [MultiPartParser]
    throttle_scope = "admin_write"

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": ["请选择CSV文件"]})
        if upload.size > 512_000:
            raise ValidationError({"file": ["CSV不能超过500 KB"]})
        try:
            text = upload.read().decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValidationError({"file": ["CSV格式无效"]}) from exc
        created, errors = [], []
        for index, row in enumerate(rows, start=2):
            try:
                result = create_invitation(
                    email=row.get("email", ""),
                    note=row.get("note", ""),
                    created_by=request.user,
                )
                created.append({**InvitationSerializer(result.invitation).data, "link": result.link})
            except Exception as exc:
                errors.append({"row": index, "error": str(exc)})
        record_audit(
            "admin.invitations_imported",
            actor=request.user,
            request=request,
            detail={"created": len(created)},
        )
        return Response({"created": created, "errors": errors}, status=status.HTTP_201_CREATED)


class InvitationRevokeView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def post(self, request, invitation_id):
        invitation = Invitation.objects.get(pk=invitation_id)
        try:
            invitation = revoke_invitation(invitation)
        except DjangoValidationError as exc:
            raise _as_api_validation(exc) from exc
        record_audit("admin.invitation_revoked", actor=request.user, target=invitation, request=request)
        return Response(InvitationSerializer(invitation).data)


class InvitationReissueView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def post(self, request, invitation_id):
        invitation = Invitation.objects.get(pk=invitation_id)
        try:
            result = reissue_invitation(invitation, created_by=request.user)
        except DjangoValidationError as exc:
            raise _as_api_validation(exc) from exc
        record_audit(
            "admin.invitation_reissued",
            actor=request.user,
            target=result.invitation,
            request=request,
            detail={"previous_invitation_id": str(invitation.id)},
        )
        return Response(
            {**InvitationSerializer(result.invitation).data, "link": result.link},
            status=status.HTTP_201_CREATED,
        )


class UserListView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(User.objects.all().order_by("-date_joined"), request)
        return paginator.get_paginated_response(UserSerializer(page, many=True).data)


class UserStatusView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def patch(self, request, user_id):
        user = User.objects.get(pk=user_id)
        if user == request.user and request.data.get("is_active") is False:
            raise ValidationError("不能停用当前管理员")
        if not isinstance(request.data.get("is_active"), bool):
            raise ValidationError({"is_active": ["必须为布尔值"]})
        user.is_active = request.data["is_active"]
        user.save(update_fields=["is_active"])
        if not user.is_active:
            _delete_user_sessions(user)
        record_audit(
            "admin.user_status_changed",
            actor=request.user,
            target=user,
            request=request,
            detail={"is_active": user.is_active},
        )
        return Response(UserSerializer(user).data)


class UserRevokeSessionsView(APIView):
    permission_classes = [IsAdministrator]
    throttle_scope = "admin_write"

    def post(self, request, user_id):
        user = User.objects.get(pk=user_id)
        count = _delete_user_sessions(user)
        record_audit(
            "admin.user_sessions_revoked",
            actor=request.user,
            target=user,
            request=request,
            detail={"count": count},
        )
        return Response({"revoked": count})


def _delete_user_sessions(user: User) -> int:
    count = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
            session.delete()
            count += 1
    return count
