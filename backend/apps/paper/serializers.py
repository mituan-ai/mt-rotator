from rest_framework import serializers

from .models import Fill, LedgerEntry, NavSnapshot, Order, PaperAccount, PaperRebalance, Position


class PositionSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument_id")
    name = serializers.CharField(source="instrument.name", read_only=True)

    class Meta:
        model = Position
        fields = ["symbol", "name", "shares", "average_cost", "updated_at"]


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
    fill = FillSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "symbol",
            "side",
            "shares",
            "eligible_on",
            "status",
            "rejection_reason",
            "fill",
            "created_at",
        ]


class RebalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaperRebalance
        fields = [
            "id",
            "eligible_on",
            "target_weights",
            "source",
            "status",
            "error",
            "created_at",
            "processed_at",
        ]


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
    strategy_id = serializers.UUIDField(source="strategy_version_id")
    strategy_name = serializers.CharField(source="strategy_version.name")
    strategy_slug = serializers.CharField(source="strategy_version.slug")
    latest_nav = serializers.SerializerMethodField()

    class Meta:
        model = PaperAccount
        fields = [
            "id",
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


class PaperAccountDetailSerializer(PaperAccountListSerializer):
    positions = PositionSerializer(many=True, read_only=True)
    pending_rebalances = serializers.SerializerMethodField()

    class Meta(PaperAccountListSerializer.Meta):
        fields = PaperAccountListSerializer.Meta.fields + ["positions", "pending_rebalances"]

    def get_pending_rebalances(self, obj):
        items = obj.rebalances.filter(status=PaperRebalance.Status.PENDING)
        return RebalanceSerializer(items, many=True).data


class AccountActivateSerializer(serializers.Serializer):
    strategy_version_id = serializers.UUIDField()
