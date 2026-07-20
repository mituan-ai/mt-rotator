from django.contrib import admin

from apps.core.admin_mixins import ReadOnlyAdminMixin

from .models import (
    Fill,
    HoldingSnapshot,
    LedgerEntry,
    NavSnapshot,
    Order,
    PaperAccount,
    PaperRebalance,
    Position,
)

for model in [
    PaperAccount,
    Position,
    PaperRebalance,
    Order,
    Fill,
    LedgerEntry,
    NavSnapshot,
    HoldingSnapshot,
]:
    admin.site.register(model, type(f"{model.__name__}Admin", (ReadOnlyAdminMixin, admin.ModelAdmin), {}))
