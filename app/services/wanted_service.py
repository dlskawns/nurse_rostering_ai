"""
Wanted(근무 희망 요청) 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Wanted, Nurse, ShiftPreference
from schemas.roster_schema import WantedInvokeRequest, WantedDeadlineRequest
from schemas.auth_schema import User as UserSchema
from datetime import datetime, date
from typing import Dict, Any, List, Tuple
from db.models import WantedRequest, NurseShiftRequest, NursePairRequest
from services.graph_service import graph_service


def _yyyymm(year: int, month: int) -> str:
    """연/월을 'YYYY-MM' 문자열로 변환합니다.

    인자:
        year: 연도
        month: 월(1~12)

    반환:
        'YYYY-MM' 형식의 문자열. 예: 2025, 9 → '2025-09'
    """
    return f"{year:04d}-{month:02d}"


def _ymd(year: int, month: int, day: int) -> date:
    """연/월/일을 date 객체로 변환합니다.

    인자:
        year: 연도
        month: 월(1~12)
        day: 일(1~31)

    반환:
        date 객체. 예: 2025, 9, 26 → date(2025, 9, 26)
    """
    return date(year, month, day)


def _next_request_id(db: Session, nurse_id: str, month_str: str) -> int:
    """해당 간호사/월 기준 다음 request_id 를 생성합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID
        month_str: 'YYYY-MM'

    반환:
        다음 request_id (최초면 1)
    """
    row = (
        db.query(WantedRequest.request_id)
        .filter(WantedRequest.nurse_id == nurse_id, WantedRequest.month == month_str)
        .order_by(WantedRequest.request_id.desc())
        .with_for_update()
        .first()
    )
    return (row[0] + 1) if row else 1


def _persist_wanted_request(db: Session, nurse_id: str, month_str: str, request: str | List[str]) -> int:
    """wanted_requests 레코드를 저장하고 request_id 를 반환합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID
        month_str: 'YYYY-MM'
        request: 요청 텍스트 (문자열 또는 리스트)

    반환:
        새로 생성된 request_id
    
    Notes:
        request가 리스트인 경우 '\n'로 join하여 문자열로 변환
    """
    request_id = _next_request_id(db, nurse_id, month_str)
    
    # request가 리스트면 문자열로 변환
    if isinstance(request, list):
        # '기존 데이터에서 로드됨' 제외하고 join
        filtered_requests = [r for r in request if r != '기존 데이터에서 로드됨']
        request_text = '\n'.join(filtered_requests) if filtered_requests else '기존 데이터 업데이트'
    else:
        request_text = request
    print(f'request_text, {request_text}')
    wr = WantedRequest(
        nurse_id=nurse_id,
        request_id=request_id,
        request=request_text,
        month=month_str,
        is_submitted=0,
        created_at=datetime.now(),
        submitted_at=None,
    )
    db.add(wr)
    try:
        db.commit()
    except Exception as e:
        print(f"wanted_requests 저장 오류: {e}")
        db.rollback()
        raise e
    print(f"wanted_requests 저장 완료: nurse_id={nurse_id}, month={month_str}, request_id={request_id}")
    return request_id


def _next_detailed_request_id(db: Session, nurse_id: str, request_id: int, *, table: str) -> int:
    """해당 (nurse_id, request_id) 범위에서 다음 detailed_request_id 를 생성합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID (문자열)
        request_id: 상위 요청 식별자
        table: 'shift' 또는 'pair'

    반환:
        다음 detailed_request_id (최초면 1)
    """
    if table == "shift":
        q = db.query(NurseShiftRequest.detailed_request_id).filter(
            NurseShiftRequest.nurse_id == nurse_id,
            NurseShiftRequest.request_id == request_id,
        )
    elif table == "pair":
        q = db.query(NursePairRequest.detailed_request_id).filter(
            NursePairRequest.nurse_id == nurse_id,
            NursePairRequest.request_id == request_id,
        )
    else:
        raise ValueError("table 인자는 'shift' 또는 'pair' 여야 합니다.")
    row = q.order_by((NurseShiftRequest.detailed_request_id if table == "shift" else NursePairRequest.detailed_request_id).desc()).first()
    return (row[0] + 1) if row else 1


def _persist_shift_results(
    db: Session,
    nurse_id: str,
    request_id: int,
    year: int,
    month: int,
    shift_map: Dict[str, Dict[int, float]],
) -> None:
    """shift 결과를 nurse_shift_requests 테이블에 저장합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID
        request_id: 상위 wanted_requests.request_id
        year, month: 날짜 조합용
        shift_map: {'D': {12: {'score': 2.5, 'request': '...'}}, ...}
    
    Notes:
        detailed_request_id는 기존 데이터 다음 순번부터 시작
    """
    # detailed_request_id 는 (nurse_id, request_id) 내에서 기존 데이터 다음부터 증가
    detailed_id = _next_detailed_request_id(db, nurse_id, request_id, table="shift")
    rows = 0
    print(f'shift_map (저장 시작, detailed_id={detailed_id}): {shift_map}')
    try:
        for shift_code, by_day in (shift_map or {}).items():
            for day, info in (by_day or {}).items():
                score = info.get("score")
                partial_request = info.get("request")
                row = NurseShiftRequest(
                    nurse_id=nurse_id,
                    request_id=request_id,
                    detailed_request_id=detailed_id,
                    shift_date=_ymd(year, month, int(day)),
                    shift=shift_code,
                    score=float(score),
                    partial_request=partial_request,
                )
                db.merge(row)
                rows += 1
                detailed_id += 1
        
        db.commit()
        print(f"nurse_shift_requests 저장 완료: 시작 detailed_request_id={detailed_id - rows}, 종료={detailed_id - 1}, 저장 rows={rows}")
    except Exception as e:
        print(f"nurse_shift_requests 저장 오류: {e}")
        db.rollback()
        raise e

def _persist_pair_results(
    db: Session,
    nurse_id: str,
    request_id: int,
    pairs: List[Dict[str, float]],
) -> None:
    """pair 결과를 nurse_pair_requests 테이블에 저장합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID
        request_id: 상위 wanted_requests.request_id
        pairs: [{"id": "12", "weight": -1.5, "request": "..."}, ...]
    
    Notes:
        detailed_request_id는 기존 데이터 다음 순번부터 시작
    """
    detailed_id = _next_detailed_request_id(db, nurse_id, request_id, table="pair")
    rows = 0
    for item in pairs or []:
        try:
            target_id = item.get("id") if item.get("id") is not None else None
            weight = float(item.get("weight")) if item.get("weight") is not None else None
            request = item.get("request")
        except Exception as e:
            print(f'pair 데이터 파싱 오류: {e}')
            continue
        if target_id is None or weight is None:
            continue
        row = NursePairRequest(
            nurse_id=nurse_id,
            request_id=request_id,
            detailed_request_id=detailed_id,
            target_id=target_id,
            score=weight,
            partial_request=request,
        )
        db.merge(row)
        rows += 1
        detailed_id += 1
    
    db.commit()
    print(f"nurse_pair_requests 저장 완료: 시작 detailed_request_id={detailed_id - rows}, 종료={detailed_id - 1}, 저장 rows={rows}")


def _parse_shift_results(
    response: List[List[Dict[str, Any]]]
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    그래프 결과에서 shift_result를 모아
    {'E': {4: {'score': 1.9, 'request': '4일은 E로 주세요'}}, ...}
    형태로 변환합니다.
    """
    parsed: Dict[str, Dict[int, Dict[str, Any]]] = {}

    if not isinstance(response, list):
        return parsed

    for sub in response:
        if not isinstance(sub, list):
            continue

        for entry in sub:
            shift_results = entry.get("shift_result")
            if not isinstance(shift_results, list):
                continue

            for sr in shift_results:
                # nested 구조 평탄화
                record = (
                    sr["result"]
                    if isinstance(sr, dict) and "result" in sr and isinstance(sr["result"], dict)
                    else sr
                )

                if not isinstance(record, dict) or "shift" not in record:
                    continue

                shift = record.get("shift")
                dates = record.get("date") or []
                scores = record.get("score") or []
                requests = record.get("request") or []

                if not isinstance(dates, list) or not isinstance(scores, list):
                    continue
                if not isinstance(requests, list):
                    # 단일 문자열로 들어오면 리스트로 감싸기
                    requests = [requests]

                n = min(len(dates), len(scores), len(requests) if requests else len(dates))

                bucket = parsed.setdefault(str(shift), {})
                for i in range(n):
                    try:
                        d = int(dates[i])
                        s = float(scores[i])
                        req = requests[i] if i < len(requests) else None
                    except (TypeError, ValueError):
                        continue

                    bucket[d] = {"score": s, "request": req}

    return parsed



