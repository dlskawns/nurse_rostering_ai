from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict

from db.client import get_db
# from db.client2 import _get_mssql_session
from routers.auth import get_current_user_from_cookie
from schemas.auth_schema import User as UserSchema
from schemas.daily_shift_schema import (
    DailyShiftMonthQuery,
    DailyShiftMonthlyUpdate,
    DailyShiftDailyUpdate,
)
from services.daily_shift_service import (
    get_or_init_month,
    update_monthly,
    update_daily,
)

router = APIRouter(prefix="/daily-shift", tags=["daily-shift"])


@router.get("")
async def get_month(
    office_id: str,
    group_id: str,
    year: int,
    month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """월 데이터 조회(없으면 shift_manage 기반으로 생성).
    - 쿼리: office_id, group_id, year, month
    - 반환: month_summary + 일자별 리스트
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증 필요")
        return get_or_init_month(db, office_id, group_id, year, month)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월 데이터 조회 실패: {e}")


@router.put("/monthly")
async def put_monthly(
    body: DailyShiftMonthlyUpdate,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """월 전체 일괄 업데이트. shift_manage 템플릿과 daily_shift 월 데이터를 동기화합니다."""
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증 필요")
        result = update_monthly(
            db,
            office_id=body.office_id,
            group_id=body.group_id,
            year=body.year,
            month=body.month,
            day_cnt=body.day,
            eve_cnt=body.evening,
            nig_cnt=body.night,
            apply_globally=body.apply_globally,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월 업데이트 실패: {e}")


@router.put("/daily")
async def put_daily(
    body: DailyShiftDailyUpdate,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """일자별 배열 업데이트.
    - body: {D:[], E:[], N:[]}
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증 필요")
        result = update_daily(
            db,
            office_id=body.office_id,
            group_id=body.group_id,
            year=body.year,
            month=body.month,
            d_list=body.D,
            e_list=body.E,
            n_list=body.N,
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"일별 업데이트 실패: {e}") 