from rest_framework import serializers

from .models import BacktestRun


class BacktestCreateSerializer(serializers.Serializer):
    strategy_version_id = serializers.UUIDField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class BacktestRunSerializer(serializers.ModelSerializer):
    strategy_name = serializers.CharField(source="strategy_version.name", read_only=True)
    strategy_slug = serializers.CharField(source="strategy_version.slug", read_only=True)
    data_snapshot = serializers.SerializerMethodField()

    class Meta:
        model = BacktestRun
        fields = [
            "id",
            "strategy_name",
            "strategy_slug",
            "start_date",
            "end_date",
            "initial_capital",
            "status",
            "result",
            "error",
            "data_snapshot",
            "created_at",
            "started_at",
            "finished_at",
        ]

    def get_data_snapshot(self, obj):
        return {
            "id": obj.snapshot_id,
            "cutoff_date": obj.snapshot.cutoff_date,
            "provider": obj.snapshot.provider,
            "digest": obj.snapshot.digest,
        }


class BacktestListSerializer(BacktestRunSerializer):
    class Meta(BacktestRunSerializer.Meta):
        fields = [field for field in BacktestRunSerializer.Meta.fields if field != "result"]
