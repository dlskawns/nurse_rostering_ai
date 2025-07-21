from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db.client import get_db
from app.db.models import Shift, Nurse, ScheduleEntry, ShiftManage
from app.schemas.auth_schema import User as UserSchema
from app.routers.auth import get_current_user_from_cookie
from app.schemas.roster_schema import ShiftAddRequest, RemoveShiftRequest, MoveShiftRequest, ShiftManageSaveRequest

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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