from __future__ import annotations

from datetime import date
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=1)
def calendar():
    return xcals.get_calendar("XSHG")


def latest_expected_session(on_date: date | None = None) -> date:
    target = pd.Timestamp(on_date or date.today())
    session = calendar().date_to_session(target, direction="previous")
    return session.date()


def next_session(after: date) -> date:
    session = calendar().date_to_session(pd.Timestamp(after), direction="next")
    if session.date() == after:
        session = calendar().next_session(session)
    return session.date()


def is_month_end_session(value: date) -> bool:
    session = calendar().date_to_session(pd.Timestamp(value), direction="none")
    return calendar().next_session(session).month != session.month


def sessions_in_range(start: date, end: date) -> list[date]:
    return [item.date() for item in calendar().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))]
