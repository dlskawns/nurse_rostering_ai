"""
Wanted(근무 희망 요청) 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Wanted, Nurse, ShiftPreference
from schemas.roster_schema import WantedInvokeRequest, WantedDeadlineRequest
from schemas.auth_schema import User as UserSchema
from datetime import datetime


def request_wanted_shifts_service(req: WantedInvokeRequest, current_user, db: Session):
    """
    Wanted 작성 요청 생성 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    existing_wanted = db.query(Wanted).filter(
        Wanted.group_id == current_user.group_id,
        Wanted.year == req.year,
        Wanted.month == req.month
    ).first()
    if existing_wanted:
        raise Exception("이미 해당 월의 요청이 존재합니다.")
    new_wanted = Wanted(
        group_id=current_user.group_id,
        year=req.year,
        month=req.month,
        exp_date=req.exp_date,
        status='requested'
    )
    db.add(new_wanted)
    db.commit()
    db.refresh(new_wanted)
    return {"message": "Wanted 작성 요청이 성공적으로 생성되었습니다."}

# ... (다른 서비스 함수도 동일하게 분리하여 추가 예정) ... 