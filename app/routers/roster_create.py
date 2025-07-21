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


# CP-SAT 기반 엔진들 import
try:
    from cp_sat_basic import generate_roster_cp_sat
    # from cp_sat_main_v3 import generate_roster_cp_sat_main_v3
    # from cp_sat_main_v2 import generate_roster_cp_sat_main_v2
    # from cp_sat_adaptive import generate_roster_cp_sat_adaptive
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
@router.post("/roster/generate")
async def generate_roster_endpoint(
    req: RosterRequest,
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
    print('여까진옵니다', CPSAT_AVAILABLE, req.algorithm)
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
        print('여까진옵니다4')
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    else:
        print('여까진옵니다5')
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


    # [Schedules] - 수간호사가 근무표 생성 요청
@router.post("/roster/request")
async def request_schedule(
    req: RosterRequest,
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

    # for shift_data in default_shifts:
    #     exists = db.query(Shift).filter(Shift.shift_id == shift_data['shift_id']).first()
    #     if not exists:
    #         db.add(Shift(**shift_data))
    db.commit()

    return new_schedule


    