from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.market.calendar import sessions_in_range

from .models import NavSnapshot, PaperAccount

VALID_PERIODS = {"mtd", "3m", "1y", "all"}
MIN_RANKING_SESSIONS = 20


def _period_start(period: str, end: date) -> date | None:
    if period == "mtd":
        return date(end.year, end.month, 1)
    if period == "3m":
        return end - relativedelta(months=3)
    if period == "1y":
        return end - relativedelta(years=1)
    return None


def _metrics(account: PaperAccount, period: str, end: date) -> dict:
    start = _period_start(period, end)
    queryset = NavSnapshot.objects.filter(account=account, date__lte=end).order_by("date")
    all_rows = list(queryset.values("date", "value"))
    account_age = len(all_rows)
    eligible = account_age >= MIN_RANKING_SESSIONS
    eligibility_reason = ""
    if not eligible:
        eligibility_reason = f"账户不足{MIN_RANKING_SESSIONS}个交易日"
    if start:
        before = [row for row in all_rows if row["date"] <= start]
        if not before:
            eligible = False
            eligibility_reason = "账户未覆盖完整排行周期"
            period_rows = [row for row in all_rows if row["date"] >= start]
        else:
            baseline = before[-1]
            period_rows = [baseline, *[row for row in all_rows if start < row["date"] <= end]]
    else:
        period_rows = all_rows
    if len(period_rows) < 2:
        total_return = Decimal("0")
        max_drawdown = Decimal("0")
    else:
        values = [Decimal(row["value"]) for row in period_rows]
        total_return = values[-1] / values[0] - 1 if values[0] else Decimal("0")
        peak = values[0]
        max_drawdown = Decimal("0")
        for value in values:
            peak = max(peak, value)
            drawdown = value / peak - 1 if peak else Decimal("0")
            max_drawdown = min(max_drawdown, drawdown)
    current_nav = Decimal(period_rows[-1]["value"]) if period_rows else Decimal(account.cash)
    return {
        "account": account,
        "eligible": eligible,
        "eligibility_reason": eligibility_reason,
        "return": total_return,
        "max_drawdown": max_drawdown,
        "current_nav": current_nav,
        "account_age_sessions": account_age,
    }


def _ranked(accounts: list[PaperAccount], period: str, end: date) -> list[dict]:
    rows = [_metrics(account, period, end) for account in accounts]
    eligible = sorted(
        (row for row in rows if row["eligible"]),
        key=lambda row: (
            -row["return"],
            -row["max_drawdown"],
            row["account"].created_at,
            str(row["account"].id),
        ),
    )
    ranks = {row["account"].id: index for index, row in enumerate(eligible, start=1)}
    for row in rows:
        row["rank"] = ranks.get(row["account"].id)
    return sorted(
        rows, key=lambda row: (row["rank"] is None, row["rank"] or 10**9, row["account"].created_at)
    )


def build_leaderboard(period: str = "mtd") -> dict:
    if period not in VALID_PERIODS:
        raise ValueError("排行周期无效")
    accounts = list(
        PaperAccount.objects.filter(mode=PaperAccount.Mode.MANUAL, status=PaperAccount.Status.ACTIVE)
        .select_related("user")
        .order_by("created_at")
    )
    latest_dates = []
    for account in accounts:
        latest = account.nav_snapshots.order_by("-date").values_list("date", flat=True).first()
        if latest:
            latest_dates.append(latest)
    as_of = min(latest_dates) if latest_dates else None
    if not as_of:
        return {"period": period, "as_of_date": None, "results": []}
    current = _ranked(accounts, period, as_of)
    sessions = sessions_in_range(as_of - relativedelta(days=10), as_of)
    previous_date = sessions[-2] if len(sessions) > 1 else None
    previous_ranks = {}
    if previous_date:
        previous_ranks = {row["account"].id: row["rank"] for row in _ranked(accounts, period, previous_date)}
    results = []
    for row in current:
        account = row["account"]
        previous_rank = previous_ranks.get(account.id)
        rank_change = previous_rank - row["rank"] if previous_rank and row["rank"] else None
        results.append(
            {
                "rank": row["rank"],
                "rank_change": rank_change,
                "display_name": account.user.display_name,
                "account_number": str(account.id).split("-")[0],
                "return": str(row["return"].quantize(Decimal("0.000001"))),
                "max_drawdown": str(row["max_drawdown"].quantize(Decimal("0.000001"))),
                "current_nav": str(row["current_nav"].quantize(Decimal("0.01"))),
                "account_age_sessions": row["account_age_sessions"],
                "eligible": row["eligible"],
                "eligibility_reason": row["eligibility_reason"],
                "started_at": account.created_at,
            }
        )
    return {"period": period, "as_of_date": as_of, "results": results}
