"""
대시보드 API 라우터
- 근무표 만족도 분석 데이터 제공
- 개인별 요청 반영률 통계
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db.client import get_db
from schemas.auth_schema import User
from routers.auth import get_current_user_from_cookie
from services.dashboard_service import (
    get_roster_analytics_summary,
    get_individual_analytics,
    get_request_details,
    get_monthly_trends
)
from typing import Optional

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/summary")
async def get_dashboard_summary(
    year: Optional[int] = Query(None, description="조회할 년도"),
    month: Optional[int] = Query(None, description="조회할 월"),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    대시보드 요약 데이터를 조회합니다.
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
        
        summary = get_roster_analytics_summary(
            group_id=current_user.group_id,
            year=year,
            month=month,
            db=db
        )
        return summary
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"대시보드 요약 데이터 조회 실패: {str(e)}")

@router.get("/individual")
async def get_individual_dashboard(
    year: Optional[int] = Query(None, description="조회할 년도"),
    month: Optional[int] = Query(None, description="조회할 월"),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    개인별 만족도 분석 데이터를 조회합니다.
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
        
        individual_data = get_individual_analytics(
            group_id=current_user.group_id,
            year=year,
            month=month,
            db=db
        )
        return individual_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"개인별 분석 데이터 조회 실패: {str(e)}")

@router.get("/trends")
async def get_monthly_trend(
    months: int = Query(6, description="조회할 월 수", ge=1, le=12),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    월별 만족도 트렌드를 조회합니다.
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
        
        trends = get_monthly_trends(
            group_id=current_user.group_id,
            months=months,
            db=db
        )
        return trends
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월별 트렌드 조회 실패: {str(e)}")

@router.get("/request-details/{analytics_id}")
async def get_request_details_by_analytics(
    analytics_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    특정 분석의 상세 요청 데이터를 조회합니다.
    """
    try:
        if not current_user:
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
        
        details = get_request_details(
            analytics_id=analytics_id,
            db=db
        )
        return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상세 요청 데이터 조회 실패: {str(e)}") 