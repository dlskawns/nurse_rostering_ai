from pydantic import BaseModel, Field
from typing import List, Dict


class DailyShiftMonthQuery(BaseModel):
    """월의 일자별 근무 인원 조회 요청 스키마.
    - 인자: office_id(str), group_id(str), year(int), month(int)
    - 반환 없음
    - 예시: year=2025, month=7
    """
    office_id: str = Field(..., description="오피스 ID")
    group_id: str = Field(..., description="그룹 ID")
    year: int
    month: int


class DailyShiftMonthResponse(BaseModel):
    """월 조회 응답 구조.
    - month_summary: 1일차 기준 요약 D/E/N
    - date: D_count/E_count/N_count 각 리스트(1~말일 길이)
    - 예시: date.D_count=[3,3,3]
    """
    office_id: str
    group_id: str
    year: int
    month: int
    month_summary: Dict[str, int]
    date: Dict[str, List[int]]


class DailyShiftMonthlyUpdate(BaseModel):
    """월 전체 일괄 업데이트 요청.
    - 인자: office_id, group_id, year, month, day, evening, night, apply_globally
    - 예시: day=4, evening=3, night=2
    """
    office_id: str
    group_id: str
    year: int
    month: int
    day: int
    evening: int
    night: int
    apply_globally: bool = True


class DailyShiftDailyUpdate(BaseModel):
    """일자별 배열 업데이트 요청.
    - 인자: office_id, group_id, year, month, D/E/N 리스트
    - 예시: D=[1,3,3], E=[2,2,2], N=[2,2,1]
    """
    office_id: str
    group_id: str
    year: int
    month: int
    D: List[int]
    E: List[int]
    N: List[int]