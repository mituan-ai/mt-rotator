from django.contrib import admin

from apps.core.admin_mixins import ReadOnlyAdminMixin

from .models import CorporateAction, DatasetSnapshot, Instrument, MarketBar, MarketDataBatch

admin.site.register(Instrument)


@admin.register(MarketDataBatch)
class MarketDataBatchAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("started_at", "status", "expected_session", "row_count", "triggered_by")


@admin.register(DatasetSnapshot)
class DatasetSnapshotAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "cutoff_date", "provider", "digest")


@admin.register(MarketBar)
class MarketBarAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("instrument", "trade_date", "adjustment", "close", "is_current")
    list_filter = ("adjustment", "is_current")
    search_fields = ("instrument__symbol",)


@admin.register(CorporateAction)
class CorporateActionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("instrument", "kind", "effective_date", "value", "is_current")
    list_filter = ("kind", "is_current")
