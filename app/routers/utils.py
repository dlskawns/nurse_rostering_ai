import time
from collections import defaultdict
from calendar import monthrange

def get_days_in_month(year, month):
    return monthrange(year, month)[1]


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
        for key, day_map in data.get("shift", {}).items():


            for day_str, wt in day_map.items():
                if key.upper() == "OFF":
                    off_requests[nurse_id][day_str] = wt
                else:
                    shift_prefs[nurse_id][key][day_str] = wt
        for prekey in data.get("preference", {}):  
            if prekey['weight'] >= 0:
                pair_prefs["work_together"].append({"nurse_1": nurse_id, "nurse_2": prekey['id'], "weight": prekey['weight']})
            else:
                pair_prefs["work_apart"].append({"nurse_1": nurse_id, "nurse_2": prekey['id'], "weight": abs(prekey['weight'])})

    return shift_prefs, off_requests, pair_prefs