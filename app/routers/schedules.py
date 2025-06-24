from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
import uuid
from datetime import datetime, date
from fastapi.responses import RedirectResponse

from app.db.client import get_db
from app.db.models import Schedule, ShiftPreference, Nurse, ScheduleEntry, Shift, Group, RosterConfig
from app.schemas.auth_schema import User as UserSchema
from app.routers.auth import get_current_user_from_cookie
from app.roster_engine import generate_roster, get_days_in_month

router = APIRouter(
    prefix="/api",
    tags=["schedules"]
)

class ScheduleRequest(BaseModel):
    year: int
    month: int

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
        status='requested'
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    # Check and add default shifts if they don't exist
    default_shifts = [
        {'shift_id': 'D', 'name': 'Day', 'color': '#87CEEB'},
        {'shift_id': 'E', 'name': 'Evening', 'color': '#FFDAB9'},
        {'shift_id': 'N', 'name': 'Night', 'color': '#6A5ACD'},
        {'shift_id': 'O', 'name': 'Off', 'color': '#F5F5F5'},
    ]
    for shift_data in default_shifts:
        exists = db.query(Shift).filter(Shift.shift_id == shift_data['shift_id']).first()
        if not exists:
            db.add(Shift(**shift_data))
    db.commit()

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

    # Get submitted preferences for those nurses for the given month
    submitted_prefs = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id.in_(nurse_ids_in_group),
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).all()
    submitted_nurse_ids = {p.nurse_id for p in submitted_prefs}

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
    
    schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month
    ).order_by(Schedule.version.desc()).first()

    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month
    ).first()

    return {
        "schedule_status": schedule.status if schedule else None,
        "preference_is_submitted": preference.is_submitted if preference else False,
        "preference_data": preference.data if preference else None,
        "schedule_id": schedule.schedule_id if schedule else None
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
    
    # Check for existing preference
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == pref_data.year,
        ShiftPreference.month == pref_data.month
    ).first()
    
    if preference: # Update existing draft
        preference.data = pref_data.data
        preference.created_at = datetime.utcnow()
    else: # Create new draft
        preference = ShiftPreference(
            nurse_id=current_user.nurse_id,
            year=pref_data.year,
            month=pref_data.month,
            data=pref_data.data,
            is_submitted=False
        )
        db.add(preference)
    
    db.commit()
    return {"message": "Preference draft saved successfully"}

# [Preferences] - 선호도 최종 제출
@router.post("/preferences/submit")
async def submit_preferences(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month
    ).first()

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

    # Check for existing preference
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month
    ).first()

    if preference:
        # If a draft exists, just update it to be submitted
        preference.is_submitted = True
        preference.submitted_at = datetime.utcnow()
    else:
        # If no draft exists, create a new one with empty data
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

    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month
    ).first()

    if not preference:
        raise HTTPException(status_code=404, detail="No preference found to retract")

    preference.is_submitted = False
    db.commit()
    return {"message": "Submission retracted successfully"}

# [Roster] - 근무표 생성
@router.post("/roster/generate")
async def generate_roster_endpoint(
    req: ScheduleRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Ensure default shifts exist to prevent foreign key errors
    default_shifts = [
        {'shift_id': 'D', 'name': 'Day', 'color': '#87CEEB'},
        {'shift_id': 'E', 'name': 'Evening', 'color': '#FFDAB9'},
        {'shift_id': 'N', 'name': 'Night', 'color': '#6A5ACD'},
        {'shift_id': 'O', 'name': 'Off', 'color': '#F5F5F5'},
    ]
    for shift_data in default_shifts:
        exists = db.query(Shift).filter(Shift.shift_id == shift_data['shift_id']).first()
        if not exists:
            db.add(Shift(**shift_data))
    db.commit()

    # 1. Get latest schedule for the month
    schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == req.year,
        Schedule.month == req.month
    ).order_by(Schedule.version.desc()).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="No active schedule request found.")

    # 2. Fetch all nurses and their preferences
    nurses_in_group = db.query(Nurse).filter(Nurse.group_id == current_user.group_id).all()
    nurse_ids = [n.nurse_id for n in nurses_in_group]
    
    preferences = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id.in_(nurse_ids),
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month
    ).all()
    
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]

    # 3. Call the roster generation logic
    generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)

    # 4. Clear old entries and save new roster to DB
    db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
    
    for nurse_id, shifts in generated.items():
        for day_index, shift_id in enumerate(shifts):
            work_date = date(req.year, req.month, day_index + 1)
            entry = ScheduleEntry(
                entry_id=str(uuid.uuid4().hex)[:16],
                schedule_id=schedule.schedule_id,
                nurse_id=nurse_id,
                work_date=work_date,
                shift_id=shift_id.upper()
            )
            db.add(entry)

    # 5. Update schedule status to 'issued'
    schedule.status = 'issued'
    db.commit()
    
    # 6. Fetch and return the created roster for display
    return await get_roster_for_month(req.year, req.month, current_user, db)

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
    ).order_by(Nurse.name).all()

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

    for nurse in nurses_in_group:
        nurse_schedule = [entries_by_nurse.get(nurse.nurse_id, {}).get(d, 'O') for d in range(1, roster_data["days_in_month"] + 1)]
        
        counts = {shift: nurse_schedule.count(shift) for shift in shift_colors.keys()}
        
        roster_data["nurses"].append({
            "id": nurse.nurse_id,
            "name": nurse.name,
            "experience": nurse.experience,
            "schedule": nurse_schedule,
            "counts": counts
        })
        
    return roster_data 