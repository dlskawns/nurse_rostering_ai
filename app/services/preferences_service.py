"""
간호사 선호도(Preferences) 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import ShiftPreference, Nurse
from schemas.roster_schema import PreferenceData, PreferenceSubmit
from schemas.auth_schema import User as UserSchema
from datetime import datetime


def save_preference_draft_service(pref_data: PreferenceData, current_user, db: Session):
    """
    선호도 초안 저장 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    current_time = datetime.now().replace(microsecond=0)
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
    db.refresh(preference)
    return {"message": "Preference draft saved successfully"}

def submit_preferences_service(req: PreferenceSubmit, current_user, db: Session):
    """
    선호도 최종 제출 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()
    if not preference:
        raise Exception("No preference draft found to submit")
    preference.is_submitted = True
    preference.submitted_at = datetime.utcnow()
    db.commit()
    return {"message": "Preferences submitted successfully"}

def submit_empty_preferences_service(req: PreferenceSubmit, current_user, db: Session):
    """
    빈 선호도 최종 제출 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
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

def retract_submission_service(req: PreferenceSubmit, current_user, db: Session):
    """
    선호도 제출 철회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == req.year,
        ShiftPreference.month == req.month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()
    if not preference:
        raise Exception("No submitted preference found to retract")
    preference.is_submitted = False
    preference.submitted_at = None
    db.commit()
    return {"message": "Submission retracted successfully"}

def get_latest_preference_service(year: int, month: int, current_user, db: Session):
    """
    최신 선호도 데이터 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
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
    return {
        "preference_data": None,
        "is_submitted": False,
        "created_at": None,
        "submitted_at": None
    }

def get_all_preferences_service(year: int, month: int, current_user, db: Session):
    """
    모든 간호사의 최신 선호도 데이터 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    preferences = db.query(ShiftPreference).filter(
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).join(Nurse, ShiftPreference.nurse_id == Nurse.nurse_id).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(ShiftPreference.submitted_at.desc()).all()
    latest_prefs = {}
    for pref in preferences:
        if pref.nurse_id not in latest_prefs:
            latest_prefs[pref.nurse_id] = pref
    return list(latest_prefs.values()) 