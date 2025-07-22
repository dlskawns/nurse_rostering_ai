from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.db.client import get_db
from app.db.models import Nurse as NurseModel
from app.schemas.roster_schema import NurseProfile
from app.routers.auth import get_current_user_from_cookie
from app.schemas.auth_schema import User as UserSchema
from app.services.nurse_service import get_nurses_in_group_service, bulk_update_nurses_service

router = APIRouter(
    prefix="/nurses",
    tags=["nurses"]
)

@router.get("", response_model=List[NurseProfile])
async def get_nurses_in_group(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return get_nurses_in_group_service(current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"간호사 목록 조회 실패: {str(e)}")

@router.post("/bulk-update")
async def bulk_update_nurses(
    nurses_data: List[NurseProfile],
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return bulk_update_nurses_service(nurses_data, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"간호사 일괄 업데이트 실패: {str(e)}") 