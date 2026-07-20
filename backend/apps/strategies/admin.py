from django.contrib import admin

from apps.core.admin_mixins import ReadOnlyAdminMixin

from .models import Signal, StrategyVersion


@admin.register(StrategyVersion)
class StrategyVersionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "version", "active", "published_at")


@admin.register(Signal)
class SignalAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("strategy_version", "signal_date", "tradable_on", "created_at")
