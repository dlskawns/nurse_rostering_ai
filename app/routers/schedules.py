from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
import uuid
from datetime import datetime, date
from fastapi.responses import RedirectResponse
import numpy as np
from typing import Optional
from app.db.client import get_db
from app.db.models import Schedule, ShiftPreference, Nurse, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage
from app.schemas.auth_schema import User as UserSchema
from app.routers.auth import get_current_user_from_cookie
from app.roster_engine import generate_roster, get_days_in_month
from app.routers.utils import Timer
from roster_system import RosterSystem
from nurse import Nurse as NurseEngine
from config import NurseRosterConfig
from app.routers.utils import parse_prefs_to_dict

# CP-SAT 기반 엔진들 import
try:
    from cp_sat_basic import generate_roster_cp_sat
    from cp_sat_main_v3 import generate_roster_cp_sat_main_v3
    from cp_sat_main_v2 import generate_roster_cp_sat_main_v2
    from cp_sat_adaptive import generate_roster_cp_sat_adaptive
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

router = APIRouter(
    prefix="/api",
    tags=["schedules"]
)

class ScheduleRequest(BaseModel):
    year: int
    month: int
    algorithm: str = "cp_sat"  # "cp_sat" or "random_sampling"

class PreferenceSubmit(BaseModel):
    year: int
    month: int

class PreferenceData(BaseModel):
    year: int
    month: int
    data: dict

