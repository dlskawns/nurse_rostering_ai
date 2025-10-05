"""
간호사 선호도(Preferences) 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
import pprint
from sqlalchemy.orm import Session
from sqlalchemy import String, cast, extract
from db.models import WantedRequest, Nurse, NurseShiftRequest, NursePairRequest, ShiftPreference
from schemas.roster_schema import PreferenceData, PreferenceSubmit
from schemas.auth_schema import User as UserSchema
from datetime import datetime


# def save_preference_draft_service(pref_data: PreferenceData, current_user, db: Session):
#     """
#     선호도 초안 저장 서비스 함수
#     """
#     if not current_user:
#         raise Exception("Not authenticated")
#     current_time = datetime.now().replace(microsecond=0)
#     preference = ShiftPreference(
#         nurse_id=current_user.nurse_id,
#         year=pref_data.year,
#         month=pref_data.month,
#         data=pref_data.data,
#         is_submitted=False,
#         created_at=current_time,
#     )
#     db.add(preference)
#     db.commit()
#     db.refresh(preference)
#     return {"message": "Preference draft saved successfully"}

def submit_preferences_service(req: PreferenceSubmit, current_user, db: Session):
    """
    선호도 최종 제출 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    preference = db.query(WantedRequest).filter(
        WantedRequest.nurse_id == current_user.nurse_id,
        WantedRequest.month == str(req.year) + '-' + str(req.month),
        WantedRequest.is_submitted == False
    ).order_by(WantedRequest.created_at.desc()).first()
    if not preference:
        raise Exception("No preference draft found to submit")
    preference.is_submitted = True
    preference.submitted_at = datetime.utcnow()
    db.commit()
    return {"message": "Preferences submitted successfully"}

# def submit_preferences_service(req: PreferenceSubmit, current_user, db: Session):
#     """
#     선호도 최종 제출 서비스 함수
#     """
#     if not current_user:
#         raise Exception("Not authenticated")
#     preference = db.query(ShiftPreference).filter(
#         ShiftPreference.nurse_id == current_user.nurse_id,
#         ShiftPreference.year == req.year,
#         ShiftPreference.month == req.month,
#         ShiftPreference.is_submitted == False
#     ).order_by(ShiftPreference.created_at.desc()).first()
#     if not preference:
#         raise Exception("No preference draft found to submit")
#     preference.is_submitted = True
#     preference.submitted_at = datetime.utcnow()
#     db.commit()
#     return {"message": "Preferences submitted successfully"}

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
    preference = db.query(WantedRequest).filter(
        WantedRequest.nurse_id == current_user.nurse_id,
        WantedRequest.month == str(req.year) + '-' + str(req.month),
        WantedRequest.is_submitted == True
    ).order_by(WantedRequest.submitted_at.desc()).first()
    if not preference:
        raise Exception("No submitted preference found to retract")
    preference.is_submitted = False
    preference.submitted_at = None
    db.commit()
    return {"message": "Submission retracted successfully"}

# def retract_submission_service(req: PreferenceSubmit, current_user, db: Session):
#     """
#     선호도 제출 철회 서비스 함수
#     """
#     if not current_user:
#         raise Exception("Not authenticated")
#     preference = db.query(ShiftPreference).filter(
#         ShiftPreference.nurse_id == current_user.nurse_id,
#         ShiftPreference.year == req.year,
#         ShiftPreference.month == req.month,
#         ShiftPreference.is_submitted == True
#     ).order_by(ShiftPreference.submitted_at.desc()).first()
#     if not preference:
#         raise Exception("No submitted preference found to retract")
#     preference.is_submitted = False
#     preference.submitted_at = None
#     db.commit()
#     return {"message": "Submission retracted successfully"}

