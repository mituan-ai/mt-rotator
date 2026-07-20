from rest_framework.permissions import BasePermission


class IsAdministrator(BasePermission):
    message = "仅管理员可执行此操作"

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)
