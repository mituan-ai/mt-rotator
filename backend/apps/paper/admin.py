from django.contrib import admin

from apps.core.admin_mixins import ReadOnlyAdminMixin

from .models import (
    AdviceSnapshot,
    Fill,
    HoldingSnapshot,
    LedgerEntry,
    NavSnapshot,
    Order,
    PaperAccount,
    PaperCycleRun,
    PaperRebalance,
    Position,
    PositionLot,
)

for model in [
    PaperAccount,
    PaperCycleRun,
    Position,
    PositionLot,
    PaperRebalance,
    Order,
    Fill,
    LedgerEntry,
    NavSnapshot,
    HoldingSnapshot,
    AdviceSnapshot,
]:
    admin.site.register(model, type(f"{model.__name__}Admin", (ReadOnlyAdminMixin, admin.ModelAdmin), {}))
