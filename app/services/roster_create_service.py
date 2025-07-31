"""
근무표 생성 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공, 엔진 호출 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Nurse, ShiftPreference, RosterConfig, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage, Schedule
from schemas.roster_schema import RosterRequest
from routers.utils import get_days_in_month, Timer
from datetime import date
import uuid
from sqlalchemy import func

# CP-SAT 기반 엔진들 import
try:
    from services.random_sampling import generate_roster
    from services.cp_sat_basic import generate_roster_cp_sat
    from services.cp_sat_main_v3 import generate_roster_cp_sat_main_v3
    from services.cp_sat_main_v2 import generate_roster_cp_sat_main_v2
    from services.cp_sat_adaptive import generate_roster_cp_sat_adaptive
    CPSAT_AVAILABLE = True
    CPSAT_MAIN_V3_AVAILABLE = True
    CPSAT_MAIN_V2_AVAILABLE = True
    CPSAT_ADAPTIVE_AVAILABLE = True
except ImportError as e:
    print(f"CP-SAT 엔진 import 실패: {e}")
    CPSAT_AVAILABLE = False
    CPSAT_MAIN_V3_AVAILABLE = False
    CPSAT_MAIN_V2_AVAILABLE = False
    CPSAT_ADAPTIVE_AVAILABLE = False

def generate_roster_service(req: RosterRequest, current_user, db: Session):
    """
    근무표 생성 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    if not wanted:
        raise Exception("해당 월의 wanted 작성을 먼저 요청해주세요.")
    schedule = request_schedule_service(req, current_user, db)
    nurses_in_group = db.query(Nurse).filter(Nurse.group_id == current_user.group_id).order_by(Nurse.experience.desc(), Nurse.nurse_id.asc()).all()
    nurse_ids = [n.nurse_id for n in nurses_in_group]
    preferences = []
    for nurse_id in nurse_ids:
        submitted_pref = db.query(ShiftPreference).filter(
            ShiftPreference.nurse_id == nurse_id,
            ShiftPreference.year == req.year,
            ShiftPreference.month == req.month,
            ShiftPreference.is_submitted == True
        ).order_by(ShiftPreference.submitted_at.desc()).first()
        if submitted_pref:
            preferences.append(submitted_pref)
        else:
            draft_pref = db.query(ShiftPreference).filter(
                ShiftPreference.nurse_id == nurse_id,
                ShiftPreference.year == req.year,
                ShiftPreference.month == req.month,
                ShiftPreference.is_submitted == False
            ).order_by(ShiftPreference.created_at.desc()).first()
            if draft_pref:
                preferences.append(draft_pref)
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.group_id == current_user.group_id
    ).order_by(RosterConfig.created_at.desc()).first()
    ####
    shift_manage_data = db.query(ShiftManage).filter(
        ShiftManage.office_id == current_user.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN'        
    ).order_by(ShiftManage.shift_slot.asc()).all()
    print('\n\n\n\nshift_manage_data', shift_manage_data, '\n\n\n\n')
    ####
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN'
    ).order_by(ShiftManage.shift_slot.asc()).all()
    shift_manage_data = [s.__dict__ for s in shift_manages]
    print('\n\n\n\nshift_manage_data', shift_manage_data, '\n\n\n\n')
    daily_shift_requirements = {}
    for shift_manage in shift_manages:
        if shift_manage.codes:
            for code in shift_manage.codes:
                daily_shift_requirements[code] = shift_manage.manpower
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]
    config_dict = latest_config.__dict__ if latest_config else {}
    config_dict['daily_shift_requirements'] = daily_shift_requirements
    if req.algorithm == "cp_sat" and CPSAT_AVAILABLE:
        try:
            with Timer("CP-SAT 엔진으로 근무표 생성"):
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
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
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
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
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
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
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
                )
            else:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    elif req.algorithm == "random_sampling":
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    else:
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
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
    shifts_db = db.query(Shift).all()
    shift_colors = {s.shift_id: s.color for s in shifts_db}
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).all()
    roster_data = {
        "year": req.year, 
        "month": req.month,
        "schedule_id": schedule.schedule_id,
        "days_in_month": get_days_in_month(req.year, req.month),
        "shift_colors": shift_colors,
        "nurses": [],
        "violations": []
    }
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

