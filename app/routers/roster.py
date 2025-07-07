from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.schemas.roster_schema import RosterRequest, RosterResponse, RosterConfigCreate, RosterConfig
from app.services.graph_service import graph_service
from app.routers.auth import get_current_user_from_cookie
from app.schemas.auth_schema import User
from app.db.client import get_db
from app.db.models import RosterConfig as RosterConfigModel

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

# ───────────────────────── API Endpoints ───────────────────────── #
# 아래와 같이 JSON List 데이터가 있을 때, 각 데이터에서 "shift 데이터가 있으면 OFF를 제외한 나머지는       {nurse_id1:  { "D": { "4": 1.0, "5": 3.2, "10": 2.5, "20": 1.5 },
#                "E": { "15":1.0, "16":1.2, "25":1.0, "26":1.0 },
#                "N": { "11":0.8, "12":0.8 } },       
# nurse_id2:  { "N": { "8":1.0, "9":1.0, "15":1.0, "16":1.0, "22":1.0, "23":1.0 } }}
# 과 같이 표기해서  각 간호사 별 shift 선호점수를 parsing해서 shift_preferences에 넣고,
# OFF의 경우는 
# off_requests변수에 {
#        nurse_id1:  { "6":  5.0, "7":  5.0 },                     
#       nurse_id2:  { "1":  3.0, "2":  3.0, "3":  3.0 },           
#       nurse_id3:  { "15": 4.0, "16": 4.0 }}
# 이런식으로 넣어줘.

# 그리고 preference 키의 경우, 
@router.post("/roster/invoke", response_model=RosterResponse)
async def invoke_graph(request: RosterRequest):
    """
    그래프를 실행하여 로스터 관련 요청을 처리합니다.
    """
    try:
        result = {}
        print('요청', request.request)
        print('스키마', request.schema)
        print('케이스', request.case)
        response =  await graph_service.invoke(request.request, request.schema, request.case)
        print('우라질레이션',  response)
        print('1기여기여기111', response)
        print('\n\n\n\n\n\n응답1:', parse_shift_results(response), '\n\n\n\n\n\n')
        print('\n\n\n\n\n\n응답2:', parse_preferences(response, request.schema), '\n\n\n\n\n\n')
        if len(response[0]) > 0:
            result['shift'] = parse_shift_results(response)
            
            # for i in range(len(response[0])):
            #     result.append(response[0][i]['shift_result'][j]['result'] for j in range(len(response[0][i]['shift_result'])))
        if len(response[1]) > 0:
            result['preference'] = parse_preferences(response, request.schema)
            # for i in range(len(response[1])):
        print('결과', result)    #     result.append(response[1][i]['preference_result'][j] for j in range(len(response[1][i]['preference_result'])))
        if result == {}:
            result = ["근무 희망사항이 없습니다."]
        print('\n\n\n\n\n\n응답:', result, '\n\n\n\n\n\n')
        return RosterResponse(response=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def parse_shift_results(
    response: List[List[Dict[str, Any]]]
) -> Dict[str, Dict[int, float]]:
    """
    2-중 리스트 구조의 shift_result → {shift: {date: score}} 형태로 통합.

    Parameters
    ----------
    response : List[List[Dict[str, Any]]]
        create_shift_analyzer 가 돌려준 전체 응답.

    Returns
    -------
    Dict[str, Dict[int, float]]
        {'D': {7: 0.0}, 'N': {10: 0.0}, ...}
    """
    parsed: Dict[str, Dict[int, float]] = {}

    # ── 1. 최상위는 여러 agent 그룹이 List 로 묶여있음 ─────────────────────
    for sub in response:
        if not isinstance(sub, list):
            continue

        # ── 2. 한 그룹 안에는 여러 entry 가 dict 로 존재 ──────────────────
        for entry in sub:
            shift_results = entry.get("shift_result", [])
            if not isinstance(shift_results, list):
                continue

            # ── 3. shift_result 의 각 항목 처리 ────────────────────────────
            for sr in shift_results:
                # ▷ 케이스 A : {'shift': 'D', 'date': [...], 'score': [...]}
                if {"shift", "date", "score"} <= sr.keys():
                    record = sr
                # ▷ 케이스 B : {'result': {...}}
                elif "result" in sr and isinstance(sr["result"], dict):
                    record = sr["result"]
                else:                       # 예상 외 구조 → skip
                    continue

                shift  = record.get("shift")
                dates  = record.get("date", [])
                scores = record.get("score", [])

                if not shift or not isinstance(dates, list) or not isinstance(scores, list):
                    continue

                bucket = parsed.setdefault(shift, {})
                for d, s in zip(dates, scores):
                    bucket[d] = float(s)

    return parsed

def parse_preferences(
    response: List[List[Dict[str, Any]]],
    schema: List[Dict[str, Any]] = None
) -> List[Dict[str, float]]:
    """
    2-중 리스트 구조의 preference_result 항목들을 전부 뽑아서
    [{'id': 12, 'weight': -1.5}, {'id': 13, 'weight': 1.5}, ...]
    형태의 리스트로 반환합니다. preference_result 가 없거나
    비어있어도 빈 리스트를 반환하며 에러는 발생하지 않습니다.
    schema가 제공되면 유효한 간호사 ID만 필터링합니다.
    """
    parsed: List[Dict[str, float]] = []
    
    # schema에서 유효한 간호사 ID 목록 추출
    valid_nurse_ids = set()
    if schema:
        for nurse in schema:
            if isinstance(nurse, dict) and 'nurse_id' in nurse:
                valid_nurse_ids.add(nurse['nurse_id'])

    # 최상위: 여러 agent 그룹
    for sub in response:
        if not isinstance(sub, list):
            continue
        # 그룹 내 각 entry
        for entry in sub:
            # preference_result 키로 가져오고, 없으면 빈 리스트
            pref_list = entry.get("preference_result", [])
            if not isinstance(pref_list, list):
                continue
            # 각 preference 항목
            for pr in pref_list:
                _id     = pr.get("id")
                weight  = pr.get("weight")
                # id 와 weight 모두 있을 때만
                if _id is None or weight is None:
                    continue
                
                # 빈 ID는 무시
                if not _id:
                    continue
                    
                # schema가 있고 ID가 유효하지 않으면 무시
                if valid_nurse_ids and _id not in valid_nurse_ids:
                    print(f"Parse Preferences: 무효한 간호사 ID '{_id}' 필터링됨")
                    continue
                    
                try:
                    parsed.append({"id": str(_id), "weight": float(weight)})
                except (ValueError, TypeError):
                    # 변환 불가능하면 skip
                    continue

    return parsed

@router.post("/roster/config/save")
async def save_roster_config(
    config_data: RosterConfigCreate,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    if not user or not user.is_head_nurse:
        raise HTTPException(status_code=403, detail="Permission denied")
    print('user11', user)
    db_config = RosterConfigModel(
        **config_data.model_dump(),
        office_id=user.office_id,
        group_id=user.group_id
    )
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return {"message": "Configuration saved successfully"} 