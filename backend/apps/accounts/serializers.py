from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Invitation, User, normalize_email_address


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "is_staff", "is_active", "date_joined"]
        read_only_fields = fields


class InvitationSerializer(serializers.ModelSerializer):
    state = serializers.CharField(read_only=True)
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "note",
            "expires_at",
            "state",
            "created_by_email",
            "created_at",
            "used_at",
            "revoked_at",
        ]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)

    def validate_email(self, value: str) -> str:
        return normalize_email_address(value)


class RegisterSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200)
    email = serializers.EmailField()
    display_name = serializers.CharField(min_length=2, max_length=24)
    password = serializers.CharField(min_length=12, max_length=128, trim_whitespace=False)

    def validate_email(self, value: str) -> str:
        return normalize_email_address(value)

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value


class InviteInspectSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200)


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    note = serializers.CharField(max_length=240, allow_blank=True, required=False)
    days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(min_length=12, max_length=128, trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        validate_password(value, self.context["request"].user)
        return value
