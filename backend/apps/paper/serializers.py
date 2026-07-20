from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.market.calendar import next_session

from .models import (
    AdviceSnapshot,
    Fill,
    LedgerEntry,
    NavSnapshot,
    Order,
    PaperAccount,
    PaperCycleRun,
    PaperRebalance,
    Position,
    PositionLot,
)


class PositionSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument_id")
    name = serializers.CharField(source="instrument.name", read_only=True)
    settlement_cycle = serializers.CharField(source="instrument.settlement_cycle", read_only=True)
    sellable_shares = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "symbol",
            "name",
            "settlement_cycle",
            "shares",
            "sellable_shares",
            "average_cost",
            "updated_at",
        ]

    def get_sellable_shares(self, obj):
        return (
            PositionLot.objects.filter(
                account=obj.account,
                instrument=obj.instrument,
                remaining_shares__gt=0,
                available_on__lte=next_session(timezone.localdate()),
            ).aggregate(value=Sum("remaining_shares"))["value"]
            or 0
        )


class FillSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(read_only=True)
    symbol = serializers.CharField(source="order.instrument_id", read_only=True)
    side = serializers.CharField(source="order.side", read_only=True)
    shares = serializers.IntegerField(source="order.shares", read_only=True)

    class Meta:
        model = Fill
        fields = [
            "id",
            "order_id",
            "symbol",
            "side",
            "shares",
            "price",
            "fee",
            "filled_on",
            "estimated",
            "created_at",
        ]


class OrderSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument_id")
    name = serializers.CharField(source="instrument.name", read_only=True)
    fill = FillSerializer(read_only=True)
    cancellable = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "symbol",
            "name",
            "side",
            "shares",
            "origin",
            "eligible_on",
            "expires_on",
            "reserved_cash",
            "status",
            "rejection_reason",
            "cancellable",
            "fill",
            "created_at",
            "cancelled_at",
        ]

    def get_cancellable(self, obj):
        return obj.origin == Order.Origin.USER and obj.status == Order.Status.PENDING


class UserOrderCreateSerializer(serializers.Serializer):
    instrument = serializers.RegexField(r"^\d{6}$")
    side = serializers.ChoiceField(choices=["buy", "sell"])
    shares = serializers.IntegerField(min_value=1)
    client_request_id = serializers.CharField(min_length=8, max_length=64)


class RebalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaperRebalance
        fields = ["id", "eligible_on", "target_weights", "source", "status", "error", "created_at"]


class LedgerSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument_id", allow_null=True)

    class Meta:
        model = LedgerEntry
        fields = ["id", "kind", "symbol", "amount", "quantity", "occurred_on", "detail", "created_at"]


class NavSerializer(serializers.ModelSerializer):
    class Meta:
        model = NavSnapshot
        fields = ["date", "value", "cash"]


class PaperAccountListSerializer(serializers.ModelSerializer):
    strategy_id = serializers.UUIDField(source="strategy_version_id", allow_null=True)
    strategy_name = serializers.CharField(source="strategy_version.name", allow_null=True)
    strategy_slug = serializers.CharField(source="strategy_version.slug", allow_null=True)
    latest_nav = serializers.SerializerMethodField()
    account_number = serializers.SerializerMethodField()

    class Meta:
        model = PaperAccount
        fields = [
            "id",
            "account_number",
            "mode",
            "risk_level",
            "strategy_id",
            "strategy_name",
            "strategy_slug",
            "generation",
            "status",
            "initial_capital",
            "cash",
            "latest_nav",
            "created_at",
            "archived_at",
        ]

    def get_latest_nav(self, obj):
        latest = obj.nav_snapshots.last()
        return NavSerializer(latest).data if latest else None

    def get_account_number(self, obj):
        return str(obj.id).split("-")[0]


class PaperAccountDetailSerializer(PaperAccountListSerializer):
    positions = PositionSerializer(many=True, read_only=True)
    pending_orders = serializers.SerializerMethodField()

    class Meta(PaperAccountListSerializer.Meta):
        fields = PaperAccountListSerializer.Meta.fields + ["positions", "pending_orders"]

    def get_pending_orders(self, obj):
        items = obj.orders.filter(status=Order.Status.PENDING).select_related("instrument")
        return OrderSerializer(items, many=True).data


class AccountPreferenceSerializer(serializers.Serializer):
    strategy_version_id = serializers.UUIDField(required=False)
    risk_level = serializers.ChoiceField(choices=PaperAccount.RiskLevel.choices, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("至少提供一项设置")
        return attrs


class AdviceSnapshotSerializer(serializers.ModelSerializer):
    strategy_name = serializers.CharField(source="strategy_version.name", read_only=True)
    strategy_slug = serializers.CharField(source="strategy_version.slug", read_only=True)

    class Meta:
        model = AdviceSnapshot
        fields = [
            "id",
            "strategy_name",
            "strategy_slug",
            "session_date",
            "expires_on",
            "status",
            "risk_level",
            "target_weights",
            "recommendations",
            "input_summary",
            "created_at",
        ]


class PaperCycleRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaperCycleRun
        fields = ["id", "session_date", "status", "attempt_count", "started_at", "finished_at", "error"]
        read_only_fields = fields
