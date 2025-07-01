from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
import uuid
from datetime import datetime, date
from fastapi.responses import RedirectResponse
import numpy as np

from app.db.client import get_db
from app.db.models import Schedule, ShiftPreference, Nurse, ScheduleEntry, Shift, Group, RosterConfig
from app.schemas.auth_schema import User as UserSchema
from app.routers.auth import get_current_user_from_cookie
from app.roster_engine import generate_roster, get_days_in_month
from app.routers.utils import Timer
from roster_system import RosterSystem
from nurse import Nurse as NurseEngine
from config import NurseRosterConfig
from app.routers.utils import parse_prefs_to_dict

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
    print('\n\n\n\n\nnurses_in_group', nurses_in_group)
    nurse_ids = [n.nurse_id for n in nurses_in_group]
    
    preferences = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id.in_(nurse_ids),
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month
    ).all()
    
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]
    print('\n\n\n\n\nnurses_dict', nurses_dict)
    print('\n\n\n\n\nprefs_dict', prefs_dict)
    # 3. Call the roster generation logic
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.group_id == current_user.group_id
    ).order_by(RosterConfig.created_at.desc()).first()

    with Timer("RosterSystem 초기화"):
        # `RosterSystem`에 맞는 데이터 구조로 변환
        nurses_for_engine = [NurseEngine.from_db_model(n, i) for i, n in enumerate(nurses_in_group)]
        
        # target_month를 date 객체로 생성
        target_month_date = date(req.year, req.month, 1)

        # DB에서 불러온 config를 NurseRosterConfig 객체로 변환
        roster_config_for_engine = NurseRosterConfig(
            daily_shift_requirements={
                'D': latest_config.day_req,
                'E': latest_config.eve_req,
                'N': latest_config.nig_req
            },
            min_experience_per_shift=latest_config.min_exp_per_shift,
            required_experienced_nurses=latest_config.req_exp_nurses,
            max_consecutive_work_days=latest_config.max_conseq_work,
            max_night_shifts_per_month=latest_config.max_nig_per_month,
            enforce_two_offs_per_week=latest_config.two_offs_per_week,
            shift_requirement_priority=latest_config.shift_priority,
            max_consecutive_nights=3 if latest_config.three_seq_nig else 2,
            global_monthly_off_days=2, # 하드코딩 필요
            standard_personal_off_days=latest_config.off_days - 2 if latest_config.off_days > 2 else 0 # 하드코딩 필요
        )

        roster_system = RosterSystem(
            nurses=nurses_for_engine,
            target_month=target_month_date,
            config=roster_config_for_engine
        )

    shift_preferences, off_requests, pair_preferences = parse_prefs_to_dict(prefs_dict)
    print('\n\n\n\n\npair_preferences', pair_preferences, '\n\n\n\n\n')
    print('\n\n\n\n\noff_requests', off_requests, '\n\n\n\n\n')
    print('\n\n\n\n\nshift_preferences', shift_preferences, '\n\n\n\n\n')
    with Timer("휴무 요청 적용"):
        # off_requests = {} # Placeholder
        # Example: off_requests = {"1": {"5": 10.0, "12": 10.0}}
        roster_system.apply_off_requests(off_requests)

    with Timer("선호 근무 유형 적용"):
        # shift_preferences = {} # Placeholder
        # Example: shift_preferences = {"1": {"D": {"4": 1.0, "5": 3.2}}}
        roster_system.apply_shift_preferences(shift_preferences)

    with Timer("페어링 선호도 적용"):
        pair_preferences = {
            "work_together": [], # e.g., [{"nurse_1": 1, "nurse_2": 5, "weight": 3.0}]
            "work_apart": []     # e.g., [{"nurse_1": 1, "nurse_2": 6, "weight": 3.0}]
        }
        roster_system.apply_pair_preferences(pair_preferences)

    with Timer("CP-SAT으로 최적화"):
        roster_system.optimize_roster_with_cp_sat_v2(time_limit_seconds=60)

    # with Timer("최적화 결과 출력"):
    #     print("--- 최적화된 근무표 지표 ---")
    #     metrics = roster_system.calculate_detailed_metrics()
    #     for key, value in metrics.items():
    #         if isinstance(value, dict):
    #             print(f"  {key}:")
    #             for sub_key, sub_value in value.items():
    #                 print(f"    {sub_key}: {sub_value}")
    #         else:
    #             print(f"  {key}: {value}")

    # # 4. Clear old entries and save new roster to DB
    # db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
    
    # shift_map = {i: s for i, s in enumerate(roster_system.config.shift_types)}

    # for n_idx, nurse_schedule in enumerate(roster_system.roster):
    #     nurse_db_id = roster_system.nurses[n_idx].db_id
    #     for day_idx, shift_vector in enumerate(nurse_schedule):
    #         shift_idx = np.where(shift_vector == 1)[0]
    #         if len(shift_idx) > 0:
    #             shift_id = shift_map[shift_idx[0]]
    #             work_date = date(req.year, req.month, day_idx + 1)
    #             entry = ScheduleEntry(
    #                 entry_id=str(uuid.uuid4().hex)[:16],
    #                 schedule_id=schedule.schedule_id,
    #                 nurse_id=nurse_db_id,
    #                 work_date=work_date,
    #                 shift_id=shift_id.upper()
    #             )
    #             db.add(entry)
    ###############
    
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
    ).order_by(Nurse.experience.desc()).all()

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

    # RosterSystem을 사용하여 위반사항 계산
    violations = []
    try:
        # DB에서 불러온 config를 NurseRosterConfig 객체로 변환
        latest_config_db = db.query(RosterConfig).filter(
            RosterConfig.group_id == current_user.group_id
        ).order_by(RosterConfig.created_at.desc()).first()
        print('1')
        roster_config_for_engine = NurseRosterConfig(
            daily_shift_requirements={
                'D': latest_config_db.day_req,
                'E': latest_config_db.eve_req,
                'N': latest_config_db.nig_req
            },
            max_consecutive_work_days=latest_config_db.max_conseq_work,
            max_night_shifts_per_month=latest_config_db.max_nig_per_month,
            max_consecutive_nights=3 if latest_config_db.three_seq_nig else 2
        )
        print('2')
        # 임시 RosterSystem 인스턴스 생성
        nurses_for_engine = [NurseEngine.from_db_model(n, i) for i, n in enumerate(db.query(Nurse).filter(Nurse.group_id == current_user.group_id).all())]
        print('3')
        system = RosterSystem(
            nurses=nurses_for_engine,
            target_month=date(year, month, 1),
            config=roster_config_for_engine
        )
        print('4')
        # 생성된 근무표를 RosterSystem에 맞게 변환하여 채워넣기
        shift_map = {s: i for i, s in enumerate(system.config.shift_types)}
        print('5')
        print('system.nurses', system.nurses)
        for nurse_idx, nurse in enumerate(system.nurses):
            nurse_schedule = entries_by_nurse.get(nurse.db_id, {})
            for day in range(system.num_days):
                day_key = day + 1
                shift = nurse_schedule.get(day_key, "O")
                shift_idx = shift_map.get(shift.upper())
                if shift_idx is None: # 'O' vs 'OFF' 처리
                    shift_idx = shift_map.get("OFF") if shift.upper() == "O" else shift_map.get("O")
                
                system.roster[nurse_idx, day, shift_idx] = 1
                
        # 위반사항 찾기
        violation_details = system._find_violations()
        print('7')
        # 위반사항 메시지 포맷팅 및 중복 제거
        violation_messages = set()
        for v in violation_details:
            if v['type'] == 'shift_requirement':
                violation_messages.add(f"{v['day']+1}일: {v['shift']} 근무 인원 미달 (필요: {v['required']}, 배정: {v['actual']})")
            elif v['type'] == 'consecutive':
                nurse_name = system.nurses[v['nurse_idx']].name
                violation_messages.add(f"{nurse_name}: 최대 연속 근무일 초과")
            elif v['type'] == 'night':
                 nurse_name = system.nurses[v['nurse_idx']].name
                 violation_messages.add(f"{nurse_name}: 야간 근무 제약 위반")
        print('8')
        violations = sorted(list(violation_messages))
        print('9')
    except Exception as e:
        print(f"위반사항 계산 중 오류 발생: {e}")

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

    # Update schedule status to 'issued'
    schedule.status = 'issued'
    db.commit()
    
    return {"message": "Roster saved successfully"}

