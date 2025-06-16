from fastapi import APIRouter, HTTPException
from app.schemas.roster_schema import RosterRequest, RosterResponse
from app.services.graph_service import graph_service

router = APIRouter()


from typing import Dict, List, Any, Union



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
    response: List[List[Dict[str, Any]]]
) -> List[Dict[str, float]]:
    """
    2-중 리스트 구조의 preference_result 항목들을 전부 뽑아서
    [{'id': 12, 'weight': -1.5}, {'id': 13, 'weight': 1.5}, ...]
    형태의 리스트로 반환합니다. preference_result 가 없거나
    비어있어도 빈 리스트를 반환하며 에러는 발생하지 않습니다.
    """
    parsed: List[Dict[str, float]] = []

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
                try:
                    parsed.append({"id": int(_id), "weight": float(weight)})
                except (ValueError, TypeError):
                    # 변환 불가능하면 skip
                    continue

    return parsed

@router.post("/invoke", response_model=RosterResponse)
async def invoke_graph(request: RosterRequest):
    """
    그래프를 실행하여 로스터 관련 요청을 처리합니다.
    """
    try:
        result = {}
        response =  await graph_service.invoke(request.request, request.schema)
        print('여기여기여기', response)
        print('\n\n\n\n\n\n응답1:', parse_shift_results(response), '\n\n\n\n\n\n')
        print('\n\n\n\n\n\n응답2:', parse_preferences(response), '\n\n\n\n\n\n')
        if len(response[0]) > 0:
            result['shift'] = parse_shift_results(response)
            
            # for i in range(len(response[0])):
            #     result.append(response[0][i]['shift_result'][j]['result'] for j in range(len(response[0][i]['shift_result'])))
        if len(response[1]) > 0:
            result['preference'] = parse_preferences(response)
            # for i in range(len(response[1])):
        print('결과', result)    #     result.append(response[1][i]['preference_result'][j] for j in range(len(response[1][i]['preference_result'])))
        if result == {}:
            result = ["근무 희망사항이 없습니다."]
        print('\n\n\n\n\n\n응답:', result, '\n\n\n\n\n\n')
        return RosterResponse(response=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 