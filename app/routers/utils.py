import time
from collections import defaultdict
# from mcp.server.fastmcp import FastMCP
from app.services.holiday_pack import (
    get_weekends,
    get_korean_public_holidays,
    serialise,
)

def get_weekend(year: int, month: int):
    """
    Get the specific month and date information for user
    This function returns the month's weekends date information

    Args:
        year (int): A year which the user wants to know the weekend dates of. if there's no information about year, just use today based year
        month (int): A month which the user wants to know the weekend dates of

    Returns:
        list: the weekend dates information of the month
    """
    
    weekends = serialise(get_weekends(year, month))
    return weekends

def get_holidays(year: int, month: int):
    """
    Get the specific month's public holiday information for user
    This function returns the month's public holiday date information

    Args:
        year (int): A year which the user wants to know the public holiday dates of 
        month (int): A month which the user wants to know the public holiday dates of

    Returns:
        list: the public holiday dates information of the month
    """
    
    holidays = serialise(get_korean_public_holidays(year, month))
    return holidays

print(get_holidays(2025, 7))







class Timer:
    """코드 블록의 실행 시간을 측정하는 컨텍스트 매니저"""
    def __init__(self, description):
        self.description = description
        
    def __enter__(self):
        self.start = time.time()
        print(f"\n{self.description} 시작...")
        return self
        
    def __exit__(self, *args):
        self.end = time.time()
        self.duration = self.end - self.start
        print(f"{self.description} 완료: {self.duration:.2f}초 소요")

from collections import defaultdict
from typing import List, Dict, Any, Tuple

def parse_prefs_to_dict(
        records: List[Dict[str, Any]]
) -> Tuple[dict, dict, dict]:
    """
    records → (shift_preferences, off_requests, nurse_pair_preferences)
    ---------------------------------------------------------------
      • shift_preferences
        { nurse_id: { "D":{day:wt,…}, "E":{…}, "N":{…} }, ... }
      • off_requests
        { nurse_id: { day: weight, … }, ... }
      • nurse_pair_preferences
        { "work_together":[{"nurse_1":…,"nurse_2":…,"weight":w},…],
          "work_apart"  :[{"nurse_1":…,"nurse_2":…,"weight":w},…] }
    """
    print('레코드', records)
    shift_prefs  = defaultdict(lambda: defaultdict(dict))
    off_requests = defaultdict(dict)
    pair_prefs   = {"work_together": [], "work_apart": []}

    for rec in records:
        nurse_id = rec["nurse_id"]
        data     = rec.get("data", {})
        # shift 따오기 
        # print(nurse_id, '>>', data)
        for key, day_map in data.get("shift", {}).items():

            # print('nurse_id', nurse_id)
            # print('key',key)
            # print('day_map',day_map)
            # print(f'--------{nurse_id}shift 시작-------')
            for day_str, wt in day_map.items():
            # print('day_str', day_str)
            # print('wt', wt)
                if key.upper() == "OFF":
                    off_requests[nurse_id][day_str] = wt
                else:
                    shift_prefs[nurse_id][key][day_str] = wt
            # print('-------shift 끝--------')
        for prekey in data.get("preference", {}):  
            if prekey['weight'] >= 0:
                pair_prefs["work_together"].append({"nurse_1": nurse_id, "nurse_2": prekey['id'], "weight": prekey['weight']})
            else:
                pair_prefs["work_apart"].append({"nurse_1": nurse_id, "nurse_2": prekey['id'], "weight": abs(prekey['weight'])})

    # # defaultdict → 일반 dict
    # shift_prefs  = {n: dict({s: dict(days) for s, days in sh.items()})
    #                 for n, sh in shift_prefs.items()}
    # off_requests = {n: dict(days) for n, days in off_requests.items()}

    return shift_prefs, off_requests, pair_prefs