# [Schedules] - 수간호사가 근무표 생성 요청
@router.post("/schedules/request")
async def request_schedule(
    req: ScheduleRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Get group and office info
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise HTTPException(status_code=404, detail="User group information not found")

    # Check for roster configuration
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.office_id == nurse.group.office_id,
        RosterConfig.group_id == nurse.group_id
    ).order_by(RosterConfig.created_at.desc()).first()

    if not latest_config:
        raise HTTPException(status_code=400, detail="설정값을 입력해주세요")

    # Find the latest version for the same year and month
    latest_version = db.query(func.max(Schedule.version)).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == req.year,
        Schedule.month == req.month
    ).scalar() or 0

    new_schedule = Schedule(
        schedule_id=str(uuid.uuid4().hex)[:12],
        office_id=nurse.group.office_id,
        group_id=current_user.group_id,
        year=req.year,
        month=req.month,
        version=latest_version + 1,
        config_id=latest_config.config_id,
        created_by=current_user.account_id,
        status='draft'  # 기본적으로 draft 상태로 생성
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    # # Check and add default shifts if they don't exist
    # default_shifts = [
    #     {'shift_id': 'D', 'name': 'Day', 'color': '#87CEEB'},
    #     {'shift_id': 'E', 'name': 'Evening', 'color': '#FFDAB9'},
    #     {'shift_id': 'N', 'name': 'Night', 'color': '#6A5ACD'},
    #     {'shift_id': 'O', 'name': 'Off', 'color': '#F5F5F5'},
    # ]
    # for shift_data in default_shifts:
    #     exists = db.query(Shift).filter(Shift.shift_id == shift_data['shift_id']).first()
    #     if not exists:
    #         db.add(Shift(**shift_data))
    # db.commit()

    return new_schedule

# [Schedules] - 현재 그룹의 활성화된(requested) 모든 스케줄 조회
@router.get("/schedules/active")
async def get_active_schedules(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    schedules_query = db.query(Schedule.year, Schedule.month).filter(
        and_(
            Schedule.group_id == current_user.group_id,
            Schedule.status == 'requested'
        )
    ).distinct().order_by(Schedule.year.desc(), Schedule.month.desc()).all()
    
    schedules = [{"year": r.year, "month": r.month} for r in schedules_query]
    
    return schedules

# [Schedules] - 발행된(issued) 모든 스케줄 조회
@router.get("/schedules/issued")
async def get_issued_schedules(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    schedules_query = db.query(Schedule.year, Schedule.month).filter(
        and_(
            Schedule.group_id == current_user.group_id,
            Schedule.status == 'issued'
        )
    ).distinct().order_by(Schedule.year.desc(), Schedule.month.desc()).all()
    
    schedules = [{"year": r.year, "month": r.month} for r in schedules_query]
    return schedules

# [Schedules] - 특정 스케줄의 모든 간호사 제출 현황 확인
@router.get("/schedules/{year}/{month}/submissions")
async def get_submission_statuses(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Get all nurses in the current user's group
    nurses_in_group = db.query(Nurse.nurse_id).filter(Nurse.group_id == current_user.group_id).all()
    nurse_ids_in_group = {n[0] for n in nurses_in_group}

    # 각 간호사의 최신 제출 상태 확인
    submitted_nurse_ids = set()
    for nurse_id in nurse_ids_in_group:
        # 해당 간호사의 최신 제출된 선호도가 있는지 확인
        latest_submitted = db.query(ShiftPreference).filter(
            ShiftPreference.nurse_id == nurse_id,
            ShiftPreference.year == year,
            ShiftPreference.month == month,
            ShiftPreference.is_submitted == True
        ).order_by(ShiftPreference.submitted_at.desc()).first()
        
        if latest_submitted:
            submitted_nurse_ids.add(nurse_id)

    return {
        "submitted_nurses": list(submitted_nurse_ids),
    }

# [Schedules] - 현재 그룹의 특정 월에 대한 스케줄 상태 확인
@router.get("/schedules/status")
async def get_schedule_status(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # 수간호사인 경우 schedules 테이블 확인
    if current_user.is_head_nurse:
        schedules = db.query(Schedule).filter(
            Schedule.group_id == current_user.group_id,
            Schedule.year == year,
            Schedule.month == month
        ).all()
        
        has_schedules = len(schedules) > 0
        latest_status = schedules[0].status if schedules else None
        
        return {
            "has_schedules": has_schedules,
            "latest_status": latest_status,
            "schedule_count": len(schedules)
        }
    
    # 일반 간호사인 경우 - 최신 선호도 데이터 조회
    schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month
    ).order_by(Schedule.version.desc()).first()

    # 최신 제출된 선호도 먼저 확인
    submitted_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()
    
    if submitted_preference:
        return {
            "schedule_status": schedule.status if schedule else None,
            "preference_is_submitted": True,
            "preference_data": submitted_preference.data,
            "has_schedules": schedule is not None,
            "created_at": submitted_preference.created_at,
            "submitted_at": submitted_preference.submitted_at
        }
    
    # 제출된 것이 없으면 최신 draft 확인
    draft_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()
    
    if draft_preference:
        return {
            "schedule_status": schedule.status if schedule else None,
            "preference_is_submitted": False,
            "preference_data": draft_preference.data,
            "has_schedules": schedule is not None,
            "created_at": draft_preference.created_at,
            "submitted_at": None
        }
    
    # 아무 선호도도 없는 경우
    return {
        "schedule_status": schedule.status if schedule else None,
        "preference_is_submitted": False,
        "preference_data": None,
        "has_schedules": schedule is not None,
        "created_at": None,
        "submitted_at": None
    }

# [Preferences] - 간호사 개인의 선호도 초안 저장
@router.post("/preferences")
async def save_preference_draft(
    pref_data: PreferenceData,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # try:
    # 항상 새로운 레코드 생성 (덮어쓰기 방지)
    print('성공0')
    from datetime import datetime
    
    current_time = datetime.now().replace(microsecond=0)
    print('성공1', current_time)
    preference = ShiftPreference(
        nurse_id=current_user.nurse_id,
        year=pref_data.year,
        month=pref_data.month,
        data=pref_data.data,
        is_submitted=False,
        created_at=current_time,

    )
    db.add(preference)
    db.commit()
    print('성공3')
    db.refresh(preference)
    
    return {"message": "Preference draft saved successfully"}
        
    # except Exception as e:
    #     db.rollback()
    #     # Primary key 중복 에러 처리
    #     if "Duplicate entry" in str(e) or "1062" in str(e):
    #         # 동일한 시간에 생성된 레코드가 있으면 해당 레코드를 업데이트
            
    #         current_time = datetime.now()
            
    #         # 현재 시간(초 단위)과 동일한 created_at를 가진 레코드 찾기
    #         existing_pref = db.query(ShiftPreference).filter(
    #             ShiftPreference.nurse_id == current_user.nurse_id,
    #             ShiftPreference.year == pref_data.year,
    #             ShiftPreference.month == pref_data.month,
    #             func.date_format(ShiftPreference.created_at, '%Y-%m-%d %H:%i:%s') == 
    #             func.date_format(current_time, '%Y-%m-%d %H:%i:%s')
    #         ).first()
            
    #         if existing_pref:
    #             # 기존 레코드 업데이트
    #             existing_pref.data = pref_data.data
    #             existing_pref.is_submitted = False
    #             db.commit()
    #             return {"message": "Preference draft updated successfully"}
    #         else:
    #             # 약간의 시간 지연 후 재시도
    #             import time
    #             time.sleep(0.1)  # 100ms 대기
    #             preference = ShiftPreference(
    #                 nurse_id=current_user.nurse_id,
    #                 year=pref_data.year,
    #                 month=pref_data.month,
    #                 data=pref_data.data,
    #                 is_submitted=False,
    #             )
    #             db.add(preference)
    #             db.commit()
    #             db.refresh(preference)
    #             return {"message": "Preference draft saved successfully (retry)"}
    #     else:
    #         raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# [Preferences] - 선호도 최종 제출
@router.post("/preferences/submit")
async def submit_preferences(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 최신 draft 찾기
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()

    if not preference:
        raise HTTPException(status_code=404, detail="No preference draft found to submit")

    preference.is_submitted = True
    preference.submitted_at = datetime.utcnow()
    db.commit()
    return {"message": "Preferences submitted successfully"}

# [Preferences] - 빈 선호도 최종 제출
@router.post("/preferences/submit/empty")
async def submit_empty_preferences(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 빈 데이터로 새 레코드 생성 및 즉시 제출
    empty_data = {"shift": {}, "preference": []}
    preference = ShiftPreference(
        nurse_id=current_user.nurse_id,
        year=req.year,
        month=req.month,
        data=empty_data,
        is_submitted=True,
        submitted_at=datetime.utcnow()
    )
    db.add(preference)
    db.commit()
    return {"message": "Empty preferences submitted successfully"}

# [Preferences] - 최종 제출 철회 (수정)
@router.post("/preferences/retract")
async def retract_submission(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 최신 제출된 레코드 찾기
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()

    if not preference:
        raise HTTPException(status_code=404, detail="No submitted preference found to retract")

    preference.is_submitted = False
    preference.submitted_at = None
    db.commit()
    return {"message": "Submission retracted successfully"}

# [Preferences] - 최신 선호도 데이터 조회
@router.get("/preferences/latest")
async def get_latest_preference(
    year: int, 
    month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 해당 년월의 최신 레코드 찾기 (제출된 것 우선, 없으면 draft 중 최신)
    submitted_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()
    
    if submitted_preference:
        return {
            "preference_data": submitted_preference.data,
            "is_submitted": True,
            "created_at": submitted_preference.created_at,
            "submitted_at": submitted_preference.submitted_at
        }
    
    # 제출된 것이 없으면 최신 draft 찾기
    draft_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()
    
    if draft_preference:
        return {
            "preference_data": draft_preference.data,
            "is_submitted": False,
            "created_at": draft_preference.created_at,
            "submitted_at": None
        }
    
    # 아무것도 없으면 빈 데이터 반환
    return {
        "preference_data": None,
        "is_submitted": False,
        "created_at": None,
        "submitted_at": None
    }

# [Preferences] - 모든 간호사의 희망사항 현황 조회
@router.get("/preferences/all")
async def get_all_preferences(
    year: int, 
    month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 해당 그룹의 모든 간호사의 최신 제출된 선호도 조회
    preferences = db.query(ShiftPreference).filter(
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).join(Nurse, ShiftPreference.nurse_id == Nurse.nurse_id).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(ShiftPreference.submitted_at.desc()).all()
    
    # 간호사별로 가장 최신 제출 데이터만 유지
    latest_prefs = {}
    for pref in preferences:
        if pref.nurse_id not in latest_prefs:
            latest_prefs[pref.nurse_id] = pref
    
    return list(latest_prefs.values())

# [Shifts] - 모든 시프트 정보 조회
@router.get("/shifts")
async def get_shifts(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # 현재 사용자의 그룹에 해당하는 시프트 정보 조회 (sequence 순서로 정렬)
    shifts = db.query(Shift).filter(Shift.group_id == current_user.group_id).order_by(Shift.sequence.asc()).all()
    
    return [
        {
            "shift_id": shift.shift_id,
            "name": shift.name,
            "color": shift.color,
            "start_time": shift.start_time,
            "end_time": shift.end_time,
            "type": shift.type,
            "allday": shift.allday,
            "auto_schedule": shift.auto_schedule,
            # "time_type": shift.time_type,
            "duration": shift.duration,
            "sequence": shift.sequence,
            "time_display": _format_time_display(shift)
        }
        for shift in shifts
    ]

def _format_time_display(shift):
    """근무 시간 정보를 표시용으로 포맷팅"""
    if shift.allday == 1:
        return '종일'
    elif shift.duration:
        return f'{shift.duration}시간'
    elif shift.start_time and shift.end_time:
        return f'{shift.start_time} ~ {shift.end_time}'
    elif shift.type:
        return shift.type

class ShiftAddRequest(BaseModel):
    shift_id: str
    name: str
    color: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    shift_type: str = "work"  # Changed from 'type' to 'shift_type' to match frontend
    # time_type: str = "range"
    duration: Optional[int] = None
    allday: Optional[int] = 0
    auto_schedule: Optional[int] = 1

@router.post("/shifts/add")
async def add_shift(
    req: ShiftAddRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Get current user's office_id
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise HTTPException(status_code=404, detail="User group information not found")
    
    # 중복 shift_id 체크 (같은 그룹 내에서)
    existing_shift = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    
    if existing_shift:
        raise HTTPException(status_code=400, detail="이미 존재하는 근무코드입니다.")
    
    # 현재 그룹의 최대 sequence 값 조회하여 +1
    max_sequence = db.query(func.max(Shift.sequence)).filter(
        Shift.group_id == current_user.group_id
    ).scalar() or 0
    
    # 새 시프트 생성
    new_shift = Shift(
        shift_id=req.shift_id,
        office_id=nurse.group.office_id,
        group_id=current_user.group_id,
        name=req.name,
        color=req.color,
        start_time=req.start_time,
        end_time=req.end_time,
        type=req.shift_type,  # 'work' or 'off'
        # time_type=req.time_type,
        duration=req.duration,
        allday=req.allday,
        auto_schedule=req.auto_schedule,
        sequence=max_sequence + 1
    )
    
    db.add(new_shift)
    db.commit()
    db.refresh(new_shift)
    
    return {
        "message": "근무코드가 성공적으로 추가되었습니다.",
        "shift": {
            "shift_id": new_shift.shift_id,
            "name": new_shift.name,
            "color": new_shift.color,
            "sequence": new_shift.sequence,
            "time_display": _format_time_display(new_shift)
        }
    }

@router.post("/shifts/update")
async def update_shift(
    req: ShiftAddRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # 기존 시프트 찾기
    existing_shift = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    
    if not existing_shift:
        raise HTTPException(status_code=404, detail="해당 근무코드를 찾을 수 없습니다.")
    
    # 시프트 정보 업데이트
    existing_shift.name = req.name
    existing_shift.color = req.color
    existing_shift.start_time = req.start_time
    existing_shift.end_time = req.end_time
    existing_shift.type = req.shift_type
    existing_shift.duration = req.duration
    existing_shift.allday = req.allday
    existing_shift.auto_schedule = req.auto_schedule
    # sequence는 수정 시 변경하지 않음 (드래그로만 변경)
    
    db.commit()
    db.refresh(existing_shift)
    
    return {
        "message": "근무코드가 성공적으로 수정되었습니다.",
        "shift": {
            "shift_id": existing_shift.shift_id,
            "name": existing_shift.name,
            "color": existing_shift.color,
            "sequence": existing_shift.sequence,
            "time_display": _format_time_display(existing_shift)
        }
    }

class RemoveShiftRequest(BaseModel):
    shift_id: str

@router.post("/shifts/remove")
async def remove_shift(
    req: RemoveShiftRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # 기존 시프트 찾기
    existing_shift = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    
    if not existing_shift:
        raise HTTPException(status_code=404, detail="해당 근무코드를 찾을 수 없습니다.")
    
    # 해당 근무코드가 사용 중인지 확인 (schedule_entries에서 참조되고 있는지)
    schedule_entries_count = db.query(ScheduleEntry).filter(
        ScheduleEntry.shift_id == req.shift_id
    ).count()
    
    if schedule_entries_count > 0:
        raise HTTPException(status_code=400, detail="해당 근무코드는 현재 사용 중이므로 삭제할 수 없습니다.")
    
    deleted_sequence = existing_shift.sequence
    
    # 시프트 삭제
    db.delete(existing_shift)
    
    # 삭제된 시프트보다 뒤에 있는 시프트들의 sequence를 -1씩 조정
    db.query(Shift).filter(
        Shift.group_id == current_user.group_id,
        Shift.sequence > deleted_sequence
    ).update({"sequence": Shift.sequence - 1})
    
    db.commit()
    
    return {"message": "근무코드가 성공적으로 삭제되었습니다."}

class MoveShiftRequest(BaseModel):
    shift_id: str
    new_sequence: int

@router.post("/shifts/move")
async def move_shift(
    req: MoveShiftRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # 이동할 시프트 찾기
    shift_to_move = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    
    if not shift_to_move:
        raise HTTPException(status_code=404, detail="해당 근무코드를 찾을 수 없습니다.")
    
    old_sequence = shift_to_move.sequence
    new_sequence = req.new_sequence
    
    if old_sequence == new_sequence:
        return {"message": "변경사항이 없습니다."}
    
    # 다른 시프트들의 sequence 조정
    if old_sequence < new_sequence:
        # 아래로 이동: old_sequence+1 ~ new_sequence 범위의 시프트들을 -1씩
        db.query(Shift).filter(
            Shift.group_id == current_user.group_id,
            Shift.sequence > old_sequence,
            Shift.sequence <= new_sequence
        ).update({"sequence": Shift.sequence - 1})
    else:
        # 위로 이동: new_sequence ~ old_sequence-1 범위의 시프트들을 +1씩
        db.query(Shift).filter(
            Shift.group_id == current_user.group_id,
            Shift.sequence >= new_sequence,
            Shift.sequence < old_sequence
        ).update({"sequence": Shift.sequence + 1})
    
    # 이동할 시프트의 sequence 업데이트
    shift_to_move.sequence = new_sequence
    
    db.commit()
    
    return {"message": "근무코드 순서가 성공적으로 변경되었습니다."}

# [Shift Management] - 시프트 관리 데이터 조회
@router.get("/shift-manage/{class_name}")
async def get_shift_manage(
    class_name: str,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get current user's office_id
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise HTTPException(status_code=404, detail="User group information not found")
    
    # 해당 클래스의 shift_manage 데이터 조회
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == class_name
    ).order_by(ShiftManage.shift_slot.asc()).all()
    
    # 데이터가 없으면 기본 슬롯 생성
    if not shift_manages:
        default_slots = [
            {"shift_slot": 1, "main_code": "D", "codes": [], "manpower": 3},
            {"shift_slot": 2, "main_code": "E", "codes": [], "manpower": 3},
            {"shift_slot": 3, "main_code": "N", "codes": [], "manpower": 2}
        ]
        
        # DB에 기본 슬롯 저장
        for slot_data in default_slots:
            shift_manage = ShiftManage(
                office_id=nurse.group.office_id,
                group_id=current_user.group_id,
                nurse_class=class_name,
                shift_slot=slot_data["shift_slot"],
                main_code=slot_data["main_code"],
                codes=slot_data["codes"],
                manpower=slot_data["manpower"]
            )
            db.add(shift_manage)
        
        db.commit()
        
        # 다시 조회해서 반환
        shift_manages = db.query(ShiftManage).filter(
            ShiftManage.office_id == nurse.group.office_id,
            ShiftManage.group_id == current_user.group_id,
            ShiftManage.nurse_class == class_name
        ).order_by(ShiftManage.shift_slot.asc()).all()
    
    return [
        {
            "shift_slot": sm.shift_slot,
            "main_code": sm.main_code,
            "codes": sm.codes if sm.codes else [],
            "manpower": sm.manpower
        }
        for sm in shift_manages
    ]

class ShiftManageSaveRequest(BaseModel):
    class_name: str
    slots: list  # [{"shift_slot": 1, "codes": ["D"], "manpower": 3}, ...]

@router.post("/shift-manage/save")
async def save_shift_manage(
    req: ShiftManageSaveRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Get current user's office_id
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise HTTPException(status_code=404, detail="User group information not found")
    
    # 기존 데이터 삭제 (특정 클래스의 모든 슬롯)
    db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == req.class_name
    ).delete()
    
    # 새 데이터 저장
    for slot_data in req.slots:
        shift_manage = ShiftManage(
            office_id=nurse.group.office_id,
            group_id=current_user.group_id,
            nurse_class=req.class_name,
            shift_slot=slot_data["shift_slot"],
            main_code=slot_data.get("main_code"),
            codes=slot_data["codes"],
            manpower=slot_data["manpower"]
        )
        db.add(shift_manage)
    
    db.commit()
    return {"message": "시프트 관리 설정이 저장되었습니다."}

# [Roster] - 근무표 생성
@router.post("/roster/generate")
async def generate_roster_endpoint(
    req: ScheduleRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 0. Check if wanted request exists for this month
    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    
    if not wanted:
        raise HTTPException(status_code=400, detail="해당 월의 wanted 작성을 먼저 요청해주세요.")

    # 1. Always create a new schedule version for each generation
    schedule = await request_schedule(req, current_user, db)

    # 2. Fetch all nurses and their preferences
    nurses_in_group = db.query(Nurse).filter(Nurse.group_id == current_user.group_id).order_by(Nurse.experience.desc(), Nurse.nurse_id.asc()).all()
    nurse_ids = [n.nurse_id for n in nurses_in_group]

    # 각 간호사의 최신 선호도 데이터 조회 (제출된 것 우선)
    preferences = []
    for nurse_id in nurse_ids:
        # 제출된 최신 선호도 먼저 확인
        submitted_pref = db.query(ShiftPreference).filter(
            ShiftPreference.nurse_id == nurse_id,
            ShiftPreference.year == req.year,
            ShiftPreference.month == req.month,
            ShiftPreference.is_submitted == True
        ).order_by(ShiftPreference.submitted_at.desc()).first()

        if submitted_pref:
            preferences.append(submitted_pref)
        else:
            # 제출된 것이 없으면 최신 draft 확인
            draft_pref = db.query(ShiftPreference).filter(
                ShiftPreference.nurse_id == nurse_id,
                ShiftPreference.year == req.year,
                ShiftPreference.month == req.month,
                ShiftPreference.is_submitted == False
            ).order_by(ShiftPreference.created_at.desc()).first()
            
            if draft_pref:
                preferences.append(draft_pref)

    # 3. Get latest roster configuration
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.group_id == current_user.group_id
    ).order_by(RosterConfig.created_at.desc()).first()

    if not latest_config:
        raise HTTPException(status_code=400, detail="설정값을 입력해주세요")

    # Get current user's office_id for shift manage data
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise HTTPException(status_code=404, detail="User group information not found")

    # Get shift manage data for RN class
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN'
    ).order_by(ShiftManage.shift_slot.asc()).all()

    # Convert shift manage data to daily requirements format
    daily_shift_requirements = {}
    for shift_manage in shift_manages:
        if shift_manage.codes:
            for code in shift_manage.codes:
                daily_shift_requirements[code] = shift_manage.manpower
    
    # 4. Convert data to formats expected by engines
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]
    config_dict = latest_config.__dict__ if latest_config else {}
    
    # Add daily shift requirements to config
    config_dict['daily_shift_requirements'] = daily_shift_requirements
    
    # 5. Choose engine and generate roster
    
    if req.algorithm == "cp_sat" and CPSAT_AVAILABLE:
        try:
            with Timer("CP-SAT 엔진으로 근무표 생성"):
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=60, 
                )
        except Exception as e:
            print("기존 엔진으로 폴백합니다.", e)
            generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    elif req.algorithm == "cp_sat_main_v3" and CPSAT_MAIN_V3_AVAILABLE:
        try:
            with Timer("CP-SAT Main V3 엔진으로 근무표 생성"):
                generated = generate_roster_cp_sat_main_v3(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=90
                )
        except Exception as e:
            print("CP-SAT 기본 엔진으로 폴백합니다.")
            if CPSAT_AVAILABLE:
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=60
                )
            else:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    elif req.algorithm == "cp_sat_main_v2" and CPSAT_MAIN_V2_AVAILABLE:
        try:
            with Timer("CP-SAT Main V2 엔진으로 근무표 생성"):
                generated = generate_roster_cp_sat_main_v2(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=90
                )
        except Exception as e:
            print("CP-SAT 기본 엔진으로 폴백합니다.")
            if CPSAT_AVAILABLE:
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=60
                )
            else:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    elif req.algorithm == "cp_sat_adaptive" and CPSAT_ADAPTIVE_AVAILABLE:
        try:
            with Timer("CP-SAT Adaptive 엔진으로 근무표 생성"):
                generated = generate_roster_cp_sat_adaptive(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=300
                )
        except Exception as e:
            print("CP-SAT 기본 엔진으로 폴백합니다.")
            if CPSAT_AVAILABLE:
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=60
                )
            else:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    elif req.algorithm == "random_sampling":
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    else:
        # 기본값 또는 CP-SAT 사용 불가능한 경우
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)

    # 6. Clear old entries and save new roster to DB
    db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
    print(generated.items())
    for nurse_id, shifts in generated.items():
        for day_index, shift_id in enumerate(shifts):
            if shift_id != '-':
                work_date = date(req.year, req.month, day_index + 1)
                entry = ScheduleEntry(
                    entry_id=str(uuid.uuid4().hex)[:16],
                    schedule_id=schedule.schedule_id,
                    nurse_id=nurse_id,
                    work_date=work_date,
                    shift_id=shift_id.upper()
                )
                db.add(entry)

    db.commit()

    # 7. Get shift colors
    shifts_db = db.query(Shift).all()
    shift_colors = {s.shift_id: s.color for s in shifts_db}
    
    # 8. DB에서 실제 저장된 데이터를 다시 읽어와서 응답 구성 (일관성 보장)
    # Get schedule entries that were just saved
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).all()
    
    roster_data = {
        "year": req.year, 
        "month": req.month,
        "schedule_id": schedule.schedule_id,
        "days_in_month": get_days_in_month(req.year, req.month),
        "shift_colors": shift_colors,
        "nurses": [],
        "violations": []  # 임시로 빈 리스트
    }
    print('\n\n\n\n\nroster_data', roster_data, '\n\n\n\n\n')
    # Structure data by nurse using DB entries (동일한 로직으로 일관성 보장)
    entries_by_nurse = {}
    for entry in entries:
        if entry.nurse_id not in entries_by_nurse:
            entries_by_nurse[entry.nurse_id] = {}
        entries_by_nurse[entry.nurse_id][entry.work_date.day] = entry.shift_id

    for nurse in nurses_in_group:
        nurse_schedule = [entries_by_nurse.get(nurse.nurse_id, {}).get(d, '-') for d in range(1, roster_data["days_in_month"] + 1)]
        counts = {shift: nurse_schedule.count(shift) for shift in shift_colors.keys()}
        
        roster_data["nurses"].append({
            "id": nurse.nurse_id,
            "name": nurse.name,
            "experience": nurse.experience,
            "schedule": nurse_schedule,
            "counts": counts
        })
    
    return roster_data

# [Roster] - 특정 schedule_id의 근무표 조회
@router.get("/roster/schedule/{schedule_id}")
async def get_roster_by_schedule_id(
    schedule_id: str,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Get schedule info
    schedule = db.query(Schedule).filter(
        Schedule.schedule_id == schedule_id,
        Schedule.group_id == current_user.group_id
    ).first()
    
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    
    # Get all nurses in the group
    nurses_in_group = db.query(Nurse.nurse_id, Nurse.name, Nurse.experience).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(Nurse.experience.desc(), Nurse.nurse_id.asc()).all()

    # Get shift colors
    shifts_db = db.query(Shift).all()
    shift_colors = {s.shift_id: s.color for s in shifts_db}
    
    # Get schedule entries
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule_id).all()
    
    roster_data = {
        "year": schedule.year, 
        "month": schedule.month,
        "schedule_id": schedule_id,
        "days_in_month": get_days_in_month(schedule.year, schedule.month),
        "shift_colors": shift_colors,
        "nurses": []
    }
    
    # Structure data by nurse
    entries_by_nurse = {}
    for entry in entries:
        if entry.nurse_id not in entries_by_nurse:
            entries_by_nurse[entry.nurse_id] = {}
        entries_by_nurse[entry.nurse_id][entry.work_date.day] = entry.shift_id

    violations = []  # 임시로 빈 리스트

    for nurse in nurses_in_group:
        nurse_schedule = [entries_by_nurse.get(nurse.nurse_id, {}).get(d, '-') for d in range(1, roster_data["days_in_month"] + 1)]
        
        counts = {shift: nurse_schedule.count(shift) for shift in shift_colors.keys()}
        
        roster_data["nurses"].append({
            "id": nurse.nurse_id,
            "name": nurse.name,
            "experience": nurse.experience,
            "schedule": nurse_schedule,
            "counts": counts
        })
    roster_data["violations"] = violations
        
    return roster_data

# [Roster] - 특정 월의 근무표 조회
@router.get("/roster/{year}/{month}")
async def get_roster_for_month(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get latest issued schedule for the month
    schedule_info = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month,
        Schedule.status == 'issued'
    ).order_by(Schedule.version.desc()).first()

    if not schedule_info:
        raise HTTPException(status_code=404, detail="No issued roster found for this month.")

    # Get all nurses in the group
    nurses_in_group = db.query(Nurse.nurse_id, Nurse.name, Nurse.experience).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(Nurse.experience.desc(), Nurse.nurse_id.asc()).all()

    # Get shift colors
    shifts_db = db.query(Shift).all()
    shift_colors = {s.shift_id: s.color for s in shifts_db}
    
    # Get schedule entries
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule_info.schedule_id).all()
    
    roster_data = {
        "year": year, "month": month,
        "days_in_month": get_days_in_month(year, month),
        "shift_colors": shift_colors,
        "nurses": []
    }
    
    # Structure data by nurse
    entries_by_nurse = {}
    for entry in entries:
        if entry.nurse_id not in entries_by_nurse:
            entries_by_nurse[entry.nurse_id] = {}
        entries_by_nurse[entry.nurse_id][entry.work_date.day] = entry.shift_id

    # 저장된 위반사항 사용 (RosterSystem 생성하지 않음)
    # violations = schedule_info.violations if schedule_info.violations else []
    violations = []  # 임시로 빈 리스트 반환 - DB 스키마 업데이트 후 위반사항 기능 복구 예정

    for nurse in nurses_in_group:
        nurse_schedule = [entries_by_nurse.get(nurse.nurse_id, {}).get(d, '-') for d in range(1, roster_data["days_in_month"] + 1)]
        
        counts = {shift: nurse_schedule.count(shift) for shift in shift_colors.keys()}
        
        roster_data["nurses"].append({
            "id": nurse.nurse_id,
            "name": nurse.name,
            "experience": nurse.experience,
            "schedule": nurse_schedule,
            "counts": counts
        })
    print(f'\n\n\n\n\n\n\n11위반사항 추가\n{violations}\n\n\n\n\n\n')
    roster_data["violations"] = violations
        
    return roster_data

# [Roster] - 근무표 저장
@router.post("/roster/save")
async def save_roster(
    roster_data: dict,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    year = roster_data.get('year')
    month = roster_data.get('month')
    roster = roster_data.get('roster')
    
    if not all([year, month, roster]):
        raise HTTPException(status_code=400, detail="Missing required fields: year, month, roster")

    # Get the latest schedule for the month
    schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month
    ).order_by(Schedule.version.desc()).first()
    
    if not schedule:
        raise HTTPException(status_code=404, detail="No schedule found for this month")

    # Clear existing roster entries
    db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
    
    # Save new roster entries
    for nurse in roster:
        nurse_id = nurse.get('nurse_id') or nurse.get('id')  # 둘 다 체크
        if not nurse_id:
            continue  # nurse_id가 없으면 건너뛰기
            
        schedule_data = nurse.get('schedule', [])
        for day_index, shift_id in enumerate(schedule_data):
            if shift_id and shift_id.strip():  # 빈 값이 아닌 경우만
                work_date = date(year, month, day_index + 1)
                entry = ScheduleEntry(
                    entry_id=str(uuid.uuid4().hex)[:16],
                    schedule_id=schedule.schedule_id,
                    nurse_id=nurse_id,
                    work_date=work_date,
                    shift_id=shift_id.upper()
                )
                db.add(entry)

    db.commit()
    return {"message": "Roster saved successfully"}

# [Roster] - 근무표 위반사항 실시간 계산
# [Roster] - 근무표 위반사항 실시간 계산
@router.post("/roster/validate")
async def validate_roster(
    roster_data: dict,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    # ──────────────────────── 0. 인증/파라미터 체크 ────────────────────────
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    year: int   = roster_data.get('year')
    month: int  = roster_data.get('month')
    roster      = roster_data.get('roster')

    if not all([year, month, roster]):
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: year, month, roster"
        )

    try:
        # ──────────────────────── 1. “base-code ↔️ 파생코드” 매핑 만들기 ────────────────────────
        #
        #  * 같은 nurse_class라도, 사전에 등록된 교대(slot) 기준으로만 조회
        #  * codes 열(JSON) 에 들어있는 파생 코드를 본교대(main_code) 로 매핑
        #
        from app.db.models import ShiftManage, Nurse, RosterConfig  # local import

        # ○ 현 수간호사의 부서 기준으로 조회
        shift_rows = db.query(ShiftManage).filter(
            ShiftManage.office_id == current_user.office_id,
            ShiftManage.group_id  == current_user.group_id
        ).all()

        #    예) { 'D': 'D', 'D1': 'D', 'MD': 'D',  'E': 'E', … }
        alias_map: dict[str, str] = {}

        for row in shift_rows:
            if not row.main_code:
                continue
            base = row.main_code.upper()          # ex) 'D'
            alias_map[base] = base

            if row.codes:
                # row.codes 가 JSON 컬럼 → 이미 list 로 deserialize 되어있음
                for code in row.codes:
                    alias_map[code.upper()] = base

        # OFF(휴무) 도 항상 포함시킴
        alias_map.setdefault('OFF', 'OFF')
        alias_map.setdefault('O',   'OFF')

        # ──────────────────────── 2. 근무표 설정(인원/제약) 불러오기 ────────────────────────
        latest_config_db = (
            db.query(RosterConfig)
              .filter(RosterConfig.group_id == current_user.group_id)
              .order_by(RosterConfig.created_at.desc())
              .first()
        )
        if not latest_config_db:
            return {"violations": ["근무표 설정을 찾을 수 없습니다."]}

        roster_config_for_engine = NurseRosterConfig(
            daily_shift_requirements={
                'D': latest_config_db.day_req,
                'E': latest_config_db.eve_req,
                'N': latest_config_db.nig_req
            },
            max_consecutive_work_days   = latest_config_db.max_conseq_work,
            max_night_shifts_per_month  = latest_config_db.max_nig_per_month,
            max_consecutive_nights      = 3 if latest_config_db.three_seq_nig else 2
        )

        # ──────────────────────── 3. RosterSystem 초기화 ────────────────────────
        nurses_for_engine = [
            NurseEngine.from_db_model(n, i)
            for i, n in enumerate(
                db.query(Nurse).filter(Nurse.group_id == current_user.group_id).all()
            )
        ]

        system = RosterSystem(
            nurses        = nurses_for_engine,
            target_month  = date(year, month, 1),
            config        = roster_config_for_engine
        )

        # shift_types 는 ['D','E','N','OFF'] (엔진 기본).  
        shift_map = {s: i for i, s in enumerate(system.config.shift_types)}
        system.roster.fill(0)                                # 3-D 배열 0으로 초기화

        # ──────────────────────── 4. 프론트에서 넘어온 근무표 → 엔진 포맷 변환 ────────────────────────
        for nurse_idx, nurse_data in enumerate(roster):
            if nurse_idx >= len(system.nurses):
                continue
            schedule = nurse_data.get('schedule', [])
            for day_idx, raw_shift in enumerate(schedule):
                if day_idx >= system.num_days:
                    continue
                # ① 대소문자 무시
                raw_shift = (raw_shift or '').upper()

                # ② alias_map 으로 본교대 변환
                base_shift = alias_map.get(raw_shift, raw_shift)

                # ③ 엔진 shift index 찾기
                shift_idx = shift_map.get(base_shift)
                if shift_idx is not None:
                    system.roster[nurse_idx, day_idx, shift_idx] = 1
                # else: 알 수 없는 코드 → 무시

        # ──────────────────────── 5. 위반사항 탐색 & 포매팅 ────────────────────────
        violation_details = system._find_violations()

        violation_messages: set[str] = set()
        detailed_violations: list[dict] = []

        for v in violation_details:
            if v['type'] == 'shift_requirement':
                violation_messages.add(
                    f"{v['day'] + 1}일: {v['shift']} 근무 인원 미달 "
                    f"(필요: {v['required']}, 배정: {v['actual']})"
                )
                detailed_violations.append({
                    'type': 'shift_requirement',
                    'day': v['day'],
                    'shift': v['shift'],
                    'required': v['required'],
                    'actual': v['actual']
                })
            elif v['type'] == 'consecutive':
                nurse_name = system.nurses[v['nurse_idx']].name
                violation_messages.add(f"{nurse_name}: 최대 연속 근무일 초과")
                detailed_violations.append({
                    'type': 'consecutive',
                    'nurse_idx': v['nurse_idx'],
                    'nurse_name': nurse_name,
                    'day': v['day']
                })
            elif v['type'] == 'night':
                nurse_name = system.nurses[v['nurse_idx']].name
                violation_messages.add(f"{nurse_name}: 야간 근무 제약 위반")
                detailed_violations.append({
                    'type': 'night',
                    'nurse_idx': v['nurse_idx'],
                    'nurse_name': nurse_name,
                    'day': v['day']
                })

        return {
            "violations": sorted(violation_messages),
            "detailed_violations": detailed_violations
        }

    # ──────────────────────── 6. 예외 처리 ────────────────────────
    except Exception as e:
        print(f"[validate_roster] 오류: {e}")
        return {
            "violations": [f"위반사항 계산 중 오류가 발생했습니다: {str(e)}"],
            "detailed_violations": []
        }


# [Schedules] - 특정 월의 모든 버전 목록 조회 (수간호사용)
@router.get("/schedules/{year}/{month}/versions")
async def get_schedule_versions(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    schedules = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month
    ).order_by(Schedule.version.desc()).all()
    
    return [{
        "schedule_id": schedule.schedule_id,
        "version": schedule.version,
        "status": schedule.status,
        "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        "created_by": schedule.created_by
    } for schedule in schedules]

# [Schedules] - 최신 월과 버전의 스케줄 정보 조회 (수간호사용)
@router.get("/schedules/latest")
async def get_latest_schedule(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Find the latest schedule (by year, month, version)
    latest_schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id
    ).order_by(
        Schedule.year.desc(),
        Schedule.month.desc(),
        Schedule.version.desc()
    ).first()
    
    if not latest_schedule:
        return None
        
    return {
        "year": latest_schedule.year,
        "month": latest_schedule.month,
        "version": latest_schedule.version,
        "status": latest_schedule.status,
        "schedule_id": latest_schedule.schedule_id
    }

# ========== WANTED 관련 API ==========

class WantedRequest(BaseModel):
    year: int
    month: int
    exp_date: Optional[datetime] = None

# [Wanted] - Wanted 작성 요청 생성 (수간호사용)
@router.post("/wanted/request")
async def request_wanted_shifts(
    req: WantedRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Check if wanted request already exists for this month
    existing_wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    
    if existing_wanted:
        raise HTTPException(status_code=400, detail="이미 해당 월의 요청이 존재합니다.")

    new_wanted = Wanted(
        group_id=current_user.group_id,
        year=req.year,
        month=req.month,
        exp_date=req.exp_date,
        status='requested'
    )
    db.add(new_wanted)
    db.commit()
    db.refresh(new_wanted)

    return {"message": "Wanted 작성 요청이 성공적으로 생성되었습니다."}

# [Wanted] - 특정 그룹의 Wanted 상태 조회
@router.get("/wanted/status")
async def get_wanted_status(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == year,
        Wanted.month == month
    ).first()

    if not wanted:
        return {"status": None, "message": "wanted 작성 요청 전"}
    
    return {
        "status": wanted.status,
        "exp_date": wanted.exp_date,
        "message": "작성 가능" if wanted.status == 'requested' else "wanted 작성 요청이 마감되었습니다"
    }

# [Wanted] - 현재 그룹의 모든 wanted 데이터 조회
@router.get("/wanted/all")
async def get_all_wanted(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    wanted_list = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id
    ).order_by(Wanted.year.desc(), Wanted.month.desc()).all()

    return [{
        "year": wanted.year,
        "month": wanted.month,
        "status": wanted.status,
        "exp_date": wanted.exp_date.isoformat() if wanted.exp_date else None,
        "created_at": wanted.created_at.isoformat() if wanted.created_at else None
    } for wanted in wanted_list]

# [Wanted] - Wanted 상태를 closed로 변경
@router.patch("/wanted/close")
async def close_wanted_request(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == year,
        Wanted.month == month
    ).first()
    
    if not wanted:
        raise HTTPException(status_code=404, detail="해당 월의 wanted 요청을 찾을 수 없습니다.")
    
    wanted.status = 'closed'
    db.commit()
    
    return {"message": "Wanted 요청이 마감되었습니다."}

# [Wanted] - Wanted 마감일 변경
@router.patch("/wanted/deadline")
async def update_wanted_deadline(
    req: WantedRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    
    if not wanted:
        raise HTTPException(status_code=404, detail="해당 월의 wanted 요청을 찾을 수 없습니다.")
    
    if wanted.status == 'closed':
        raise HTTPException(status_code=400, detail="마감된 wanted 요청의 마감일은 변경할 수 없습니다.")
    
    wanted.exp_date = req.exp_date
    db.commit()
    
    return {"message": "마감일이 성공적으로 변경되었습니다."}

# ========== 발행 관련 API ==========

class PublishRequest(BaseModel):
    schedule_id: str
    issue_comment: str = None

# [Roster] - 근무표 발행
@router.post("/roster/publish")
async def publish_roster(
    req: PublishRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Get current nurse info
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse:
        raise HTTPException(status_code=404, detail="간호사 정보를 찾을 수 없습니다.")

    # Get schedule to publish
    schedule = db.query(Schedule).filter(
        Schedule.schedule_id == req.schedule_id,
        Schedule.group_id == current_user.group_id
    ).first()
    
    if not schedule:
        raise HTTPException(status_code=404, detail="해당 스케줄을 찾을 수 없습니다.")

    # Check if this is the first publication
    existing_issued = db.query(IssuedRoster).filter(
        IssuedRoster.group_id == current_user.group_id,
        IssuedRoster.office_id == nurse.group.office_id
    ).first()
    
    is_first_issue = not existing_issued
    
    # Get next sequence number
    max_seq = db.query(func.max(IssuedRoster.seq_no)).filter(
        IssuedRoster.group_id == current_user.group_id,
        IssuedRoster.office_id == nurse.group.office_id
    ).scalar() or 0
    
    # Set all other schedules in this month to draft
    db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == schedule.year,
        Schedule.month == schedule.month,
        Schedule.status == 'issued'
    ).update({"status": "draft"})
    
    # Update current schedule to issued
    schedule.status = 'issued'
    
    # Create issued roster record
    issued_roster = IssuedRoster(
        seq_no=max_seq + 1,
        office_id=nurse.group.office_id,
        group_id=current_user.group_id,
        nurse_id=current_user.nurse_id,
        version=schedule.version,
        v_name=f"v{schedule.version}",  # 기본 버전명
        issue_cmmt=req.issue_comment if not is_first_issue else "첫 발행",
        schedule_id=req.schedule_id
    )
    
    db.add(issued_roster)
    db.commit()
    
    return {
        "message": "근무표가 성공적으로 발행되었습니다.",
        "seq_no": issued_roster.seq_no,
        "is_first_issue": is_first_issue
    } 