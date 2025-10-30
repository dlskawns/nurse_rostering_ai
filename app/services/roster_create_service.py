"""
근무표 생성 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공, 엔진 호출 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Nurse, ShiftPreference, RosterConfig, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage, Schedule, NurseShiftRequest, NursePairRequest, WantedRequest, DailyShift
from schemas.roster_schema import RosterRequest
from routers.utils import get_days_in_month, Timer
from datetime import date
import uuid
from sqlalchemy import func
from collections import defaultdict
from db.client import get_db
# from db.client2 import _get_mssql_session


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

def _collect_nurses_and_preferences(db: Session, req, current_user):
    """그룹 내 간호사 목록과 선호도(제출본 우선)를 수집한다. (WantedRequest 기반)"""
    # 1️⃣ 그룹 내 간호사 목록
    nurses_in_group = (
        db.query(Nurse)
        .filter(Nurse.group_id == current_user.group_id)
        .order_by(Nurse.experience.desc(), Nurse.nurse_id.asc())
        .all()
    )

    nurse_ids = [n.nurse_id for n in nurses_in_group]
    month_str = f"{req.year}-{req.month:02d}"
    preferences = []

    # 2️⃣ 각 간호사별 submitted → draft 순으로 선호도 가져오기
    for nurse_id in nurse_ids:
        submitted_wr = (
            db.query(WantedRequest)
            .filter(
                WantedRequest.nurse_id == nurse_id,
                WantedRequest.month == month_str,
                WantedRequest.is_submitted == True
            )
            .order_by(WantedRequest.submitted_at.desc())
            .first()
        )

        target_wr = submitted_wr or (
            db.query(WantedRequest)
            .filter(
                WantedRequest.nurse_id == nurse_id,
                WantedRequest.month == month_str,
            )
            .order_by(WantedRequest.created_at.asc())
            .first()
        )

        if not target_wr:
            continue  # 기록이 없는 간호사는 건너뜀

        # 3️⃣ shift 데이터 수집
        shift_rows = (
            db.query(NurseShiftRequest)
            .filter(
                NurseShiftRequest.nurse_id == nurse_id,
                NurseShiftRequest.request_id == target_wr.request_id,
                # cast(NurseShiftRequest.shift_date, String).like(f"{month_str}-%"),
            )
            .all()
        )

        shift_data = {"D": {}, "E": {}, "N": {}, "O": {}}
        for s in shift_rows:
            shift_type = s.shift.upper()
            day = str(int(str(s.shift_date).split("-")[-1]))
            if shift_type in shift_data:
                shift_data[shift_type][day] = int(s.score) if s.score is not None else 0

        # 4️⃣ pair 데이터 수집
        pair_rows = (
            db.query(NursePairRequest)
            .filter(
                NursePairRequest.nurse_id == nurse_id,
                NursePairRequest.request_id == target_wr.request_id,
            )
            .all()
        )

        pair_data = [{"id": p.target_id, "weight": p.score} for p in pair_rows]

        # 5️⃣ data JSON 구성
        data_json = {
            "request": target_wr.request,
            "shift": {k: v for k, v in shift_data.items() if v},
            "preference": pair_data,
        }

        # 6️⃣ 기존 ShiftPreference 포맷으로 append
        preferences.append({
            "nurse_id": nurse_id,
            "year": req.year,
            "month": req.month,
            "is_submitted": bool(target_wr.is_submitted),
            "created_at": target_wr.created_at,
            "submitted_at": target_wr.submitted_at,
            "data": data_json,
        })

    # 7️⃣ 기존 함수와 동일하게 반환
    print("preferences", nurses_in_group, preferences)
    return nurses_in_group, preferences


# def _collect_nurses_and_preferences(db: Session, req: RosterRequest, current_user):
#     """그룹 내 간호사 목록과 선호도(제출본 우선)를 수집한다."""
#     nurses_in_group = (
#         db.query(Nurse)
#         .filter(Nurse.group_id == current_user.group_id)
#         .order_by(Nurse.experience.desc(), Nurse.nurse_id.asc())
#         .all()
#     )
#     nurse_ids = [n.nurse_id for n in nurses_in_group]

#     preferences = []
#     for nurse_id in nurse_ids:
#         submitted_pref = (
#             db.query(ShiftPreference)
#             .filter(
#                 ShiftPreference.nurse_id == nurse_id,
#                 ShiftPreference.year == req.year,
#                 ShiftPreference.month == req.month,
#                 ShiftPreference.is_submitted == True,
#             )
#             .order_by(ShiftPreference.submitted_at.desc())
#             .first()
#         )
#         if submitted_pref:
#             preferences.append(submitted_pref)
#         else:
#             draft_pref = (
#                 db.query(ShiftPreference)
#                 .filter(
#                     ShiftPreference.nurse_id == nurse_id,
#                     ShiftPreference.year == req.year,
#                     ShiftPreference.month == req.month,
#                     ShiftPreference.is_submitted == False,
#                 )
#                 .order_by(ShiftPreference.created_at.desc())
#                 .first()
#             )
#             if draft_pref:
#                 preferences.append(draft_pref)
#     return nurses_in_group, preferences


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
    return latest_config


def _build_shift_manage_and_requirements(db: Session, current_user, latest_config, req):
    """ShiftManage에서 인원·코드 정보를 읽어 engine용 데이터와 요구인원을 구성한다."""
    shift_manages = (
        db.query(ShiftManage)
        .filter(
            ShiftManage.office_id == current_user.office_id,
            ShiftManage.group_id == current_user.group_id,
            ShiftManage.nurse_class == 'RN',
            # ShiftManage.config_version == latest_config.config_version,
        )
        .order_by(ShiftManage.shift_slot.asc())
        .all()
    )
    shift_manage_data = [s.__dict__ for s in shift_manages]
    daily_shift_requirements = {}
    for sm in shift_manages:
        # if sm.codes:
        #     for code in sm.codes:
        # daily_shift_requirements[sm.main_code.strip()] = sm.manpower
        daily_shift_requirements[sm.main_code] = sm.manpower
    # ── DailyShift 일자별 요구치 조회 및 정규화 ──
    days_in_month = get_days_in_month(req.year, req.month)
    try:
        rows = (
            db.query(DailyShift)
            .filter(
                DailyShift.office_id == current_user.office_id,
                DailyShift.group_id == current_user.group_id,
                DailyShift.year == req.year,
                DailyShift.month == req.month,
            )
            .order_by(DailyShift.day.asc())
            .all()
        )
    except Exception as e:
        print(f"error: {e}")
    # day→counts 맵 구성 후 리스트로 변환(0-index)
    by_day = {r.day: {'D': int(r.d_count or 0), 'E': int(r.e_count or 0), 'N': int(r.n_count or 0)} for r in rows}
    daily_shift_requirements_by_day = [by_day.get(d, {'D': daily_shift_requirements.get('D', 0), 'E': daily_shift_requirements.get('E', 0), 'N': daily_shift_requirements.get('N', 0)}) for d in range(1, days_in_month + 1)]

    return shift_manage_data, daily_shift_requirements, daily_shift_requirements_by_day

def _normalize_to_main(code: str, code2main: dict) -> str:
    """세부 근무코드를 메인코드로 정규화한다."""
    if not code:
        return '-'
    c = str(code).upper()
    if c in ('O', 'OFF'):
        return 'O'
    return code2main.get(c, c)

def _get_prev_year_month(year: int, month: int) -> tuple[int, int]:
    """이전 달의 (year, month)를 반환한다."""
    if month > 1:
        return year, month - 1
    return year - 1, 12

def _query_prev_month_schedule_id(db: Session, group_id: str, year: int, month: int) -> str | None:
    """이전 달의 최종(issued 우선) schedule_id를 조회한다."""
    py, pm = _get_prev_year_month(year, month)
    # 1) IssuedRoster 우선
    issued = (
        db.query(IssuedRoster)
        .join(Schedule, IssuedRoster.schedule_id == Schedule.schedule_id)
        .filter(Schedule.group_id == group_id, Schedule.year == py, Schedule.month == pm)
        .order_by(IssuedRoster.issued_at.desc())
        .first()
    )
    if issued:
        return issued.schedule_id
    # 2) 없으면 해당 월의 최신 Schedule
    latest = (
        db.query(Schedule)
        .filter(Schedule.group_id == group_id, Schedule.year == py, Schedule.month == pm)
        .order_by(Schedule.version.desc())
        .first()
    )
    return latest.schedule_id if latest else None

def _get_last_days_map(db: Session, schedule_id: str, days: int, code2main: dict) -> dict:
    """해당 schedule_id의 마지막 N일 근무코드를 메인코드로 정규화하여 반환한다.
    반환: { nurse_id: ['E','N','O','D','N','O'] } (최대 길이 days, 과거→현재 순)
    """
    if not schedule_id:
        return {}
    # 해당 스케줄의 모든 엔트리 로딩
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule_id).all()
    by_nurse: dict[str, dict[int, str]] = defaultdict(dict)
    max_day = 0
    for e in entries:
        d = int(e.work_date.day)
        max_day = max(max_day, d)
        by_nurse[e.nurse_id][d] = _normalize_to_main(e.shift_id, code2main)
    # 꼬리 days일만 취득
    result = {}
    start = max(1, max_day - days + 1)
    tail_days = list(range(start, max_day + 1))
    for nurse_id, daymap in by_nurse.items():
        seq = []
        for d in tail_days:
            seq.append(daymap.get(d, '-'))
        result[nurse_id] = seq
    return result

def _calc_tail_metrics(seq: list[str]) -> dict:
    """꼬리 시퀀스(길이<=6)로부터 연속성 메트릭을 계산한다."""
    if not seq:
        return {
            'consecutive_work_tail': 0,
            'consecutive_night_tail': 0,
            'last_day_shift': None,
            'offs_after_tail_nights': 0,
        }
    last = seq[-1]
    # 연속 근무 꼬리(D/E/N)
    cons_work = 0
    for c in reversed(seq):
        if c in ('D', 'E', 'N'):
            cons_work += 1
        elif c == 'O':
            break
    # tail 끝의 OFF 카운트
    offs_after_n = 0
    i = len(seq) - 1
    while i >= 0 and seq[i] == 'O':
        offs_after_n += 1
        i -= 1
    # 그 직전의 연속 N 카운트
    cons_n = 0
    while i >= 0 and seq[i] == 'N':
        cons_n += 1
        i -= 1
    return {
        'consecutive_work_tail': cons_work,
        'consecutive_night_tail': cons_n,
        'last_day_shift': last,
        'offs_after_tail_nights': min(2, offs_after_n),
    }

def build_cross_month_constraints(db: Session, req: RosterRequest, current_user, shift_manage_data, config_dict: dict, nurse_ids: list[str]) -> dict:
    """이전 달 꼬리 패턴을 기반으로 강제 OFF/금지 셀을 생성한다."""
    print("이전 월 경계 제약 생성 시작…")
    enable = bool(config_dict.get('cross_month_hard_rules_enable', True))
    lookback = int(config_dict.get('cross_month_lookback_days', 6))
    if not enable or lookback <= 0:
        print("이전 월 경계 제약 비활성화 또는 조회일수 0")
        return {'forced_off': {}, 'forbidden': {}}

    # 코드 정규화 맵 구성
    code2main = {}
    for r in (shift_manage_data or []):
        main = r.get('main_code')
        for c in (r.get('codes') or []):
            code2main[str(c).upper()] = main
    code2main['O'] = 'O'; code2main['O'] = 'O'

    # 이전 달 최신 스케줄 조회 → 마지막 N일 시퀀스
    prev_sid = _query_prev_month_schedule_id(db, current_user.group_id, req.year, req.month)
    last_map = _get_last_days_map(db, prev_sid, lookback, code2main) if prev_sid else {}

    forced_off = defaultdict(list)
    forbidden = defaultdict(lambda: defaultdict(list))

    # 설정값 활용
    K = int(config_dict.get('max_conseq_work') or 0)
    two_after_three = bool(config_dict.get('two_offs_after_three_nig'))
    two_after_two = bool(config_dict.get('two_offs_after_two_nig'))
    banned_E_to_D = bool(config_dict.get('banned_day_after_eve'))
    L = int(config_dict.get('max_consecutive_nights') or 0)

    for nurse_id in nurse_ids:
        tail = last_map.get(nurse_id, [])
        metrics = _calc_tail_metrics(tail)
        cons_work = metrics['consecutive_work_tail']
        cons_n = metrics['consecutive_night_tail']
        last_shift = metrics['last_day_shift']
        offs_after = metrics['offs_after_tail_nights']

        # (a) 연속 근무 K
        if K and cons_work == K:
            forced_off[nurse_id].append(0)
            print(f"간호사 {nurse_id}: 연속근무={cons_work} → day1 OFF")

        # (b) N2/3 → 2OFF
        req_offs = 0
        if two_after_three and cons_n >= 3:
            req_offs = 2
        elif two_after_two and cons_n >= 2:
            req_offs = 2
        rem = max(0, req_offs - offs_after)
        for d in range(min(2, rem)):
            forced_off[nurse_id].append(d)
        if rem > 0:
            print(f"간호사 {nurse_id}: N tail={cons_n}, offs_after={offs_after} → day1..{rem} OFF")

        # (c) E→D, N→D 금지
        if last_shift == 'E' and banned_E_to_D:
            forbidden[nurse_id][0].append('D')
        if last_shift == 'N':
            forbidden[nurse_id][0].append('D')

        # (d) 연속 N 상한
        if L and cons_n == L:
            forbidden[nurse_id][0].append('N')

    # 중복 제거/정렬
    forced_off = {k: sorted(set(v)) for k, v in forced_off.items()}
    forbidden = {k: {d: sorted(set(ss)) for d, ss in v.items()} for k, v in forbidden.items()}
    off_cnt = sum(len(v) for v in forced_off.values())
    forb_cnt = sum(len(ss) for v in forbidden.values() for ss in v.values())
    print(f"강제 OFF {off_cnt}건, 금지 셀 {forb_cnt}건 적용")
    return {'forced_off': forced_off, 'forbidden': forbidden}

def _run_cp_sat_basic(db: Session, current_user, nurses_in_group, preferences, latest_config, req, shift_manage_data, fixed_cells=None, time_limit_seconds=60, config_override: dict | None = None):
    """cp_sat_basic 엔진 호출을 표준화한다."""
    try:
        nurses_dict = [n.__dict__ for n in nurses_in_group]
        # prefs_dict = [p.__dict__ for p in preferences]
        prefs_dict = preferences

        # 호출자가 구성한 config_dict(게이지 반영 등)이 있으면 이를 사용
        config_dict = (config_override.copy() if config_override is not None else (latest_config.__dict__.copy() if latest_config else {}))
        # ShiftManage 요구인원은 호출부에서 주입한다

        # fixed_cells 는 옵션
        if fixed_cells:
            config_dict['fixed_cells'] = fixed_cells
    except Exception as e:
        print(f"error: {e}")
    # cross-month 경계 제약 생성 및 주입
    try:
        initial_constraints = build_cross_month_constraints(
            db, req, current_user, shift_manage_data, config_dict, [n.nurse_id for n in nurses_in_group]
        )
        config_dict['initial_constraints'] = initial_constraints
    except Exception as e:
        print(f"이전 월 경계 제약 생성 실패: {e}")
    try:
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
    except Exception as e:
        print(f"error: {e}")
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
def _apply_preceptor_gauge(config_dict: dict, gauge: int | None) -> None:
    """프리셉터 게이지(0~10)를 엔진 설정 파라미터로 매핑한다.

    Args:
        config_dict: 엔진에 전달할 설정 딕셔너리 (in-place 수정)
        gauge: 프론트에서 전달한 게이지 값(0~10). None이면 미적용
    """

    if gauge is None:
        return
    print(f"프리셉터 게이지: {gauge}")
    g = max(0, min(10, int(gauge)))
    # 강도: 0→0.2x, 10→2.0x
    strength = round(0.2 + 0.18 * g, 2)
    # 상위 일수 K: 0→4, 10→30
    top_k = int(4 + (30 - 4) * (g / 10.0))
    # 최소 가중치 하한: 0→10.0, 10→5.0
    min_w = round(10.0 - 0.5 * g, 2)

    config_dict['preceptor_enable'] = g > 0
    config_dict['preceptor_strength_multiplier'] = strength
    config_dict['preceptor_top_days'] = top_k
    config_dict['preceptor_min_pair_weight'] = min_w
    # # 교대 포커스: 게이지 낮음→N, 중간→E/N, 높음→D/E/N
    # if g <= 3:
    #     config_dict['preceptor_focus_shifts'] = ['N']
    # elif g <= 6:
    #     config_dict['preceptor_focus_shifts'] = ['E','N']
    # else:
    #     config_dict['preceptor_focus_shifts'] = ['D','E','N']
    # print(f"[프리셉터 게이지] g={g} → strength={strength}x, top_k={top_k}, min_w={min_w}, focus={config_dict['preceptor_focus_shifts']}")
    print(f"[프리셉터 게이지] g={g} → strength={strength}x, top_k={top_k}, min_w={min_w}")

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
    shift_manage_data, daily_shift_requirements, daily_shift_requirements_by_day = _build_shift_manage_and_requirements(
        db, current_user, latest_config, req
    )
    # daily_shift_requirements를 config에 주입해서 엔진 호출
    config_dict = latest_config.__dict__ if latest_config else {}
    print('daily_shift_requirements!!', daily_shift_requirements)
    config_dict['daily_shift_requirements'] = daily_shift_requirements
    # 일자별 요구치 우선 적용
    config_dict['daily_shift_requirements_by_day'] = daily_shift_requirements_by_day
    print('latest_config', latest_config.daily_shift_requirements)
    # ── 프리셉터 게이지(0~10) → 파라미터 매핑 ──
    
    _apply_preceptor_gauge(config_dict, config_dict['preceptor_gauge'])
    # 경계 제약 기능 기본값
    config_dict.setdefault('cross_month_hard_rules_enable', True)
    config_dict.setdefault('cross_month_lookback_days', 6)
    config_dict.setdefault('allow_override_by_law', False)
    print("cp_sat_basic 엔진으로 근무표 생성 시작")
    generated, satisfaction_data, roster_system = _run_cp_sat_basic(
        db,
        current_user,
        nurses_in_group,
        preferences,
        latest_config,
        req,
        shift_manage_data,
        fixed_cells=None,
        time_limit_seconds=60,
        config_override=config_dict,
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
    # ── 프리셉터 게이지(0~10) → 파라미터 매핑 (고정 생성에도 동일 적용) ──
    _apply_preceptor_gauge(config_dict, config_dict['preceptor_gauge'])
    # 경계 제약 기능 기본값 및 충돌 정책(hold는 기본 차단)
    config_dict.setdefault('cross_month_hard_rules_enable', True)
    config_dict.setdefault('cross_month_lookback_days', 6)
    config_dict.setdefault('allow_override_by_law', False)

    print("cp_sat_basic 엔진으로 고정 셀 반영 근무표 생성 시작")
    generated, satisfaction_data, roster_system = _run_cp_sat_basic(
        db,
        current_user,
        nurses_in_group,
        preferences,
        latest_config,
        req,
        shift_manage_data,
        fixed_cells=fixed_cells,
        time_limit_seconds=300,
        config_override=config_dict,
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
    print('latest_config', latest_config)
    # if not latest_config :
        # raise Exception("설정값을 입력해주세요")
    if not latest_config or latest_config == None:
        return "noConfigId"
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
        dropped=False,
        name=f"{req.month}월 근무표 VER{latest_version + 1}"
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    db.commit()
    return new_schedule 