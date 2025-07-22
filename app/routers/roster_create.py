from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime
from app.schemas.auth_schema import User as UserSchema
from app.schemas.roster_schema import RosterRequest
from app.db.client import get_db
from app.db.models import Nurse, ShiftPreference, RosterConfig, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage
from app.routers.utils import get_days_in_month
from app.routers.auth import get_current_user_from_cookie
from sqlalchemy import func, and_
from app.db.models import Schedule, Shift
from app.routers.utils import Timer
from datetime import date
import uuid
from app.services.roster_create_service import generate_roster_service, request_schedule_service

# CP-SAT 기반 엔진들 import
try:
    from app.services.random_sampling import generate_roster
    from app.services.cp_sat_basic import generate_roster_cp_sat
    from app.services.cp_sat_main_v3 import generate_roster_cp_sat_main_v3
    from app.services.cp_sat_main_v2 import generate_roster_cp_sat_main_v2
    from app.services.cp_sat_adaptive import generate_roster_cp_sat_adaptive
    CPSAT_AVAILABLE = True
    CPSAT_MAIN_V3_AVAILABLE = True
    CPSAT_MAIN_V2_AVAILABLE = True
    CPSAT_ADAPTIVE_AVAILABLE = True
    print("CP-SAT 엔진들이 사용 가능합니다.")
except ImportError as e:
    print(f"CP-SAT 엔진 import 실패: {e}")
    CPSAT_AVAILABLE = False
    CPSAT_MAIN_V3_AVAILABLE = False
    CPSAT_MAIN_V2_AVAILABLE = False
    CPSAT_ADAPTIVE_AVAILABLE = False



router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# [Roster] - 근무표 생성
@router.post("/roster_create/generate")
async def generate_roster_endpoint(
    req: RosterRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return generate_roster_service(req, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"근무표 생성 실패: {str(e)}")


    # [Schedules] - 수간호사가 근무표 생성 요청
@router.post("/roster/request")
async def request_schedule(
    req: RosterRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return request_schedule_service(req, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"스케줄 생성 실패: {str(e)}")


    