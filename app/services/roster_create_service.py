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

# ───────────────────────────── 공통 헬퍼 ─────────────────────────────

def _collect_nurses_and_preferences(db: Session, req: RosterRequest, current_user):
    """그룹 내 간호사 목록과 선호도(제출본 우선)를 수집한다."""
    nurses_in_group = (
        db.query(Nurse)
        .filter(Nurse.group_id == current_user.group_id)
        .order_by(Nurse.experience.desc(), Nurse.nurse_id.asc())
        .all()
    )
    nurse_ids = [n.nurse_id for n in nurses_in_group]

    preferences = []
    for nurse_id in nurse_ids:
        submitted_pref = (
            db.query(ShiftPreference)
            .filter(
                ShiftPreference.nurse_id == nurse_id,
                ShiftPreference.year == req.year,
                ShiftPreference.month == req.month,
                ShiftPreference.is_submitted == True,
            )
            .order_by(ShiftPreference.submitted_at.desc())
            .first()
        )
        if submitted_pref:
            preferences.append(submitted_pref)
        else:
            draft_pref = (
                db.query(ShiftPreference)
                .filter(
                    ShiftPreference.nurse_id == nurse_id,
                    ShiftPreference.year == req.year,
                    ShiftPreference.month == req.month,
                    ShiftPreference.is_submitted == False,
                )
                .order_by(ShiftPreference.created_at.desc())
                .first()
            )
            if draft_pref:
                preferences.append(draft_pref)
    return nurses_in_group, preferences


def _fetch_latest_config(db: Session, req: RosterRequest, current_user):
    """요청의 config_id 우선, 없으면 그룹 최신 config을 가져온다."""
    if req.config_id:
        latest_config = (
            db.query(RosterConfig).filter(RosterConfig.config_id == req.config_id).first()
        )
    else:
        latest_config = (
            db.query(RosterConfig)
            .filter(RosterConfig.group_id == current_user.group_id)
            .order_by(RosterConfig.created_at.desc())
            .first()
        )
    if not latest_config:
        raise Exception("설정값을 입력해주세요")
    if not latest_config.config_version:
        raise Exception("설정 버전이 없습니다.")
    return latest_config


def _build_shift_manage_and_requirements(db: Session, current_user, latest_config):
    """ShiftManage에서 인원·코드 정보를 읽어 engine용 데이터와 요구인원을 구성한다."""
    shift_manages = (
        db.query(ShiftManage)
        .filter(
            ShiftManage.office_id == current_user.office_id,
            ShiftManage.group_id == current_user.group_id,
            ShiftManage.nurse_class == 'RN',
            ShiftManage.config_version == latest_config.config_version,
        )
        .order_by(ShiftManage.shift_slot.asc())
        .all()
    )
    shift_manage_data = [s.__dict__ for s in shift_manages]

    daily_shift_requirements = {}
    for sm in shift_manages:
        if sm.codes:
            for code in sm.codes:
                daily_shift_requirements[code] = sm.manpower
    return shift_manage_data, daily_shift_requirements


def _run_cp_sat_basic(nurses_in_group, preferences, latest_config, req, shift_manage_data, fixed_cells=None, time_limit_seconds=60):
    """cp_sat_basic 엔진 호출을 표준화한다."""
    nurses_dict = [n.__dict__ for n in nurses_in_group]
    prefs_dict = [p.__dict__ for p in preferences]

    config_dict = latest_config.__dict__ if latest_config else {}
    # ShiftManage 요구인원은 호출부에서 주입한다
    # fixed_cells 는 옵션
    if fixed_cells:
        config_dict['fixed_cells'] = fixed_cells

    print("cp_sat_basic 엔진 호출 준비 완료")
    cp_sat_result = generate_roster_cp_sat(
        nurses_dict,
        prefs_dict,
        config_dict,
        req.year,
        req.month,
        shift_manage_data,
        time_limit_seconds=time_limit_seconds,
    )

    if isinstance(cp_sat_result, dict) and "roster" in cp_sat_result:
        return (
            cp_sat_result["roster"],
            cp_sat_result.get("satisfaction_data", {}),
            cp_sat_result.get("roster_system"),
        )
    # 구형 반환 형식 호환
    return cp_sat_result, {}, None


def _persist_entries(db: Session, schedule, generated, req):
    """생성된 근무표를 ScheduleEntry로 저장한다."""
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
                    shift_id=shift_id.upper(),
                )
                db.add(entry)
    db.commit()


