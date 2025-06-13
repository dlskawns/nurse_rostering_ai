from fastapi import APIRouter, HTTPException
from app.schemas.roster_schema import RosterRequest, RosterResponse
from app.services.graph_service import graph_service

router = APIRouter()


from typing import Dict, List, Any, Union
from typing import Dict, List, Any

def parse_shift_results(
    response: List[List[Dict[str, Any]]]
) -> Dict[str, Dict[int, float]]:
    """
    응답 리스트에서 shift별 날짜 및 점수를 통합해 반환.

    Args:
        response (List[List[Dict[str, Any]]]): 2중 리스트 구조의 shift_result 응답

    Returns:
        Dict[str, Dict[int, float]]: shift별 날짜-점수 맵
    """
    parsed: Dict[str, Dict[int, float]] = {}

    if not response or not isinstance(response[0], list):
        return parsed  # 구조가 예상과 다르면 빈 딕셔너리 반환

    for entry in response[0]:
        shift_results = entry.get("shift_result", [])
        if not isinstance(shift_results, list):
            continue

        for sr in shift_results:
            result = sr.get("result", {})
            if not isinstance(result, dict):
                continue

            shift = result.get("shift")
            dates = result.get("date", [])
            scores = result.get("score", [])

            if not shift or not isinstance(dates, list) or not isinstance(scores, list):
                continue

            bucket = parsed.setdefault(shift, {})
            for d, s in zip(dates, scores):
                bucket[d] = float(s)

    return parsed

@router.post("/invoke", response_model=RosterResponse)
async def invoke_graph(request: RosterRequest):
    """
    그래프를 실행하여 로스터 관련 요청을 처리합니다.
    """
    try:
        result = []
        response = graph_service.invoke(request.request, request.schema)
        print('\n\n\n\n\n\n응답1:', parse_shift_results(response), '\n\n\n\n\n\n')
        # print('\n\n\n\n\n\n응답2:', response[0][0]['shift_result'][0]['result'], '\n\n\n\n\n\n')
        if len(response[0]) > 0:
            for i in range(len(response[0])):
                result.append(response[0][i]['shift_result'][j]['result'] for j in range(len(response[0][i]['shift_result'])))
        if len(response[1]) > 0:
            for i in range(len(response[1])):
                result.append(response[1][i]['preference_result'][j] for j in range(len(response[1][i]['preference_result'])))
        
        # 'shift_results' in response:
        #     result.append(response['shift_results']['result'][0])
        # if 'preference_results' in response:
        #     result.append(response['preference_results']['result'][0])
        if result == []:
            result = ["근무 희망사항이 없습니다."]
        print('\n\n\n\n\n\n응답:', result, '\n\n\n\n\n\n')
        return RosterResponse(response=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 