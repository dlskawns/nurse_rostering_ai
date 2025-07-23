import random
from routers.utils import get_days_in_month


def generate_roster(nurses, preferences, year, month):
    """
    간호사 목록과 선호도를 기반으로 근무표를 생성합니다.

    Args:
        nurses (list): 간호사 정보 딕셔너리 리스트.
        preferences (list): 선호도 정보 딕셔너리 리스트.
        year (int): 근무표 년도.
        month (int): 근무표 월.

    Returns:
        dict: {nurse_id: [shift_day1, shift_day2, ...]} 형태의 근무표.
    """
    days_in_month = get_days_in_month(year, month)
    shifts = ["D", "E", "N", "O"] # O for OFF
    roster = {nurse['nurse_id']: [''] * days_in_month for nurse in nurses}
    
    # 1. 선호도 기반으로 근무 배정
    prefs_by_nurse = {p['nurse_id']: p['data'] for p in preferences}
    
    for nurse_id, data in prefs_by_nurse.items():
        # Wanted Shift (D, E, N)
        if 'shift' in data and data['shift']:
            for shift_type, dates in data['shift'].items():
                normalized_shift = shift_type.upper()
                if normalized_shift == 'OFF':
                    normalized_shift = 'O'

                if normalized_shift not in shifts:
                    continue
                
                for date_str in dates.keys():
                    try:
                        day_index = int(date_str) - 1
                        if 0 <= day_index < days_in_month:
                            roster[nurse_id][day_index] = normalized_shift
                    except (ValueError, TypeError):
                        pass # 날짜가 숫자가 아니면 무시
        # OFF
        if 'off' in data and data['off']:
             for date_str in data['off']:
                try:
                    day_index = int(date_str) - 1
                    if 0 <= day_index < days_in_month:
                        roster[nurse_id][day_index] = "O"
                except (ValueError, TypeError):
                    pass # 날짜가 숫자가 아니면 무시

    # 2. 나머지 비어있는 슬롯 채우기 (간단한 랜덤 배정)
    for nurse_id in roster:
        for day in range(days_in_month):
            if roster[nurse_id][day] == '':
                # 이전 근무가 N이면 D를 피하는 등의 간단한 규칙 추가 가능
                roster[nurse_id][day] = random.choice(shifts)

    # 최종 결과 포맷팅
    final_roster = {}
    for nurse_id, schedule in roster.items():
        final_roster[nurse_id] = [s if s else "O" for s in schedule] # 혹시 빈칸이 있으면 OFF로

    return final_roster 