from rest_framework import serializers

from .models import Signal, StrategyVersion


class StrategyVersionSerializer(serializers.ModelSerializer):
    latest_signal = serializers.SerializerMethodField()

    class Meta:
        model = StrategyVersion
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "version",
            "parameters",
            "risk_symbols",
            "defensive_weights",
            "active",
            "published_at",
            "latest_signal",
        ]

    def get_latest_signal(self, obj):
        signal = obj.signals.select_related("snapshot", "strategy_version").first()
        return SignalSerializer(signal).data if signal else None


class SignalSerializer(serializers.ModelSerializer):
    strategy_slug = serializers.CharField(source="strategy_version.slug", read_only=True)
    strategy_name = serializers.CharField(source="strategy_version.name", read_only=True)
    data_source = serializers.SerializerMethodField()

    class Meta:
        model = Signal
        fields = [
            "id",
            "strategy_slug",
            "strategy_name",
            "signal_date",
            "tradable_on",
            "target_weights",
            "rationale",
            "data_source",
            "created_at",
        ]

    def get_data_source(self, obj):
        return {
            "provider": obj.snapshot.provider,
            "cutoff_date": obj.snapshot.cutoff_date,
            "adjustment": "dividend_adjusted_total_return",
        }