def generate_roster_service_with_fixed_cells(req, current_user, db: Session):
    """
    고정된 셀을 반영한 근무표 생성 서비스 함수
    req: ex. year=2027 month=3 fixed_cells=[{'nurse_index': 0, 'day_index': 11, 'shift': 'D'}] 
    """
  
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    
    # 고정된 셀 정보 추출
    fixed_cells = req.fixed_cells
    print(f"고정된 셀 개수: {len(fixed_cells)}")
    
    wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    if not wanted:
        raise Exception("해당 월의 wanted 작성을 먼저 요청해주세요.")
    
    schedule = request_schedule_service(req, current_user, db)
    nurses_in_group = db.query(Nurse).filter(Nurse.group_id == current_user.group_id).order_by(Nurse.experience.desc(), Nurse.nurse_id.asc()).all()
    nurse_ids = [n.nurse_id for n in nurses_in_group]

    preferences = []
    for nurse_id in nurse_ids:
        submitted_pref = db.query(ShiftPreference).filter(
            ShiftPreference.nurse_id == nurse_id,
            ShiftPreference.year == req.year,
            ShiftPreference.month == req.month,
            ShiftPreference.is_submitted == True
        ).order_by(ShiftPreference.submitted_at.desc()).first()
        if submitted_pref:
            preferences.append(submitted_pref)
        else:
            draft_pref = db.query(ShiftPreference).filter(
                ShiftPreference.nurse_id == nurse_id,
                ShiftPreference.year == req.year,
                ShiftPreference.month == req.month,
                ShiftPreference.is_submitted == False
            ).order_by(ShiftPreference.created_at.desc()).first()
            if draft_pref:
                preferences.append(draft_pref)
    
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.group_id == current_user.group_id
    ).order_by(RosterConfig.created_at.desc()).first()
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
    
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN'
    ).order_by(ShiftManage.shift_slot.asc()).all()
    shift_manage_data = [s.__dict__ for s in shift_manages]
    print('\n\n\n\nshift_manage_data', shift_manage_data, '\n\n\n\n')
    # grouped = {}
    # for row in shift_manage_data:
    #     main = row['main_code']
    #     grouped.setdefault(main, []).extend(row.get('codes', []))
    # print('\n\n\n\n\ngrouped', grouped, '\n\n\n\n\n')
    daily_shift_requirements = {}
    for shift_manage in shift_manages:
        if shift_manage.codes:
            for code in shift_manage.codes:
                daily_shift_requirements[code] = shift_manage.manpower
    
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]
    config_dict = latest_config.__dict__ if latest_config else {}
    config_dict['daily_shift_requirements'] = daily_shift_requirements
    
    # 고정된 셀 정보를 config에 추가
    config_dict['fixed_cells'] = fixed_cells
    print(f"고정된 셀 정보: {fixed_cells}")
    
    # 기본적으로 CP-SAT Adaptive 엔진 사용 (고정된 셀이 있을 때는 더 정교한 최적화 필요)
    if CPSAT_AVAILABLE:
        try:
            with Timer("CP-SAT 엔진으로 고정 셀 반영 근무표 생성"):
                print('이쪽으로 왔음')
                generated = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=300
                )
        except Exception as e:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
    
    # 기존 스케줄 엔트리 삭제
    db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).delete()
    
    # 새로운 스케줄 엔트리 생성
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
    
    # 결과 데이터 구성
    shifts_db = db.query(Shift).all()
    shift_colors = {s.shift_id: s.color for s in shifts_db}
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.schedule_id).all()
    
    roster_data = {
        "year": req.year, 
        "month": req.month,
        "schedule_id": schedule.schedule_id,
        "days_in_month": get_days_in_month(req.year, req.month),
        "shift_colors": shift_colors,
        "nurses": [],
        "violations": []
    }
    
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
    
    print(f"고정된 셀을 반영한 근무표 생성 완료: {len(fixed_cells)}개 셀 고정")
    return roster_data

def request_schedule_service(req: RosterRequest, current_user, db: Session):
    """
    스케줄 생성 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    latest_config = db.query(RosterConfig).filter(
        RosterConfig.office_id == nurse.group.office_id,
        RosterConfig.group_id == nurse.group_id
    ).order_by(RosterConfig.created_at.desc()).first()
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
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
        status='draft'
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    db.commit()
    return new_schedule 