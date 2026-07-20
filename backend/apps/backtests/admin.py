from django.contrib import admin

from apps.core.admin_mixins import ReadOnlyAdminMixin

from .models import BacktestRun


@admin.register(BacktestRun)
class BacktestRunAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user", "strategy_version", "status", "start_date", "end_date", "created_at")
    list_filter = ("status", "strategy_version")
