import os
from typing import Dict, List
from calendar import monthrange

from db.client2 import msdb_manager


def _days_in_month(year: int, month: int) -> int:
    """해당 월의 일수를 반환합니다. 예: 2024/2 -> 29"""
    return monthrange(year, month)[1]


def get_or_init_month(office_id: str, group_id: str, year: int, month: int) -> Dict:
    """MSSQL(dbo.daily_shift)에서 월 데이터를 조회합니다. 없으면 shift_manage 템플릿으로 생성 후 반환합니다.
    - month_summary는 1일차 값을 사용합니다.
    """
    # 1) 존재 여부 확인
    cnt = msdb_manager.fetch_one(
        """
        SELECT COUNT(*)
        FROM dbo.daily_shift
        WHERE office_id=%s AND group_id=%s AND [year]=%s AND [month]=%s
        """,
        (office_id, group_id, year, month),
    )

    if cnt == 0:
        # 템플릿 읽어 일수만큼 생성
        sql_init = """
DECLARE @D INT, @E INT, @N INT;
SELECT
  @D = MAX(CASE WHEN shift_slot=1 THEN manpower END),
  @E = MAX(CASE WHEN shift_slot=2 THEN manpower END),
  @N = MAX(CASE WHEN shift_slot=3 THEN manpower END)
FROM dbo.shift_manage
WHERE office_id=%s AND group_id=%s AND nurse_class='RN' AND shift_slot IN (1,2,3);
IF @D IS NULL OR @E IS NULL OR @N IS NULL
  THROW 50001, 'shift_manage 템플릿(RN) 없음', 1;
DECLARE @Days INT = DAY(EOMONTH(DATEFROMPARTS(%s, %s, 1)));
;WITH Days AS (
  SELECT 1 AS d
  UNION ALL SELECT d+1 FROM Days WHERE d+1 <= @Days
)
INSERT INTO dbo.daily_shift (office_id, group_id, [year], [month], [day], d_count, e_count, n_count)
SELECT %s, %s, %s, %s, d, @D, @E, @N FROM Days OPTION (MAXRECURSION 200);
        """
        msdb_manager.execute(sql_init, (office_id, group_id, year, month, office_id, group_id, year, month))

    # 2) 조회
    rows = msdb_manager.fetch_all(
        """
        SELECT [day], d_count, e_count, n_count
        FROM dbo.daily_shift
        WHERE office_id=%s AND group_id=%s AND [year]=%s AND [month]=%s
        ORDER BY [day]
        """,
        (office_id, group_id, year, month),
    )
    d_list = [int(r[1]) if not isinstance(r, dict) else int(r["d_count"]) for r in rows]
    e_list = [int(r[2]) if not isinstance(r, dict) else int(r["e_count"]) for r in rows]
    n_list = [int(r[3]) if not isinstance(r, dict) else int(r["n_count"]) for r in rows]

    return {
        "office_id": office_id,
        "group_id": group_id,
        "year": year,
        "month": month,
        "month_summary": {
            "D_count": d_list[0] if d_list else 0,
            "E_count": e_list[0] if e_list else 0,
            "N_count": n_list[0] if n_list else 0,
        },
        "date": {"D_count": d_list, "E_count": e_list, "N_count": n_list},
    } 