from __future__ import annotations

from typing import List, Dict, Tuple
from calendar import monthrange
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, update

from db.models import DailyShift, ShiftManage, Nurse


def _get_month_days(year: int, month: int) -> int:
    """월의 말일(일수)을 반환합니다.
    - 인자: year(int), month(int)
    - 반환: int (해당 월의 일수)
    - 예시: 2024년 2월 → 29
    """
    return monthrange(year, month)[1]


def _read_template_from_shift_manage(db: Session, office_id: str, group_id: str) -> Tuple[int, int, int]:
    """shift_manage에서 RN 클래스의 슬롯(1:D,2:E,3:N)별 manpower를 읽어옵니다.
    - 반환: (day, evening, night)
    - 예시: (3,2,2)
    """
    slots = (
        db.query(ShiftManage)
        .filter(
            ShiftManage.office_id == office_id,
            ShiftManage.group_id == group_id,
            ShiftManage.nurse_class == 'RN',
            ShiftManage.shift_slot.in_([1, 2, 3]),
        )
        .all()
    )
    if not slots or len(slots) < 3:
        raise ValueError("shift_manage 템플릿(RN)이 없습니다.")
    slot_to_value = {s.shift_slot: s.manpower for s in slots}
    return slot_to_value.get(1, 0), slot_to_value.get(2, 0), slot_to_value.get(3, 0)


def _to_response(
    office_id: str,
    group_id: str,
    year: int,
    month: int,
    rows: List[DailyShift],
) -> Dict:
    """DailyShift row 리스트를 응답 포맷으로 변환합니다.
    - month_summary는 1일차 값을 사용합니다.
    """
    rows_sorted = sorted(rows, key=lambda r: r.day)
    d_list = [r.d_count for r in rows_sorted]
    e_list = [r.e_count for r in rows_sorted]
    n_list = [r.n_count for r in rows_sorted]
    month_summary = {
        "D_count": d_list[0] if d_list else 0,
        "E_count": e_list[0] if e_list else 0,
        "N_count": n_list[0] if n_list else 0,
    }
    return {
        "office_id": office_id,
        "group_id": group_id,
        "year": year,
        "month": month,
        "month_summary": month_summary,
        "date": {
            "D_count": d_list,
            "E_count": e_list,
            "N_count": n_list,
        },
    }


def get_or_init_month(db: Session, office_id: str, group_id: str, year: int, month: int) -> Dict:
    """월 단위 데이터를 조회하거나 없으면 shift_manage 템플릿으로 초기화합니다.
    - 예시: 2025/07 조회 시 데이터가 없으면 (D,E,N) = (3,2,2)로 31일 생성
    """
    rows = (
        db.query(DailyShift)
        .filter(
            DailyShift.office_id == office_id,
            DailyShift.group_id == group_id,
            DailyShift.year == year,
            DailyShift.month == month,
        )
        .all()
    )

    if not rows:
        print("[daily_shift] 월 데이터 없음 → shift_manage 기반으로 초기화")
        days = _get_month_days(year, month)
        d, e, n = _read_template_from_shift_manage(db, office_id, group_id)
        for day_idx in range(1, days + 1):
            db.add(
                DailyShift(
                    office_id=office_id,
                    group_id=group_id,
                    year=year,
                    month=month,
                    day=day_idx,
                    d_count=d,
                    e_count=e,
                    n_count=n,
                )
            )
        db.commit()
        rows = (
            db.query(DailyShift)
            .filter(
                DailyShift.office_id == office_id,
                DailyShift.group_id == group_id,
                DailyShift.year == year,
                DailyShift.month == month,
            )
            .all()
        )
    return _to_response(office_id, group_id, year, month, rows)


def update_monthly(
    db: Session,
    office_id: str,
    group_id: str,
    year: int,
    month: int,
    day_cnt: int,
    eve_cnt: int,
    nig_cnt: int,
    apply_globally: bool = True,
) -> Dict:
    """월 전체 일괄 업데이트를 수행합니다.
    - shift_manage 템플릿을 갱신 후 daily_shift의 해당 월 모든 날짜를 동일 값으로 저장합니다.
    - 예시: day=4, evening=3, night=2이면 7월 1..말일을 (4,3,2)로 설정
    """
    days = _get_month_days(year, month)

    if apply_globally:
        # RN, slot 1~3 업데이트
        for slot, value in [(1, day_cnt), (2, eve_cnt), (3, nig_cnt)]:
            db.query(ShiftManage).filter(
                ShiftManage.office_id == office_id,
                ShiftManage.group_id == group_id,
                ShiftManage.nurse_class == 'RN',
                ShiftManage.shift_slot == slot,
            ).update({ShiftManage.manpower: int(value)})

    # 해당 월 데이터가 없다면 우선 생성
    existing = (
        db.query(DailyShift)
        .filter(
            DailyShift.office_id == office_id,
            DailyShift.group_id == group_id,
            DailyShift.year == year,
            DailyShift.month == month,
        )
        .all()
    )
    if not existing:
        for d_idx in range(1, days + 1):
            db.add(
                DailyShift(
                    office_id=office_id,
                    group_id=group_id,
                    year=year,
                    month=month,
                    day=d_idx,
                    d_count=day_cnt,
                    e_count=eve_cnt,
                    n_count=nig_cnt,
                )
            )
    else:
        # 벌크 업데이트
        for r in existing:
            r.d_count = int(day_cnt)
            r.e_count = int(eve_cnt)
            r.n_count = int(nig_cnt)

    db.commit()
    return {"updated": True, "days_affected": days}


def update_daily(
    db: Session,
    office_id: str,
    group_id: str,
    year: int,
    month: int,
    d_list: List[int],
    e_list: List[int],
    n_list: List[int],
) -> Dict:
    """일자별 배열을 그대로 저장합니다.
    - 리스트 길이는 해당 월의 일수와 같아야 합니다.
    - 예시: D=[1,3,3], E=[2,2,3], N=[2,2,2]
    """
    days = _get_month_days(year, month)
    if not (len(d_list) == len(e_list) == len(n_list) == days):
        raise ValueError("리스트 길이가 월의 일수와 다릅니다.")

    # 기존 행 조회
    rows = (
        db.query(DailyShift)
        .filter(
            DailyShift.office_id == office_id,
            DailyShift.group_id == group_id,
            DailyShift.year == year,
            DailyShift.month == month,
        )
        .all()
    )
    rows_map = {r.day: r for r in rows}

    # upsert
    for idx in range(days):
        day_no = idx + 1
        if day_no in rows_map:
            r = rows_map[day_no]
            r.d_count = int(d_list[idx])
            r.e_count = int(e_list[idx])
            r.n_count = int(n_list[idx])
        else:
            db.add(
                DailyShift(
                    office_id=office_id,
                    group_id=group_id,
                    year=year,
                    month=month,
                    day=day_no,
                    d_count=int(d_list[idx]),
                    e_count=int(e_list[idx]),
                    n_count=int(n_list[idx]),
                )
            )
    db.commit()
    return {"updated": True, "days_affected": days} 