from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from db.client import get_db
# from db.client2 import _get_mssql_session
from db.models import Shift, Nurse, ScheduleEntry, ShiftManage, RosterConfig
from schemas.auth_schema import User as UserSchema
from routers.auth import get_current_user_from_cookie
from schemas.roster_schema import ShiftAddRequest, RemoveShiftRequest, MoveShiftRequest, ShiftManageSaveRequest, ShiftUpdateRequest
from services.shift_service import (
    get_shifts_service as get_shifts_service_mysql,
    add_shift_service,
    update_shift_service,
    remove_shift_service,
    move_shift_service
)
from typing import Optional
import os
from services.shift_service_mssql import get_shifts_service as get_shifts_service_mssql
from datetime import timedelta, datetime

def convert_time(value):
    if isinstance(value, str):  # '06:00' → timedelta
        h, m = map(int, value.split(":"))
        return timedelta(hours=h, minutes=m)
    return value


router = APIRouter(
    tags=["shifts"]
)
templates = Jinja2Templates(directory="app/templates")
from dotenv import load_dotenv
load_dotenv()

# [Shifts] - 모든 시프트 정보 조회
@router.get("/shifts")
async def get_shifts(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)   
):
    try:
        backend = os.getenv("DB_BACKEND", "mysql").lower()
        if backend == "mssql":
            shifts = get_shifts_service_mssql(current_user, db)
        else:
            shifts = get_shifts_service_mysql(current_user, db)
        for shift in shifts:
            shift["start_time"] = convert_time(shift["start_time"])
            shift["end_time"] = convert_time(shift["end_time"])
        return shifts
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"시프트 정보 조회 실패: {str(e)}")

def _format_time_display(shift):
    """근무 시간 정보를 표시용으로 포맷팅"""
    if 'allday' in shift:
        if shift.allday == 1:
            return '종일'
    elif shift.start_time and shift.end_time:
        return f'{shift.start_time} ~ {shift.end_time}'
    elif shift.type:
        return shift.type

@router.post("/shifts/add")
async def add_shift(
    req: ShiftAddRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        result = add_shift_service(req, current_user, db)
    except Exception as e:
        print('error', e)
        raise HTTPException(status_code=500, detail=f"근무코드 추가 실패: {str(e)}")

@router.post("/shifts/update")
async def update_shift(
    req: ShiftUpdateRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        result = update_shift_service(req, current_user, db)
        return result
    except Exception as e:
        print('error', e)
        raise HTTPException(status_code=500, detail=f"근무코드 수정 실패: {str(e)}")
@router.post("/shifts/remove")
async def remove_shift(
    req: RemoveShiftRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return remove_shift_service(req, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"근무코드 삭제 실패: {str(e)}")

@router.post("/shifts/move")
async def move_shift(
    req: MoveShiftRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return move_shift_service(req, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"근무코드 순서 변경 실패: {str(e)}")


# [Shift Management] - 시프트 관리 데이터 조회
@router.get("/shift-manage/{class_name}")
async def get_shift_manage(
    class_name: str,
    # config_version: Optional[str] = None,
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
        ShiftManage.nurse_class == class_name,
        # ShiftManage.config_version == config_version
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
                manpower=slot_data["manpower"],
                # config_version=config_version
            )
            db.add(shift_manage)
        db.commit()

        # 다시 조회해서 반환
        shift_manages = db.query(ShiftManage).filter(
            ShiftManage.office_id == nurse.group.office_id,
            ShiftManage.group_id == current_user.group_id,
            ShiftManage.nurse_class == class_name,
            # ShiftManage.config_version == config_version
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


@router.post("/shift-manage/save")
async def save_shift_manage(
    req: ShiftManageSaveRequest,
    # config_version: Optional[str] = None,
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
        ShiftManage.nurse_class == req.class_name,
        # ShiftManage.config_version == config_version
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
            manpower=slot_data["manpower"],
            # config_version=config_version
        )
        db.add(shift_manage)
    
    db.commit()
    return {"message": "시프트 관리 설정이 저장되었습니다."}