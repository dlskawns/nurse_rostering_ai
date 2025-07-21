from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.db.client import get_db
from app.db.models import Nurse as NurseModel
from app.schemas.roster_schema import NurseProfile
from app.routers.auth import get_current_user_from_cookie
from app.schemas.auth_schema import User as UserSchema

router = APIRouter(
    prefix="/nurses",
    tags=["nurses"]
)

@router.get("", response_model=List[NurseProfile])
async def get_nurses_in_group(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    nurses = db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id).all()
    return nurses

@router.post("/bulk-update")
async def bulk_update_nurses(
    nurses_data: List[NurseProfile],
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Validation: Ensure at least one head nurse exists
    if not any(n.is_head_nurse for n in nurses_data):
        raise HTTPException(status_code=400, detail="At least one head nurse must be assigned.")

    db_nurses_dict = {n.nurse_id: n for n in db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id).all()}
    
    for nurse_data in nurses_data:
        db_nurse = db_nurses_dict.get(nurse_data.nurse_id)
        
        if db_nurse: # Update existing nurse
            # Ensure they are not trying to update a nurse from another group
            if db_nurse.group_id != current_user.group_id:
                continue # Or raise error
            
            update_data = nurse_data.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_nurse, key, value)
        
        else: # Add new nurse
            # 보안을 위해 클라이언트의 group_id는 무시하고 현재 사용자의 group_id를 강제로 설정
            nurse_dict = nurse_data.dict()
            nurse_dict.pop('group_id', None)  # 기존 group_id 제거
            new_nurse = NurseModel(**nurse_dict, group_id=current_user.group_id)
            db.add(new_nurse)

    # Handle deletions
    client_nurse_ids = {n.nurse_id for n in nurses_data}
    for db_nurse_id, db_nurse in db_nurses_dict.items():
        if db_nurse_id not in client_nurse_ids:
            db.delete(db_nurse)
            
    db.commit()
    return {"message": "Nurses updated successfully"} 