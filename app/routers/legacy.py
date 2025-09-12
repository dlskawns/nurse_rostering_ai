from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from sqlalchemy.orm import Session
from routers.auth import get_current_user_from_cookie
from schemas.auth_schema import User
from db.client import get_db
from db.models import RosterConfig as RosterConfigModel
from schemas.auth_schema import User as UserSchema


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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
    config_version: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Get config based on version parameter or latest
    if config_version:
        latest_config = db.query(RosterConfigModel).filter(
            RosterConfigModel.office_id == current_user.office_id,
            RosterConfigModel.group_id == current_user.group_id,
            RosterConfigModel.config_version == config_version
        ).order_by(RosterConfigModel.created_at.desc()).first()
    else:
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

# @router.get("/dashboard", response_class=HTMLResponse)
# async def dashboard_page(request: Request, user: User = Depends(get_current_user_from_cookie)):
#     if not user or not user.is_head_nurse:
#         return templates.TemplateResponse("unauthorized.html", {"request": request}, status_code=403)
#     return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})