def get_latest_preference_service(year: int, month: int, current_user, db: Session):
    """
    최신 선호도 데이터 조회 서비스 함수 (WantedRequest 기반)
    Front 기대 출력 형태에 맞게 중첩 구조로 변환하여 반환
    """
    if not current_user:
        raise Exception("Not authenticated")

    nurse_id = current_user.nurse_id
    month_str = f"{year}-{month:02d}"

    # 1️⃣ 제출된 요청 중 최신 데이터
    submitted_wr = (
        db.query(WantedRequest)
        .filter(
            WantedRequest.nurse_id == nurse_id,
            WantedRequest.month == month_str,
            WantedRequest.is_submitted == True,
        )
        .order_by(WantedRequest.submitted_at.desc())
        .first()
    )

    # 2️⃣ 없으면 가장 오래된(created_at.asc) 임시 요청 선택
    target_wr = submitted_wr or (
        db.query(WantedRequest)
        .filter(
            WantedRequest.nurse_id == nurse_id,
            WantedRequest.month == month_str,
        )
        .order_by(WantedRequest.created_at.desc())
        .first()
    )

    if not target_wr:
        # 아무 데이터도 없을 때
        return {
            "preference_data": None,
            "is_submitted": False,
            "created_at": None,
            "submitted_at": None,
        }

    # 3️⃣ 해당 request_id로 shift / pair 데이터 가져오기
    shift_rows = (
        db.query(NurseShiftRequest)
        .filter(
            NurseShiftRequest.nurse_id == nurse_id,
            NurseShiftRequest.request_id == target_wr.request_id,
            # cast(NurseShiftRequest.shift_date, String).like(f"{month_str}-%"),
        )
        .all()
    )
    # print('shift_rows', shift_rows)
    pair_rows = (
        db.query(NursePairRequest)
        .filter(
            NursePairRequest.nurse_id == nurse_id,
            NursePairRequest.request_id == target_wr.request_id,
        )
        .all()
    )

    # 4️⃣ shift 데이터 구조화 -> 여기만 나중에 바꿀것
    # 예: {'N': {'1': {'request': '주말은 N로 줘', 'score': 1.7}}, 'O': {...}}
    shift_data = {}
    for s in shift_rows:
        shift_code = s.shift.upper()
        day = str(int(s.shift_date.day))
        if shift_code not in shift_data:
            shift_data[shift_code] = {}
        shift_data[shift_code][day] = {
            "request": s.partial_request,
            "score": float(s.score) if s.score is not None else None,
        }
    
    # 5️⃣ pair 데이터 구조화 -> 여기만 나중에 바꿀것
    # 예: [{'id': '간호사ID', 'request': '같이해주세요', 'weight': -1.5}]
    pair_data = []
    for p in pair_rows:
        pair_data.append({
            "id": p.target_id,
            "request": p.partial_request,
            "weight": float(p.score) if p.score is not None else 0.0,
        })

    # 6️⃣ 최종 JSON 구성 (Front 기대 형식)
    preference_data = {
        "request": target_wr.request,  # 상위 텍스트 그대로
        "shift": shift_data,
        "preference": pair_data,
    }
    # pprint.pprint({'preference_data': preference_data,
    #      'is_submitted': bool(target_wr.is_submitted),
    #       'created_at': target_wr.created_at,
    #        'submitted_at': target_wr.submitted_at})
    return {
        "preference_data": preference_data,
        "is_submitted": bool(target_wr.is_submitted),
        "created_at": target_wr.created_at,
        "submitted_at": target_wr.submitted_at,
    }

# def get_latest_preference_service(year: int, month: int, current_user, db: Session):
#     """
#     최신 선호도 데이터 조회 서비스 함수
#     """
#     if not current_user:
#         raise Exception("Not authenticated")
#     submitted_preference = db.query(ShiftPreference).filter(
#         ShiftPreference.nurse_id == current_user.nurse_id,
#         ShiftPreference.year == year,
#         ShiftPreference.month == month,
#         ShiftPreference.is_submitted == True
#     ).order_by(ShiftPreference.submitted_at.desc()).first()
#     if submitted_preference:
#         return {
#             "preference_data": submitted_preference.data,
#             "is_submitted": True,
#             "created_at": submitted_preference.created_at,
#             "submitted_at": submitted_preference.submitted_at
#         }
#     draft_preference = db.query(ShiftPreference).filter(
#         ShiftPreference.nurse_id == current_user.nurse_id,
#         ShiftPreference.year == year,
#         ShiftPreference.month == month,
#         ShiftPreference.is_submitted == False
#     ).order_by(ShiftPreference.created_at.desc()).first()
#     if draft_preference:
#         pprint.pprint({'preference_data': draft_preference.data,
#          'is_submitted': False,
#           'created_at': draft_preference.created_at,
#            'submitted_at': None})
#         return {
#             "preference_data": draft_preference.data,
#             "is_submitted": False,
#             "created_at": draft_preference.created_at,
#             "submitted_at": None
#         }
#     return {
#         "preference_data": None,
#         "is_submitted": False,
#         "created_at": None,
#         "submitted_at": None
#     }


