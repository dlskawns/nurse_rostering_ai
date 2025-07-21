from app.schemas.roster_schema import PreferenceData, PreferenceSubmit
from app.routers.auth import get_current_user_from_cookie
from app.db.client import get_db
from app.db.models import ShiftPreference, Nurse
from app.schemas.auth_schema import User as UserSchema
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

router = APIRouter()

# [Preferences] - 간호사 개인의 선호도 초안 저장
@router.post("/preferences")
async def save_preference_draft(
    pref_data: PreferenceData,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # try:
    # 항상 새로운 레코드 생성 (덮어쓰기 방지)
    print('성공0')
    from datetime import datetime
    
    current_time = datetime.now().replace(microsecond=0)
    print('성공1', current_time)
    preference = ShiftPreference(
        nurse_id=current_user.nurse_id,
        year=pref_data.year,
        month=pref_data.month,
        data=pref_data.data,
        is_submitted=False,
        created_at=current_time,

    )
    db.add(preference)
    db.commit()
    print('성공3')
    db.refresh(preference)
    
    return {"message": "Preference draft saved successfully"}
        
    # except Exception as e:
    #     db.rollback()
    #     # Primary key 중복 에러 처리
    #     if "Duplicate entry" in str(e) or "1062" in str(e):
    #         # 동일한 시간에 생성된 레코드가 있으면 해당 레코드를 업데이트
            
    #         current_time = datetime.now()
            
    #         # 현재 시간(초 단위)과 동일한 created_at를 가진 레코드 찾기
    #         existing_pref = db.query(ShiftPreference).filter(
    #             ShiftPreference.nurse_id == current_user.nurse_id,
    #             ShiftPreference.year == pref_data.year,
    #             ShiftPreference.month == pref_data.month,
    #             func.date_format(ShiftPreference.created_at, '%Y-%m-%d %H:%i:%s') == 
    #             func.date_format(current_time, '%Y-%m-%d %H:%i:%s')
    #         ).first()
            
    #         if existing_pref:
    #             # 기존 레코드 업데이트
    #             existing_pref.data = pref_data.data
    #             existing_pref.is_submitted = False
    #             db.commit()
    #             return {"message": "Preference draft updated successfully"}
    #         else:
    #             # 약간의 시간 지연 후 재시도
    #             import time
    #             time.sleep(0.1)  # 100ms 대기
    #             preference = ShiftPreference(
    #                 nurse_id=current_user.nurse_id,
    #                 year=pref_data.year,
    #                 month=pref_data.month,
    #                 data=pref_data.data,
    #                 is_submitted=False,
    #             )
    #             db.add(preference)
    #             db.commit()
    #             db.refresh(preference)
    #             return {"message": "Preference draft saved successfully (retry)"}
    #     else:
    #         raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# [Preferences] - 선호도 최종 제출
@router.post("/preferences/submit")
async def submit_preferences(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 최신 draft 찾기
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()

    if not preference:
        raise HTTPException(status_code=404, detail="No preference draft found to submit")

    preference.is_submitted = True
    preference.submitted_at = datetime.utcnow()
    db.commit()
    return {"message": "Preferences submitted successfully"}

# [Preferences] - 빈 선호도 최종 제출
@router.post("/preferences/submit/empty")
async def submit_empty_preferences(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 빈 데이터로 새 레코드 생성 및 즉시 제출
    empty_data = {"shift": {}, "preference": []}
    preference = ShiftPreference(
        nurse_id=current_user.nurse_id,
        year=req.year,
        month=req.month,
        data=empty_data,
        is_submitted=True,
        submitted_at=datetime.utcnow()
    )
    db.add(preference)
    db.commit()
    return {"message": "Empty preferences submitted successfully"}

# [Preferences] - 최종 제출 철회 (수정)
@router.post("/preferences/retract")
async def retract_submission(
    req: PreferenceSubmit,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 최신 제출된 레코드 찾기
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()

    if not preference:
        raise HTTPException(status_code=404, detail="No submitted preference found to retract")

    preference.is_submitted = False
    preference.submitted_at = None
    db.commit()
    return {"message": "Submission retracted successfully"}

# [Preferences] - 최신 선호도 데이터 조회
@router.get("/preferences/latest")
async def get_latest_preference(
    year: int, 
    month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 해당 년월의 최신 레코드 찾기 (제출된 것 우선, 없으면 draft 중 최신)
    submitted_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()
    
    if submitted_preference:
        return {
            "preference_data": submitted_preference.data,
            "is_submitted": True,
            "created_at": submitted_preference.created_at,
            "submitted_at": submitted_preference.submitted_at
        }
    
    # 제출된 것이 없으면 최신 draft 찾기
    draft_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()
    
    if draft_preference:
        return {
            "preference_data": draft_preference.data,
            "is_submitted": False,
            "created_at": draft_preference.created_at,
            "submitted_at": None
        }
    
    # 아무것도 없으면 빈 데이터 반환
    return {
        "preference_data": None,
        "is_submitted": False,
        "created_at": None,
        "submitted_at": None
    }

# [Preferences] - 모든 간호사의 희망사항 현황 조회
@router.get("/preferences/all")
async def get_all_preferences(
    year: int, 
    month: int,
    current_user: UserSchema = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 해당 그룹의 모든 간호사의 최신 제출된 선호도 조회
    preferences = db.query(ShiftPreference).filter(
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).join(Nurse, ShiftPreference.nurse_id == Nurse.nurse_id).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(ShiftPreference.submitted_at.desc()).all()
    
    # 간호사별로 가장 최신 제출 데이터만 유지
    latest_prefs = {}
    for pref in preferences:
        if pref.nurse_id not in latest_prefs:
            latest_prefs[pref.nurse_id] = pref
    
    return list(latest_prefs.values())