def _parse_preferences(response: List[List[Dict[str, Any]]], schema: List[Dict[str, Any]] | None = None) -> List[Dict[str, float]]:
    """그래프 결과에서 preference_result를 [{'id': '12', 'weight': -1.5}, ...]로 변환합니다.

    인자:
        response: 그래프 전체 응답
        schema: 유효한 간호사 ID 필터링용 스키마

    반환:
        선호 리스트
    """
    parsed: List[Dict[str, float]] = []
    valid_nurse_ids = set()
    if schema:
        for nurse in schema:
            if isinstance(nurse, dict) and 'nurse_id' in nurse:
                valid_nurse_ids.add(str(nurse['nurse_id']))
    for sub in response:
        if not isinstance(sub, list):
            continue
        for entry in sub:
            pref_list = entry.get("preference_result", [])
            if not isinstance(pref_list, list):
                continue
            for pr in pref_list:
                _id = pr.get("id")
                weight = pr.get("weight")
                request = pr.get("request")
                if _id is None or weight is None:
                    continue
                _id_str = str(_id)
                if valid_nurse_ids and _id_str not in valid_nurse_ids:
                    print(f"Parse Preferences: 무효한 간호사 ID '{_id_str}' 필터링됨")
                    continue
                try:
                    parsed.append({"id": _id_str, "weight": float(weight), "request": request})
                except (ValueError, TypeError):
                    continue
    return parsed


