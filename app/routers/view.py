from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from app.routers.auth import get_current_user_from_cookie
from app.schemas.auth_schema import User  # pydantic User 모델

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
    if current_user is None:                              # 로그인 안됨 → /login
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
    if current_user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not current_user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")

    return templates.TemplateResponse(
        "roster_create.html",
        {"request": request, "user": current_user},
    )
