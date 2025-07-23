from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime
from db.roster_config import NurseRosterConfig, DEFAULT_CONFIG
from schemas.roster_schema import RosterConfigCreate, RosterConfig, PublishRequest, WantedInvokeRequest, WantedInvokeResponse, RosterRequest
from services.graph_service import graph_service
from routers.auth import get_current_user_from_cookie
from schemas.auth_schema import User
from db.client import get_db
from db.models import RosterConfig as RosterConfigModel
from schemas.auth_schema import User as UserSchema
from db.models import Schedule, ShiftPreference, Nurse, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage
from sqlalchemy import func, and_
from routers.utils import get_days_in_month
from db.nurse_config import Nurse as NurseEngine
from services.roster_system import RosterSystem
from datetime import date
from services.roster_service import save_roster_config_service, get_latest_schedule_service, get_issued_schedules_service, get_schedule_status_service
import uuid

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ─────────────────────────  로그인  ───────────────────────── #
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request},
    )

# ─────────────────────────  메인 페이지  ───────────────────────── #
@router.get("/", response_class=HTMLResponse)
async def read_item(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_from_cookie),
):
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": current_user},
    )

# ─────────────────────────  수간호사 전용 메뉴  ───────────────────────── #
@router.get("/head-nurse-management", response_class=HTMLResponse)
async def head_nurse_management(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_from_cookie),
):
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    return templates.TemplateResponse(
        "head_nurse_management.html",
        {"request": request, "user": current_user},
    )

@router.get("/roster-create", response_class=HTMLResponse)
async def roster_create(
    
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_from_cookie),
):
    """
    근무표 생성 페이지 호출
    """
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    return templates.TemplateResponse(
        "roster_create.html",
        {"request": request, "user": current_user},
    )

@router.get("/roster-configure", response_class=HTMLResponse)
async def roster_configure(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    latest_config = db.query(RosterConfigModel).filter(
        RosterConfigModel.office_id == current_user.office_id,
        RosterConfigModel.group_id == current_user.group_id
    ).order_by(RosterConfigModel.created_at.desc()).first()

    return templates.TemplateResponse(
        "roster_configure.html",
        {"request": request, "user": current_user, "config": latest_config},
    )

@router.get("/roster-view", response_class=HTMLResponse)
async def roster_view_page(request: Request, user: User = Depends(get_current_user_from_cookie)):
    if not user:
        # 일반 간호사도 접근 가능해야 하므로 head_nurse 체크는 제거
        return templates.TemplateResponse("unauthorized.html", {"request": request}, status_code=403)
    return templates.TemplateResponse("roster_view.html", {"request": request, "user": user})

@router.post("/roster/config/save")
async def save_roster_config(
    config_data: RosterConfigCreate,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    if not user or not user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        return save_roster_config_service(config_data, user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Configuration save failed: {str(e)}")
    

# [Schedules] - 최신 월과 버전의 스케줄 정보 조회 (수간호사용)
@router.get("/roster/latest")
async def get_latest_schedule(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return get_latest_schedule_service(current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get latest schedule: {str(e)}")


# [Schedules] - 발행된(issued) 모든 스케줄 조회
@router.get("/roster/issued")
async def get_issued_schedules(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return get_issued_schedules_service(current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get issued schedules: {str(e)}")


# [Schedules] - 현재 그룹의 특정 월에 대한 스케줄 상태 확인
@router.get("/roster/status")
async def get_schedule_status(
    year: int, month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return get_schedule_status_service(year, month, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get schedule status: {str(e)}")



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
# [Schedules] - 특정 월의 모든 버전 목록 조회 (수간호사용)
@router.get("/roster/{year:int}/{month:int}/versions")
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

# [Roster] - 특정 월의 근무표 조회
@router.get("/roster/{year:int}/{month:int}")
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


# [Roster] - 특정 월의 근무표 조회
@router.get("/roster/{year: int}/{month: int}")
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



# [Schedules] - 특정 스케줄의 모든 간호사 제출 현황 확인
@router.get("/roster/{year:int}/{month:int}/submissions")
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
@router.get("/roster/status")
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

