from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from db.client import get_db
from db.models import Nurse as NurseModel
from schemas.roster_schema import NurseProfile, MoveNurseRequest
from routers.auth import get_current_user_from_cookie
from schemas.auth_schema import User as UserSchema
from services.nurse_service import get_nurses_in_group_service, bulk_update_nurses_service, move_nurse_service
from pydantic import BaseModel, Field


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

class NurseSequenceUpdate(BaseModel):
    nurse_id: str
    sequence: int = Field(ge=0)


@router.post("/sequence/save")
async def save_nurse_sequence(
    req: MoveNurseRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    try:
        return move_nurse_service(req, current_user, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"간호사 순서 변경 실패: {str(e)}")


    # try:
    #     if not current_user:
    #         raise HTTPException(status_code=401, detail="인증되지 않았습니다.")
    #     nurse_ids = [u.nurse_id for u in updates]
    #     if not nurse_ids:
    #         return {"message": "변경 사항 없음", "updated": 0}
    #     # 같은 그룹 내 대상만 업데이트
    #     rows = (
    #         db.query(NurseModel)
    #         .filter(NurseModel.group_id == current_user.group_id, NurseModel.nurse_id.in_(nurse_ids))
    #         .all()
    #     )
    #     row_map = {r.nurse_id: r for r in rows}
    #     updated = 0
    #     for item in updates:
    #         r = row_map.get(item.nurse_id)
    #         if r is None:
    #             continue
    #         r.sequence = int(item.sequence)
    #         updated += 1
    #     db.commit()
    #     return {"message": "간호사 순서 저장 완료", "updated": updated}
    # except Exception as e:
    #     db.rollback()
    #     raise HTTPException(status_code=500, detail=f"간호사 순서 저장 실패: {str(e)}")



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