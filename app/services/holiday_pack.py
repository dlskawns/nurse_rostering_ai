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

# LangChain tool decorator for exposing wrappers
from langchain_core.tools import tool


def get_dates_of_month(year: int, month: int) -> List[date]:
    """Return a list of all dates in *year*/*month* (1‑indexed)."""
    
    _, num_days = calendar.monthrange(year, month)
    return [date(year, month, day) for day in range(1, num_days + 1)]


def get_weekends(year: int, month: int) -> List[date]:
    """    
    Get the specific month and date information for user
    This function returns the month's weekends date information

    Args:
        year (int): A year which the user wants to know the weekend dates of. if there's no information about year, just use today based year
        month (int): A month which the user wants to know the weekend dates of

    Returns:
        list: the weekend dates information of the month
    """
    return [d for d in get_dates_of_month(year, month) if d.weekday() >= 5]


def get_korean_public_holidays(year: int, month: int) -> List[date]:
    """    
    Get the specific month's public holiday information for user
    This function returns the month's public holiday date information

    Args:
        year (int): A year which the user wants to know the public holiday dates of 
        month (int): A month which the user wants to know the public holiday dates of

    Returns:
        list: the public holiday dates information of the month"""
    return [d for d in get_dates_of_month(year, month) if d in _kr_holidays]


def serialise(dates: List[date]) -> list[str]:
    """Convert date objects to ISO‑formatted strings."""
    return [d.isoformat() for d in dates]


# -----------------------------
# Tool-exposed wrappers (new)
# -----------------------------
# @tool("get_weekends")
def tool_get_weekends(year: int, month: int) -> list[str]:
    """    
    Only Use This Tool when you want to know the weekends date information
    Do not use when you don't need to know that info
    Get the specific month and date information for user
    This function returns the month's weekends date information

    Args:
        year (int): A year which the user wants to know the weekend dates of. if there's no information about year, just use today based year
        month (int): A month which the user wants to know the weekend dates of

    Returns:
        list: the weekend dates information of the month"""
    return serialise(get_weekends(year, month))


# @tool("get_holidays")
def tool_get_holidays(year: int, month: int) -> list[str]:
    """
    Only Use This Tool when you want to know the public holiday date information
    Do not use when you don't need to know that info
    Get the specific month's public holiday information for user
    This function returns the month's public holiday date information

    Args:
        year (int): A year which the user wants to know the public holiday dates of 
        month (int): A month which the user wants to know the public holiday dates of

    Returns:
        list: the public holiday dates information of the month
    """
    return serialise(get_korean_public_holidays(year, month))