def _build_roster_response(db: Session, schedule, req, nurses_in_group):
    """프론트에서 쓰는 roster_data 형태로 응답을 구성한다."""
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
        "violations": [],
    }

    entries_by_nurse = {}
    for entry in entries:
        if entry.nurse_id not in entries_by_nurse:
            entries_by_nurse[entry.nurse_id] = {}
        entries_by_nurse[entry.nurse_id][entry.work_date.day] = entry.shift_id

    for nurse in nurses_in_group:
        nurse_schedule = [
            entries_by_nurse.get(nurse.nurse_id, {}).get(d, '-')
            for d in range(1, roster_data["days_in_month"] + 1)
        ]
        counts = {shift: nurse_schedule.count(shift) for shift in shift_colors.keys()}
        roster_data["nurses"].append(
            {
                "id": nurse.nurse_id,
                "name": nurse.name,
                "experience": nurse.experience,
                "schedule": nurse_schedule,
                "counts": counts,
            }
        )
    return roster_data


# ───────────────────────────── 서비스 함수 ─────────────────────────────

def generate_roster_service(req: RosterRequest, current_user, db: Session):
    """
    근무표 생성 서비스 함수 (cp_sat_basic 엔진만 사용)
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    wanted = (
        db.query(Wanted)
        .filter(
            Wanted.group_id == current_user.group_id,
            Wanted.year == req.year,
            Wanted.month == req.month,
        )
        .first()
    )
    if not wanted:
        raise Exception("해당 월의 wanted 작성을 먼저 요청해주세요.")

    schedule = request_schedule_service(req, current_user, db)

    nurses_in_group, preferences = _collect_nurses_and_preferences(db, req, current_user)
    latest_config = _fetch_latest_config(db, req, current_user)
    shift_manage_data, daily_shift_requirements = _build_shift_manage_and_requirements(
        db, current_user, latest_config
    )

    # daily_shift_requirements를 config에 주입해서 엔진 호출
    config_dict = latest_config.__dict__ if latest_config else {}
    config_dict['daily_shift_requirements'] = daily_shift_requirements

    print("cp_sat_basic 엔진으로 근무표 생성 시작")
    generated, satisfaction_data, roster_system = _run_cp_sat_basic(
        nurses_in_group,
        preferences,
        latest_config,
        req,
        shift_manage_data,
        fixed_cells=None,
        time_limit_seconds=60,
    )

    _persist_entries(db, schedule, generated, req)
    roster_data = _build_roster_response(db, schedule, req, nurses_in_group)
    return roster_data


def generate_roster_service_with_fixed_cells(req, current_user, db: Session):
    """
    고정된 셀을 반영한 근무표 생성 서비스 함수 (cp_sat_basic 엔진만 사용)
    req: ex. year=2027 month=3 fixed_cells=[{'nurse_index': 0, 'day_index': 11, 'shift': 'D'}]
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    fixed_cells = req.fixed_cells
    print(f"고정된 셀 개수: {len(fixed_cells)}")

    wanted = (
        db.query(Wanted)
        .filter(
            Wanted.group_id == current_user.group_id,
            Wanted.year == req.year,
            Wanted.month == req.month,
        )
        .first()
    )
    if not wanted:
        raise Exception("해당 월의 wanted 작성을 먼저 요청해주세요.")

    schedule = request_schedule_service(req, current_user, db)

    nurses_in_group, preferences = _collect_nurses_and_preferences(db, req, current_user)
    latest_config = _fetch_latest_config(db, req, current_user)
    shift_manage_data, daily_shift_requirements = _build_shift_manage_and_requirements(
        db, current_user, latest_config
    )

    # fixed_cells 및 요구인원 설정 반영
    config_dict = latest_config.__dict__ if latest_config else {}
    config_dict['daily_shift_requirements'] = daily_shift_requirements

    print("cp_sat_basic 엔진으로 고정 셀 반영 근무표 생성 시작")
    generated, satisfaction_data, roster_system = _run_cp_sat_basic(
        nurses_in_group,
        preferences,
        latest_config,
        req,
        shift_manage_data,
        fixed_cells=fixed_cells,
        time_limit_seconds=300,
    )

    _persist_entries(db, schedule, generated, req)
    roster_data = _build_roster_response(db, schedule, req, nurses_in_group)

    # 기존 로직 유지: 대시보드 분석 데이터 저장 시도 (있으면 사용)
    try:
        from services.dashboard_service import save_roster_analytics
        if roster_system:
            print("CP-SAT 엔진 결과를 사용하여 대시보드 분석 데이터 저장 중...")
            save_roster_analytics(schedule.schedule_id, roster_system, db)
            print("대시보드 분석 데이터 저장 완료")
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
        status='draft',
        dropped=False
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    db.commit()
    return new_schedule 