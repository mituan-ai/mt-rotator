from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", allow_null=True, read_only=True)

    class Meta:
        model = AuditEvent
        fields = ["id", "actor_email", "event_type", "target_type", "target_id", "detail", "created_at"]
