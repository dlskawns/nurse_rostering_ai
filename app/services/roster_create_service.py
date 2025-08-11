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
    if req.config_id:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.config_id == req.config_id
        ).first()
    else:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.group_id == current_user.group_id
        ).order_by(RosterConfig.created_at.desc()).first()
    ####
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
    
    # config_version을 사용하여 ShiftManage 조회
    config_version = latest_config.config_version
    if not config_version:
        raise Exception("설정 버전이 없습니다.")
        
    shift_manage_data = db.query(ShiftManage).filter(
        ShiftManage.office_id == current_user.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN',
        ShiftManage.config_version == config_version
    ).order_by(ShiftManage.shift_slot.asc()).all()
    print('\n\n\n\nshift_manage_data', shift_manage_data, '\n\n\n\n')
    ####
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN',
        ShiftManage.config_version == config_version
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
                cp_sat_result = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
                )
                # CP-SAT 엔진에서 반환된 결과 처리
                if isinstance(cp_sat_result, dict) and "roster" in cp_sat_result:
                    generated = cp_sat_result["roster"]
                    satisfaction_data = cp_sat_result.get("satisfaction_data", {})
                    roster_system = cp_sat_result.get("roster_system")
                else:
                    # 기존 형식으로 반환된 경우
                    generated = cp_sat_result
                    satisfaction_data = {}
                    roster_system = None
        except Exception as e:
            print("기존 엔진으로 폴백합니다.", e)
            generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
            satisfaction_data = {}
            roster_system = None
    elif req.algorithm == "cp_sat_main_v3" and CPSAT_MAIN_V3_AVAILABLE:
        try:
            with Timer("CP-SAT Main V3 엔진으로 근무표 생성"):
                cp_sat_result = generate_roster_cp_sat_main_v3(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, time_limit_seconds=90
                )
                # CP-SAT 엔진에서 반환된 결과 처리
                if isinstance(cp_sat_result, dict) and "roster" in cp_sat_result:
                    generated = cp_sat_result["roster"]
                    satisfaction_data = cp_sat_result.get("satisfaction_data", {})
                    roster_system = cp_sat_result.get("roster_system")
                else:
                    generated = cp_sat_result
                    satisfaction_data = {}
                    roster_system = None
        except Exception as e:
            print("CP-SAT 기본 엔진으로 폴백합니다.")
            if CPSAT_AVAILABLE:
                cp_sat_result = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=60
                )
                if isinstance(cp_sat_result, dict) and "roster" in cp_sat_result:
                    generated = cp_sat_result["roster"]
                    satisfaction_data = cp_sat_result.get("satisfaction_data", {})
                    roster_system = cp_sat_result.get("roster_system")
                else:
                    generated = cp_sat_result
                    satisfaction_data = {}
                    roster_system = None
            else:
                print("기존 엔진으로 폴백합니다.")
                generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
                satisfaction_data = {}
                roster_system = None
    elif req.algorithm == "random_sampling":
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
        satisfaction_data = {}
        roster_system = None
    else:
        generated = generate_roster(nurses_dict, prefs_dict, req.year, req.month)
        satisfaction_data = {}
        roster_system = None
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
    
    # 대시보드 분석 데이터 저장
    try:
        from services.dashboard_service import save_roster_analytics
        
        if roster_system:
            # CP-SAT 엔진에서 생성된 roster_system 객체가 있는 경우
            print("CP-SAT 엔진 결과를 사용하여 대시보드 분석 데이터 저장 중...")
            save_roster_analytics(schedule.schedule_id, roster_system, db)
            print("대시보드 분석 데이터 저장 완료")
        else:
            # roster_system이 없는 경우 (기존 엔진 사용 시)
            print("기존 엔진 결과를 사용하여 대시보드 분석 데이터 저장 중...")
            # 간호사 객체 생성
            from services.roster_system import RosterSystem
            from db.roster_config import NurseRosterConfig
            from db.nurse_config import Nurse as NurseConfig
            
            nurses_for_analysis = []
            for n in nurses_in_group:
                nurse_config = NurseConfig(
                    id=len(nurses_for_analysis),
                    db_id=n.nurse_id,
                    name=n.name,
                    experience_years=n.experience,
                    is_head_nurse=n.is_head_nurse,
                    is_night_nurse=getattr(n, 'is_night_nurse', False),
                    personal_off_adjustment=0,
                    remaining_off_days=0
                )
                nurses_for_analysis.append(nurse_config)
            
            # 설정 객체 생성
            config_for_analysis = NurseRosterConfig(
                daily_shift_requirements=daily_shift_requirements,
                min_experience_per_shift=latest_config.min_exp_per_shift,
                required_experienced_nurses=latest_config.req_exp_nurses,
                max_night_shifts_per_month=latest_config.max_nig_per_month,
                max_consecutive_nights=3 if latest_config.three_seq_nig else 2,
                max_consecutive_work_days=latest_config.max_conseq_work,
                banned_day_after_eve=latest_config.banned_day_after_eve,
                two_offs_after_three_nig=latest_config.two_offs_after_three_nig,
                two_offs_after_two_nig=latest_config.two_offs_after_two_nig,
                sequential_offs=latest_config.sequential_offs,
                even_nights=latest_config.even_nights
            )
            
            # RosterSystem 객체 생성
            roster_system = RosterSystem(
                nurses=nurses_for_analysis,
                target_month=date(req.year, req.month, 1),
                config=config_for_analysis
            )
            
            # 생성된 근무표 데이터를 roster_system에 설정
            import numpy as np
            roster_system.roster = np.zeros((len(nurses_for_analysis), roster_system.num_days, len(roster_system.config.shift_types)))
            
            # 생성된 결과를 roster_system.roster에 반영
            shift_type_to_index = {shift: i for i, shift in enumerate(roster_system.config.shift_types)}
            for nurse_idx, nurse in enumerate(nurses_for_analysis):
                if nurse.db_id in generated:
                    shifts = generated[nurse.db_id]
                    for day_idx, shift in enumerate(shifts):
                        if shift != '-' and day_idx < roster_system.num_days:
                            shift_upper = shift.upper()
                            if shift_upper == 'O':
                                shift_upper = 'OFF'
                            if shift_upper in shift_type_to_index:
                                roster_system.roster[nurse_idx, day_idx, shift_type_to_index[shift_upper]] = 1
            
            # 선호도 매트릭스 설정 (기본값)
            roster_system.preference_matrix = np.zeros((len(nurses_for_analysis), roster_system.num_days, len(roster_system.config.shift_types)))
            
            # 분석 데이터 저장
            save_roster_analytics(schedule.schedule_id, roster_system, db)
            print("기존 엔진 대시보드 분석 데이터 저장 완료")
            
    except ImportError as e:
        print(f"대시보드 서비스를 찾을 수 없습니다: {e}")
    except Exception as e:
        print(f"대시보드 분석 데이터 저장 실패: {e}")
    
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
    
    # config_id가 제공된 경우 해당 config 사용, 아니면 최신 config 사용
    if  req.config_id:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.config_id == req.config_id
        ).first()
    else:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.group_id == current_user.group_id
        ).order_by(RosterConfig.created_at.desc()).first()
    
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
    
    # config_version을 사용하여 ShiftManage 조회
    config_version = latest_config.config_version
    if not config_version:
        raise Exception("설정 버전이 없습니다.")
    
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    
    shift_manages = db.query(ShiftManage).filter(
        ShiftManage.office_id == nurse.group.office_id,
        ShiftManage.group_id == current_user.group_id,
        ShiftManage.nurse_class == 'RN',
        ShiftManage.config_version == config_version
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
    
    # 고정된 셀 정보를 config에 추가
    config_dict['fixed_cells'] = fixed_cells
    print(f"고정된 셀 정보: {fixed_cells}")
    
    # 기본적으로 CP-SAT Adaptive 엔진 사용 (고정된 셀이 있을 때는 더 정교한 최적화 필요)
    satisfaction_data = {}
    roster_system = None
    
    if CPSAT_AVAILABLE:
        try:
            with Timer("CP-SAT 엔진으로 고정 셀 반영 근무표 생성"):
                print('이쪽으로 왔음')
                cp_sat_result = generate_roster_cp_sat(
                    nurses_dict, prefs_dict, config_dict, req.year, req.month, shift_manage_data, time_limit_seconds=300
                )
                # CP-SAT 엔진에서 반환된 결과 처리
                if isinstance(cp_sat_result, dict) and "roster" in cp_sat_result:
                    generated = cp_sat_result["roster"]
                    satisfaction_data = cp_sat_result.get("satisfaction_data", {})
                    roster_system = cp_sat_result.get("roster_system")
                else:
                    generated = cp_sat_result
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
    
    # 대시보드 분석 데이터 저장
    try:
        from services.dashboard_service import save_roster_analytics
        
        if roster_system:
            # CP-SAT 엔진에서 생성된 roster_system 객체가 있는 경우
            print("CP-SAT 엔진 결과를 사용하여 대시보드 분석 데이터 저장 중...")
            save_roster_analytics(schedule.schedule_id, roster_system, db)
            print("대시보드 분석 데이터 저장 완료")
        else:
            # roster_system이 없는 경우 (기존 엔진 사용 시)
            print("기존 엔진 결과를 사용하여 대시보드 분석 데이터 저장 중...")
            # 간호사 객체 생성
            from services.roster_system import RosterSystem
            from db.roster_config import NurseRosterConfig
            from db.nurse_config import Nurse as NurseConfig
            
            nurses_for_analysis = []
            for n in nurses_in_group:
                nurse_config = NurseConfig(
                    id=len(nurses_for_analysis),
                    db_id=n.nurse_id,
                    name=n.name,
                    experience_years=n.experience,
                    is_head_nurse=n.is_head_nurse,
                    is_night_nurse=getattr(n, 'is_night_nurse', False),
                    personal_off_adjustment=0,
                    remaining_off_days=0
                )
                nurses_for_analysis.append(nurse_config)
            
            # 설정 객체 생성
            config_for_analysis = NurseRosterConfig(
                daily_shift_requirements=daily_shift_requirements,
                min_experience_per_shift=latest_config.min_exp_per_shift,
                required_experienced_nurses=latest_config.req_exp_nurses,
                max_night_shifts_per_month=latest_config.max_nig_per_month,
                max_consecutive_nights=3 if latest_config.three_seq_nig else 2,
                max_consecutive_work_days=latest_config.max_conseq_work,
                banned_day_after_eve=latest_config.banned_day_after_eve,
                two_offs_after_three_nig=latest_config.two_offs_after_three_nig,
                two_offs_after_two_nig=latest_config.two_offs_after_two_nig,
                sequential_offs=latest_config.sequential_offs,
                even_nights=latest_config.even_nights
            )
            
            # RosterSystem 객체 생성
            roster_system = RosterSystem(
                nurses=nurses_for_analysis,
                target_month=date(req.year, req.month, 1),
                config=config_for_analysis
            )
            
            # 생성된 근무표 데이터를 roster_system에 설정
            import numpy as np
            roster_system.roster = np.zeros((len(nurses_for_analysis), roster_system.num_days, len(roster_system.config.shift_types)))
            
            # 생성된 결과를 roster_system.roster에 반영
            shift_type_to_index = {shift: i for i, shift in enumerate(roster_system.config.shift_types)}
            for nurse_idx, nurse in enumerate(nurses_for_analysis):
                if nurse.db_id in generated:
                    shifts = generated[nurse.db_id]
                    for day_idx, shift in enumerate(shifts):
                        if shift != '-' and day_idx < roster_system.num_days:
                            shift_upper = shift.upper()
                            if shift_upper == 'O':
                                shift_upper = 'OFF'
                            if shift_upper in shift_type_to_index:
                                roster_system.roster[nurse_idx, day_idx, shift_type_to_index[shift_upper]] = 1
            
            # 선호도 매트릭스 설정 (기본값)
            roster_system.preference_matrix = np.zeros((len(nurses_for_analysis), roster_system.num_days, len(roster_system.config.shift_types)))
            
            # 분석 데이터 저장
            save_roster_analytics(schedule.schedule_id, roster_system, db)
            print("기존 엔진 대시보드 분석 데이터 저장 완료")
            
    except ImportError as e:
        print(f"대시보드 서비스를 찾을 수 없습니다: {e}")
    except Exception as e:
        print(f"대시보드 분석 데이터 저장 실패: {e}")
    
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
    # config_id가 제공된 경우 해당 config 사용, 아니면 최신 config 사용
    if req.config_id:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.config_id == req.config_id
        ).first()
    else:
        latest_config = db.query(RosterConfig).filter(
            RosterConfig.office_id == nurse.group.office_id,
            RosterConfig.group_id == nurse.group_id
        ).order_by(RosterConfig.created_at.desc()).first()
    print('\n\n\n\n\nlatest_config여길봐', latest_config.config_id, latest_config.config_version, latest_config.day_req,'\n\n\n\n\n')
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