# [Roster] - 근무표 위반사항 실시간 계산
@router.post("/roster/validate")
async def validate_roster(
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

    try:
        # Get roster configuration
        latest_config_db = db.query(RosterConfig).filter(
            RosterConfig.group_id == current_user.group_id
        ).order_by(RosterConfig.created_at.desc()).first()
        
        if not latest_config_db:
            return {"violations": ["근무표 설정을 찾을 수 없습니다."]}
        
        # Create RosterSystem configuration
        roster_config_for_engine = NurseRosterConfig(
            daily_shift_requirements={
                'D': latest_config_db.day_req,
                'E': latest_config_db.eve_req,
                'N': latest_config_db.nig_req
            },
            max_consecutive_work_days=latest_config_db.max_conseq_work,
            max_night_shifts_per_month=latest_config_db.max_nig_per_month,
            max_consecutive_nights=3 if latest_config_db.three_seq_nig else 2
        )
        
        # Get nurses for engine
        nurses_for_engine = [NurseEngine.from_db_model(n, i) for i, n in enumerate(db.query(Nurse).filter(Nurse.group_id == current_user.group_id).all())]
        
        # Create RosterSystem instance
        system = RosterSystem(
            nurses=nurses_for_engine,
            target_month=date(year, month, 1),
            config=roster_config_for_engine
        )
        
        # Convert roster data to RosterSystem format
        shift_map = {s: i for i, s in enumerate(system.config.shift_types)}
        
        # Initialize roster with zeros
        system.roster.fill(0)
        
        for nurse_idx, nurse_data in enumerate(roster):
            if nurse_idx >= len(system.nurses):
                continue
            schedule = nurse_data.get('schedule', [])
            for day_idx, shift in enumerate(schedule):
                if day_idx >= system.num_days:
                    continue
                shift_idx = shift_map.get(shift.upper())
                if shift_idx is not None:
                    system.roster[nurse_idx, day_idx, shift_idx] = 1
        
        # Find violations
        violation_details = system._find_violations()
        
        # Format violation messages
        violation_messages = set()
        for v in violation_details:
            if v['type'] == 'shift_requirement':
                violation_messages.add(f"{v['day']+1}일: {v['shift']} 근무 인원 미달 (필요: {v['required']}, 배정: {v['actual']})")
            elif v['type'] == 'consecutive':
                nurse_name = system.nurses[v['nurse_idx']].name
                violation_messages.add(f"{nurse_name}: 최대 연속 근무일 초과")
            elif v['type'] == 'night':
                nurse_name = system.nurses[v['nurse_idx']].name
                violation_messages.add(f"{nurse_name}: 야간 근무 제약 위반")
        
        violations = sorted(list(violation_messages))
        
        return {"violations": violations}
        
    except Exception as e:
        print(f"위반사항 계산 중 오류 발생: {e}")
        return {"violations": [f"위반사항 계산 중 오류가 발생했습니다: {str(e)}"]}

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