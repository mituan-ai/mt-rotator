from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("internal-admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/market/", include("apps.market.urls")),
    path("api/v1/strategies/", include("apps.strategies.urls")),
    path("api/v1/backtests/", include("apps.backtests.urls")),
    path("api/v1/paper/", include("apps.paper.urls")),
]
