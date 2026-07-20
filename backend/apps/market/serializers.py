from rest_framework import serializers

from .models import Instrument, MarketBar, MarketDataBatch


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ["symbol", "name", "exchange", "lot_size", "listed_on"]


class MarketBarSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="trade_date")

    class Meta:
        model = MarketBar
        fields = ["date", "open", "high", "low", "close", "volume"]


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