def _copy_existing_requests_to_new(
    db: Session,
    nurse_id: str,
    old_request_id: int,
    new_request_id: int,
    year: int,
    month: int,
    case_filter: set = None,
) -> Tuple[int, int]:
    """기존 request_id의 데이터를 새 request_id로 복사합니다.

    인자:
        db: DB 세션
        nurse_id: 간호사 ID
        old_request_id: 기존 request_id
        new_request_id: 새 request_id
        year: 연도
        month: 월
        case_filter: 복사할 (day, shift) 튜플 set (None이면 전체 복사)

    반환:
        (복사된 shift 수, 복사된 pair 수) 튜플
        
    Notes:
        case_filter가 있으면 해당 (day, shift)만 복사 (캘린더에서 지운 항목 제외)
    """
    # 1. 기존 shift 데이터 복사
    old_shift_rows = (
        db.query(NurseShiftRequest)
        .filter(
            NurseShiftRequest.nurse_id == nurse_id,
            NurseShiftRequest.request_id == old_request_id,
        )
        .all()
    )
    
    shift_count = 0
    detailed_id = 1
    for old_row in old_shift_rows:
        # case_filter가 있으면 필터링
        if case_filter is not None:
            day = int(str(old_row.shift_date).split('-')[2])
            shift = old_row.shift
            if (day, shift) not in case_filter:
                print(f"필터링됨: {day}일 {shift} (case에 없음)")
                continue
        
        new_row = NurseShiftRequest(
            nurse_id=nurse_id,
            request_id=new_request_id,
            detailed_request_id=detailed_id,
            shift_date=old_row.shift_date,
            shift=old_row.shift,
            score=old_row.score,
            partial_request=old_row.partial_request,
        )
        print(f'new_row', new_row.__dict__)
        db.merge(new_row)
        shift_count += 1
        detailed_id += 1
    
    if shift_count > 0:
        db.commit()
        print(f"기존 shift 데이터 복사 완료: {shift_count}건")
    
    # 2. 기존 pair 데이터 복사
    old_pair_rows = (
        db.query(NursePairRequest)
        .filter(
            NursePairRequest.nurse_id == nurse_id,
            NursePairRequest.request_id == old_request_id,
        )
        .all()
    )
    print(f'old_pair_rows',old_pair_rows)
    pair_count = 0
    detailed_id = 1
    for old_row in old_pair_rows:
        new_row = NursePairRequest(
            nurse_id=nurse_id,
            request_id=new_request_id,
            detailed_request_id=detailed_id,
            target_id=old_row.target_id,
            score=old_row.score,
            partial_request=old_row.partial_request or '기존 데이터에서 로드됨',
        )
        db.merge(new_row)
        pair_count += 1
        detailed_id += 1
    print(f'pair_count',pair_count)
    if pair_count > 0:
        db.commit()
        print(f"기존 pair 데이터 복사 완료: {pair_count}건")
    return shift_count, pair_count


