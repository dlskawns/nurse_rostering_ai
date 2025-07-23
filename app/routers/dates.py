from fastapi import APIRouter, Depends, HTTPException
from services.holiday_pack import (
    get_weekends,
    get_korean_public_holidays,
    serialise,
)
router = APIRouter()

@router.get("/dates/holidays")
def get_holidays(
    year: int, 
    month: int,
):
    holidays_serial = serialise(get_korean_public_holidays(year, month))
    weekends_serial = serialise(get_weekends(year, month))
    total_holiday = sorted(set(holidays_serial + weekends_serial))
    return total_holiday

@router.get("/dates/weekends")
def get_holidays(
    year: int, 
    month: int,
):
    weekends_serial = serialise(get_weekends(year, month))
    return weekends_serial