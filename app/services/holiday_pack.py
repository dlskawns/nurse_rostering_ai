# weekend_utils.py
"""Utility functions for Korean calendar queries."""
from __future__ import annotations

from datetime import date, timedelta, datetime
import calendar
from typing import List

try:
    import holidays  # python-holidays
except ImportError as e:
    raise ImportError("python-holidays 패키지를 설치하세요: pip install holidays") from e

# 한국 공휴일을 제공하는 객체 (대체 공휴일 포함)
_kr_holidays = holidays.KR()  # type: ignore
this_year = datetime.now().year

def get_dates_of_month(year: int, month: int) -> List[date]:
    """Return a list of all dates in *year*/*month* (1‑indexed)."""
    
    _, num_days = calendar.monthrange(year, month)
    return [date(year, month, day) for day in range(1, num_days + 1)]


def get_weekends(year: int, month: int) -> List[date]:
    """Return Saturday/Sunday dates in the given month."""
    return [d for d in get_dates_of_month(year, month) if d.weekday() >= 5]


def get_korean_public_holidays(year: int, month: int) -> List[date]:
    """Return KR public holidays (including substitute holidays) in the month."""
    return [d for d in get_dates_of_month(year, month) if d in _kr_holidays]


def serialise(dates: List[date]) -> list[str]:
    """Convert date objects to ISO‑formatted strings."""
    return [d.isoformat() for d in dates]


# print(serialise(get_korean_public_holidays(2025, 6)) + serialise(get_weekends(2025, 6)))
