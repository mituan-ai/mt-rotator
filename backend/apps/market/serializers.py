from rest_framework import serializers

from .models import Instrument, MarketBar, MarketDataBatch


class InstrumentSerializer(serializers.ModelSerializer):
    latest_close = serializers.SerializerMethodField()

    class Meta:
        model = Instrument
        fields = [
            "symbol",
            "name",
            "exchange",
            "asset_class",
            "settlement_cycle",
            "lot_size",
            "listed_on",
            "enabled",
            "catalog_active",
            "data_status",
            "data_error",
            "last_bar_date",
            "average_amount_20d",
            "trade_eligible",
            "advice_eligible",
            "latest_close",
        ]

    def get_latest_close(self, obj):
        bar = (
            obj.bars.filter(
                adjustment=MarketBar.Adjustment.RAW,
                is_current=True,
                batch__finished_at__isnull=False,
            )
            .order_by("-trade_date")
            .first()
        )
        return str(bar.close) if bar else None


class MarketBarSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="trade_date")

    class Meta:
        model = MarketBar
        fields = ["date", "open", "high", "low", "close", "volume", "amount"]


class MarketDataBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketDataBatch
        fields = [
            "id",
            "provider",
            "status",
            "expected_session",
            "row_count",
            "errors",
            "warnings",
            "metadata",
            "started_at",
            "finished_at",
            "triggered_by",
        ]