def get_all_preferences_service(year: int, month: int, current_user, db: Session):
    """
    모든 간호사의 최신 선호도 데이터 조회 서비스 함수 (새 구조 기반)
    - WantedRequest, NurseShiftRequest, NursePairRequest 조합
    - Output은 기존 ShiftPreference.data 구조와 동일하게 유지
    """
    if not current_user:
        raise Exception("Not authenticated")

    month_str = f"{year}-{month:02d}"

    # ✅ 1️⃣ 그룹 내 간호사 목록 가져오기
    nurse_ids = [
        n.nurse_id
        for n in db.query(Nurse.nurse_id)
        .filter(Nurse.group_id == current_user.group_id)
        .all()
    ]
    # ✅ 2️⃣ 각 간호사별 최신 요청(WantedRequest) 찾기
    wanted_requests = (
        db.query(WantedRequest)
        .filter(
            WantedRequest.nurse_id.in_(nurse_ids),
            WantedRequest.month == month_str,
            WantedRequest.is_submitted == True,
        )
        .order_by(WantedRequest.nurse_id, WantedRequest.submitted_at.desc())
        .all()
    )
    # ✅ 3️⃣ nurse_id별 최신 submitted request만 남기기
    latest_wr_map = {}
    for wr in wanted_requests:
        if wr.nurse_id not in latest_wr_map:
            latest_wr_map[wr.nurse_id] = wr
    results = []

    # ✅ 4️⃣ 각 nurse_id에 대해 shift/pair 요청 조회 및 JSON 구성
    for nurse_id, wr in latest_wr_map.items():
        # shift 요청들
        shift_rows = (
            db.query(NurseShiftRequest)
            .filter(
                NurseShiftRequest.nurse_id == nurse_id,
                NurseShiftRequest.request_id == wr.request_id,
                cast(NurseShiftRequest.shift_date, String).like(f"{month_str}-%"),
            )
            .all()
        )
        shift_data = {"D": {}, "E": {}, "N": {}, "O": {}}
        for s in shift_rows:
            shift_type = s.shift.upper()
            day = str(int(str(s.shift_date).split("-")[-1]))  # 날짜만 추출 (문자열 키)
            if shift_type in shift_data:
                shift_data[shift_type][day] = int(s.score) if s.score is not None else 0

        # pair 요청들
        pair_rows = (
            db.query(NursePairRequest)
            .filter(
                NursePairRequest.nurse_id == nurse_id,
                NursePairRequest.request_id == wr.request_id,
            )
            .all()
        )
        pair_data = [
            {"id": p.target_id, "weight": p.score}
            for p in pair_rows
        ]
        # ✅ data JSON 구성
        data_json = {
            "request": wr.request,
            "shift": {k: v for k, v in shift_data.items() if v},
            "preference": pair_data,
        }
        results.append({
            "nurse_id": nurse_id,
            "year": year,
            "month": month,
            "is_submitted": bool(wr.is_submitted),
            "created_at": wr.created_at,
            "submitted_at": wr.submitted_at,
            "data": data_json,
        })

    return results

# def get_all_preferences_service(year: int, month: int, current_user, db: Session):
#     """
#     모든 간호사의 최신 선호도 데이터 조회 서비스 함수
#     """
#     if not current_user:
#         raise Exception("Not authenticated")
#     print('들어옴')
#     preferences = db.query(ShiftPreference).filter(
#         ShiftPreference.year == year,
#         ShiftPreference.month == month,
#         ShiftPreference.is_submitted == True
#     ).join(Nurse, ShiftPreference.nurse_id == Nurse.nurse_id).filter(
#         Nurse.group_id == current_user.group_id
#     ).order_by(ShiftPreference.submitted_at.desc()).all()
#     print('preferences', [s.__dict__ for s in preferences])
#     latest_prefs = {}
#     for pref in preferences:
#         if pref.nurse_id not in latest_prefs:
#             latest_prefs[pref.nurse_id] = pref
#     print('latest_prefs')
#     pprint.pprint([s.__dict__ for s in latest_prefs.values()])
#     return list(latest_prefs.values()) 