async def invoke_and_persist_wanted_service(
    req: WantedInvokeRequest,
    current_user: UserSchema,
    db: Session,
) -> Dict[str, Any]:
    """Wanted 그래프 실행 후 결과를 신규 테이블에 저장하고, 기존 응답 구조를 반환합니다.

    인자:
        req: WantedInvokeRequest (프론트 입력과 동일)
        current_user: 현재 로그인 사용자 (간호사)
        db: DB 세션

    반환:
        Dict: 기존 라우터가 반환하던 구조와 호환되는 응답

    예시:
        입력: request="5/5 OFF, 5/6 E", year=2025, month=9
        처리: wanted_requests 1건 + nurse_shift_requests N건 + nurse_pair_requests M건 저장
        
    Notes:
        - case가 있으면: 기존 데이터 복사 + case_results 추가
        - case가 없으면: LLM 결과만 저장 (원래 동작)
    """
    print("그래프 실행 및 DB 저장을 시작합니다.")
    
    nurse_id = current_user.nurse_id
    month_str = _yyyymm(req.year, req.month)
    
    # ======================================================================
    # case 여부 확인
    # ======================================================================
    has_case = req.case is not None and len(req.case) > 0
    print(f'has_case, {has_case}')
    # ======================================================================
    # 1. 그래프 실행
    # ======================================================================
    response = await graph_service.invoke(req.request, req.schema, req.case, req.year, req.month)
    
    # ======================================================================
    # 2. 새 wanted_request 생성
    # ======================================================================
    # new_request_id = _persist_wanted_request(db, nurse_id, month_str, req.request)
    # print(f'new_request_id, {new_request_id}')
    
    # ======================================================================
    # 3. case가 있는 경우: 기존 데이터 복사 + 새 데이터 추가
    # ======================================================================
    if has_case:
        print("case 감지 - 기존 데이터 복사 모드")
        
        # 3-1. case에서 유지할 날짜/shift 파악 (캘린더에서 지운 항목 제외)
        case_filter = set()
        for item in req.case:
            date_str = item.get('date', '')
            shift_type = item.get('shift', '')
            
            # date를 day로 변환
            if isinstance(date_str, str) and '-' in date_str:
                day = int(date_str.split('-')[2])
            else:
                day = int(date_str)
            
            case_filter.add((day, shift_type))
        
        print(f"case_filter (유지할 항목): {case_filter}")
        
        # 3-2. 기존 request 찾기
        old_wr = (
            db.query(WantedRequest)
            .filter(
                WantedRequest.nurse_id == nurse_id,
                WantedRequest.month == month_str,
            )
            .order_by(WantedRequest.request_id.desc())
            .first()
        )
    
    # ======================================================================
    # 2. 새 wanted_request 생성
    # ======================================================================
        new_request_id = _persist_wanted_request(db, nurse_id, month_str, old_wr.request if old_wr else '캘린더 선택')
        print(f'new_request_id, {new_request_id}')
        
        # 3-3. 기존 데이터가 있으면 필터링해서 복사
        if old_wr:
            print(f"기존 데이터 발견: request_id={old_wr.request_id}, 복사 시작")
            try:
                _copy_existing_requests_to_new(
                    db=db,
                    nurse_id=nurse_id,
                    old_request_id=old_wr.request_id,
                    new_request_id=new_request_id,
                    year=req.year,
                    month=req.month,
                    case_filter=case_filter,  # 필터 전달
                )
            except Exception as e:
                print(f"기존 데이터 복사 오류: {e}")
                raise e
        else:
            print("복사할 기존 데이터 없음")
        
        # 3-3. case_results 추가 (뒷 순번으로)
        try:
            print(f'response',response)
            shift_parsed = _parse_shift_results(response)
            print(f'shift_parsed (case_results), {shift_parsed}')
        except Exception as e:
            print(f"shift_parsed 파싱 오류: {e}")
            raise e
        
        if shift_parsed:
            _persist_shift_results(
                db=db,
                nurse_id=nurse_id,
                request_id=new_request_id,
                year=req.year,
                month=req.month,
                shift_map=shift_parsed,
            )
    
    # ======================================================================
    # 4. case가 없는 경우: 원래대로 LLM 결과만 저장
    # ======================================================================
    else:
    # ======================================================================
    # 2. 새 wanted_request 생성
    # ======================================================================
        new_request_id = _persist_wanted_request(db, nurse_id, month_str, req.request)
        print(f'new_request_id, {new_request_id}')

        print("일반 LLM 모드 - 새 데이터만 저장")
        print(f'response',response)
        shift_parsed = _parse_shift_results(response)
        print(f'shift_parsed (LLM 결과), {shift_parsed}')
        
        if shift_parsed:
            _persist_shift_results(
                db=db,
                nurse_id=nurse_id,
                request_id=new_request_id,
                year=req.year,
                month=req.month,
                shift_map=shift_parsed,
            )

        pref_parsed = _parse_preferences(response, req.schema)
        if pref_parsed:
            _persist_pair_results(
                db=db,
                nurse_id=nurse_id,
                request_id=new_request_id,
                pairs=pref_parsed,
            )

    # ======================================================================
    # 5. 결과 반환
    # ======================================================================
    shift_parsed = _parse_shift_results(response)
    pref_parsed = _parse_preferences(response, req.schema)
    
    result: Dict[str, Any] = {}
    if shift_parsed:
        result["shift"] = shift_parsed
    if pref_parsed:
        result["preference"] = pref_parsed
    if not result:
        result = ["근무 희망사항이 없습니다."]
    print("그래프 실행 및 DB 저장을 완료했습니다.")
    return result


def request_wanted_shifts_service(req: WantedDeadlineRequest, current_user, db: Session):
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