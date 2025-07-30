# from fastapi import APIRouter, HTTPException, Depends
# from sqlalchemy.orm import Session
# from typing import List, Optional, Dict, Any
# from datetime import time

# from app.db.models import (
#     Office, Group, Nurse,  Schedule, 
#      RosterConfig, Wanted, IssuedRoster, Shift
# )
# from app.db.client import get_db
# from app.routers.auth import get_current_user_from_cookie
# from app.schemas.auth_schema import User
# from pydantic import BaseModel

# router = APIRouter()

# # Shift 관련 Pydantic 모델들
# class ShiftCreate(BaseModel):
#     shift_id: str
#     name: str
#     start_time: Optional[str] = None  # HH:MM format
#     end_time: Optional[str] = None    # HH:MM format
#     duration: Optional[int] = None    # hours
#     color: str = "#2196F3"
#     is_rest: bool = False
#     all_day: Optional[int] = 0
#     auto_schedule: Optional[int] = 1
#     type: str

# class ShiftResponse(BaseModel):
#     shift_id: str
#     name: str
#     start_time: Optional[str] = None
#     end_time: Optional[str] = None
#     duration: Optional[int] = None
#     color: str
#     is_rest: bool
#     created_at: str
#     updated_at: str
#     all_day: Optional[int] = 0
#     auto_schedule: Optional[int] = 1
#     type: str

# # [API] - 그룹별 근무코드 조회
# @router.get("/api/shifts")
# async def get_shifts(
#     current_user: User = Depends(get_current_user_from_cookie),
#     db: Session = Depends(get_db)
# ):
#     """현재 사용자의 그룹에 속한 모든 근무코드를 조회합니다."""
#     if not current_user:
#         raise HTTPException(status_code=401, detail="Not authenticated")
    
#     try:
#         # 현재 사용자의 그룹 정보 가져오기
#         nurse = db.query(Nurse).filter(Nurse.account_id == current_user.account_id).first()
#         if not nurse:
#             raise HTTPException(status_code=404, detail="Nurse information not found")
        
#         # 해당 그룹의 모든 근무코드 조회
#         shifts = db.query(Shift).filter(Shift.group_id == nurse.group_id).order_by(Shift.created_at.desc()).all()
        
#         shifts_data = []
#         for shift in shifts:
#             shifts_data.append({
#                 "shift_id": shift.shift_id,
#                 "name": shift.name,
#                 "start_time": shift.start_time.strftime("%H:%M") if shift.start_time else None,
#                 "end_time": shift.end_time.strftime("%H:%M") if shift.end_time else None,
#                 "duration": shift.duration,
#                 "color": shift.color,
#                 "is_rest": shift.is_rest,
#                 "created_at": shift.created_at.isoformat(),
#                 "updated_at": shift.updated_at.isoformat(),
#                 "all_day": shift.all_day,
#                 "auto_schedule": shift.auto_schedule,
#                 "type": shift.type
#             })
        
#         return {"shifts": shifts_data}
    
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to retrieve shifts: {str(e)}")

# # [API] - 근무코드 추가
# @router.post("/roster/shift/add")
# async def add_shift(
#     shift_data: ShiftCreate,
#     current_user: User = Depends(get_current_user_from_cookie),
#     db: Session = Depends(get_db)
# ):
#     """새로운 근무코드를 추가합니다."""
#     if not current_user or not current_user.is_head_nurse:
#         raise HTTPException(status_code=403, detail="Permission denied")
    
#     try:
#         # 현재 사용자의 그룹 정보 가져오기
#         nurse = db.query(Nurse).filter(Nurse.account_id == current_user.account_id).first()
#         if not nurse:
#             raise HTTPException(status_code=404, detail="Nurse information not found")
        
#         # 중복 근무코드 확인
#         existing_shift = db.query(Shift).filter(
#             Shift.shift_id == shift_data.shift_id,
#             Shift.group_id == nurse.group_id
#         ).first()
#         if existing_shift:
#             raise HTTPException(status_code=400, detail="Shift code already exists")
        
#         # 시간 데이터 처리
#         start_time_obj = None
#         end_time_obj = None
        
#         if shift_data.start_time:
#             try:
#                 hours, minutes = map(int, shift_data.start_time.split(':'))
#                 start_time_obj = time(hours, minutes)
#             except ValueError:
#                 raise HTTPException(status_code=400, detail="Invalid start_time format. Use HH:MM")
        
#         if shift_data.end_time:
#             try:
#                 hours, minutes = map(int, shift_data.end_time.split(':'))
#                 end_time_obj = time(hours, minutes)
#             except ValueError:
#                 raise HTTPException(status_code=400, detail="Invalid end_time format. Use HH:MM")
        
#         # 새 근무코드 생성
#         new_shift = Shift(
#             shift_id=shift_data.shift_id,
#             group_id=nurse.group_id,
#             name=shift_data.name,
#             start_time=start_time_obj,
#             end_time=end_time_obj,
#             duration=shift_data.duration,
#             color=shift_data.color,
#             is_rest=shift_data.is_rest,
#             all_day=shift_data.all_day,
#             auto_schedule=shift_data.auto_schedule,
#             type=shift_data.type
#         )
        
#         db.add(new_shift)
#         db.commit()
#         db.refresh(new_shift)
        
#         return {"message": "Shift code added successfully", "shift_id": new_shift.shift_id}
    
#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=f"Failed to add shift: {str(e)}")

# # [API] - 근무코드 삭제
# @router.delete("/roster/shift/delete/{shift_id}")
# async def delete_shift(
#     shift_id: str,
#     current_user: User = Depends(get_current_user_from_cookie),
#     db: Session = Depends(get_db)
# ):
#     """근무코드를 삭제합니다."""
#     if not current_user or not current_user.is_head_nurse:
#         raise HTTPException(status_code=403, detail="Permission denied")
    
#     try:
#         # 현재 사용자의 그룹 정보 가져오기
#         nurse = db.query(Nurse).filter(Nurse.account_id == current_user.account_id).first()
#         if not nurse:
#             raise HTTPException(status_code=404, detail="Nurse information not found")
        
#         # 근무코드 찾기
#         shift = db.query(Shift).filter(
#             Shift.shift_id == shift_id,
#             Shift.group_id == nurse.group_id
#         ).first()
#         if not shift:
#             raise HTTPException(status_code=404, detail="Shift code not found")
        
#         # 사용 중인 근무코드인지 확인 (ScheduleEntry에서 참조되고 있는지)
#         from app.db.models import ScheduleEntry
#         schedule_entries = db.query(ScheduleEntry).filter(ScheduleEntry.shift_id == shift_id).first()
#         if schedule_entries:
#             raise HTTPException(status_code=400, detail="Cannot delete shift code that is currently in use")
        
#         # 근무코드 삭제
#         db.delete(shift)
#         db.commit()
        
#         return {"message": "Shift code deleted successfully"}
    
#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=f"Failed to delete shift: {str(e)}") 