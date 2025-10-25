from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.client import get_db
from routers.auth import get_current_user_from_cookie
from schemas.auth_schema import User as UserSchema
from schemas.team_schema import TeamBulkOpsRequest, TeamWithMembers
from services.team_service import list_teams_with_members, apply_team_ops


router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamWithMembers])
async def get_teams(
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="인증 필요")
    return list_teams_with_members(db, current_user.office_id, current_user.group_id)


@router.put("", response_model=list[TeamWithMembers])
async def put_teams(
    body: TeamBulkOpsRequest,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    if not current_user or not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="권한 없음")
    try:
        payload = [t.dict() for t in body.teams]
        return apply_team_ops(
            db,
            current_user.office_id,
            current_user.group_id,
            payload,
            delete_team_ids=body.delete_team_ids,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"팀 동기화 실패: {e}")


