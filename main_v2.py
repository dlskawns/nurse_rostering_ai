from datetime import date, datetime, timedelta
import json
import time
import pandas as pd
import numpy as np
from config import NurseRosterConfig
from nurse import Nurse
from roster_system import RosterSystem
from typing import List, Optional

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

def load_test_data(filename):
    """JSON 파일에서 테스트 데이터를 로드합니다."""
    with open(filename, 'r') as f:
        return json.load(f)

def create_nurses_from_data(nurses_data):
    """JSON 데이터로부터 간호사 객체를 생성합니다."""
    nurses = []
    for nurse_data in nurses_data:
        # resignation_date가 있으면 datetime으로 변환
        if 'resignation_date' in nurse_data:
            nurse_data['resignation_date'] = datetime.strptime(
                nurse_data['resignation_date'], '%Y-%m-%d'
            ).date()
        nurses.append(Nurse(**nurse_data))
    return nurses

def export_roster_to_excel(roster_system, filename):
    """근무표를 지표와 요약 정보와 함께 Excel로 내보냅니다."""
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import PatternFill, Font, Alignment
    
    # 근무 배정 DataFrame 생성 (전치된 형식)
    days = pd.date_range(
        start=roster_system.target_month,
        periods=roster_system.num_days,
        freq='D'
    )
    
    # 전치된 DataFrame 생성 - 행은 간호사, 열은 날짜
    df = pd.DataFrame(
        index=[n.name for n in roster_system.nurses],
        columns=[date.strftime('%Y-%m-%d') for date in days]
    )
    
    # 요일 정보를 나중에 두 번째 헤더 행으로 추가
    day_of_week = [date.strftime('%a') for date in days]
    
    # 근무 배정 정보 채우기
    for day in range(roster_system.num_days):
        date_str = days[day].strftime('%Y-%m-%d')
        for n_idx, nurse in enumerate(roster_system.nurses):
            shift_idx = np.where(roster_system.roster[n_idx, day] == 1)[0]
            if len(shift_idx) > 0:
                df.loc[nurse.name, date_str] = roster_system.config.shift_types[shift_idx[0]]
            else:
                df.loc[nurse.name, date_str] = '-'
    
    # 각 간호사의 적용된 휴무 요청 수 계산 및 적용/미적용 날짜 추적
    off_counts = {}
    off_details = {}  # 적용 및 미적용 날짜 저장용
    off_requests = {int(k): v for k, v in load_test_data('test_data.json')['off_requests'].items()}
    
    for nurse_id, requested_days in off_requests.items():
        nurse_idx = next((i for i, n in enumerate(roster_system.nurses) if n.id == nurse_id), None)
        if nurse_idx is None:
            continue
            
        nurse_name = roster_system.nurses[nurse_idx].name
        off_counts[nurse_name] = 0
        applied_days = []
        not_applied_days = []
        
        for day in requested_days:
            if 1 <= day <= roster_system.num_days:  # 해당 월의 날짜인 경우
                off_idx = roster_system.config.shift_types.index('OFF')
                # 실제로 OFF로 설정되었는지 확인
                if roster_system.roster[nurse_idx, day-1, off_idx] == 1:
                    off_counts[nurse_name] = off_counts.get(nurse_name, 0) + 1
                    applied_days.append(str(day))
                else:
                    not_applied_days.append(str(day))
        
        off_details[nurse_name] = {
            'applied': applied_days,
            'not_applied': not_applied_days
        }
    
    # Create a new Excel workbook
    wb = openpyxl.Workbook()
    
    # Create Roster sheet
    ws_roster = wb.active
    ws_roster.title = "근무표"
    
    # Add headers with day of week
    ws_roster.cell(row=1, column=1, value="간호사")
    for col, (date_str, day) in enumerate(zip(df.columns, day_of_week), 2):
        ws_roster.cell(row=1, column=col, value=f"{date_str} ({day})")
    
    # Add nurse data
    for row, nurse_name in enumerate(df.index, 2):
        ws_roster.cell(row=row, column=1, value=nurse_name)
        for col, date_str in enumerate(df.columns, 2):
            ws_roster.cell(row=row, column=col, value=df.loc[nurse_name, date_str])
    
    # Add summary row for each shift type
    shift_types = roster_system.config.shift_types
    start_row = len(df.index) + 3  # Start after all nurses
    
    for i, shift in enumerate(shift_types):
        row = start_row + i
        ws_roster.cell(row=row, column=1, value=f"합계 {shift}")
        
        for col, date_str in enumerate(df.columns, 2):
            # Count cells with this shift value in the column
            count_formula = f'=COUNTIF({get_column_letter(col)}2:{get_column_letter(col)}{len(df.index)+1},"{shift}")'
            ws_roster.cell(row=row, column=col, value=count_formula)
    
    # Add required count row
    row = start_row + len(shift_types)
    ws_roster.cell(row=row, column=1, value="필요 인원")
    
    for col, date_str in enumerate(df.columns, 2):
        day_idx = col - 2
        day_requirements = []
        for shift in ['D', 'E', 'N']:
            if shift in roster_system.config.daily_shift_requirements:
                req = roster_system.config.daily_shift_requirements[shift]
                day_requirements.append(f"{shift}:{req}")
        ws_roster.cell(row=row, column=col, value=", ".join(day_requirements))
    
    # Add OFF request information with detailed applied/not applied days
    row = start_row + len(shift_types) + 2
    ws_roster.cell(row=row, column=1, value="적용된 휴무 요청")
    ws_roster.cell(row=row, column=2, value="횟수")
    ws_roster.cell(row=row, column=3, value="적용된 날짜")
    ws_roster.cell(row=row, column=4, value="미적용된 날짜")
    
    for i, (nurse_name, count) in enumerate(off_counts.items()):
        nurse_row = row + i + 1
        ws_roster.cell(row=nurse_row, column=1, value=nurse_name)
        ws_roster.cell(row=nurse_row, column=2, value=count)
        
        # Add applied days
        if nurse_name in off_details:
            applied_days = ", ".join(off_details[nurse_name]['applied'])
            not_applied_days = ", ".join(off_details[nurse_name]['not_applied'])
            ws_roster.cell(row=nurse_row, column=3, value=applied_days)
            ws_roster.cell(row=nurse_row, column=4, value=not_applied_days)
    
    # Add OFF allocation information
    row = start_row + len(shift_types) + len(off_counts) + 5
    ws_roster.cell(row=row, column=1, value="휴무일 할당 현황")
    ws_roster.cell(row=row, column=2, value="").font = Font(bold=True)
    ws_roster.cell(row=row, column=3, value="").font = Font(bold=True)
    ws_roster.cell(row=row, column=4, value="").font = Font(bold=True)
    
    # Header row for OFF allocations
    row += 1
    ws_roster.cell(row=row, column=1, value="간호사")
    ws_roster.cell(row=row, column=2, value="공통 휴무일")
    ws_roster.cell(row=row, column=3, value="기본 개인 휴무일")
    ws_roster.cell(row=row, column=4, value="개인 조정일")
    ws_roster.cell(row=row, column=5, value="총 할당일")
    ws_roster.cell(row=row, column=6, value="잔여일")
    
    # 각 간호사별 휴무 할당 현황 표시
    for i, nurse in enumerate(roster_system.nurses):
        row += 1
        nurse_name = nurse.name
        global_off = roster_system.config.global_monthly_off_days
        standard_off = roster_system.config.standard_personal_off_days
        personal_adj = nurse.personal_off_adjustment
        total_allocation = global_off + standard_off + personal_adj
        
        # 실제 사용된 휴무일 계산
        off_idx = roster_system.config.shift_types.index('OFF')
        used_offs = np.sum(roster_system.roster[i, :, off_idx])
        remaining = nurse.remaining_off_days
        
        ws_roster.cell(row=row, column=1, value=nurse_name)
        ws_roster.cell(row=row, column=2, value=global_off)
        ws_roster.cell(row=row, column=3, value=standard_off)
        ws_roster.cell(row=row, column=4, value=personal_adj)
        ws_roster.cell(row=row, column=5, value=total_allocation)
        ws_roster.cell(row=row, column=6, value=remaining)
    
    # 워크시트 서식 지정
    for col in range(1, len(df.columns) + 5):  # 휴무 요청 상세 정보 포함하도록 확장
        ws_roster.column_dimensions[get_column_letter(col)].width = 15
    
    # 지표 시트 생성 (요청대로 재구성)
    ws_metrics = wb.create_sheet(title='근무 지표')
    
    # 지표 가져오기
    metrics = roster_system.calculate_metrics()
    
    # 개별 간호사 지표를 위한 상세 지표 가져오기
    try:
        detailed_metrics = roster_system.calculate_detailed_metrics()
    except Exception:
        detailed_metrics = None
    
    # 헤더 행 설정
    ws_metrics.cell(row=1, column=1, value="간호사")
    metric_cols = ["근무 횟수", "미배정 근무", "인원 요구사항 위반", 
                  "경력 요구사항 위반", "연속 근무 위반", "야간 근무 위반", 
                  "주말 근무 분포"]
    
    for col, metric in enumerate(metric_cols, 2):
        ws_metrics.cell(row=1, column=col, value=metric)
    
    # 간호사별 지표 계산
    nurse_specific_metrics = {}
    
    # 먼저, 분배할 전체 지표 추적
    global_metrics = {
        "미배정 근무": metrics.get("unassigned_slots", 0),
        "인원 요구사항 위반": metrics.get("staffing_violations", 0),
        "경력 요구사항 위반": metrics.get("experience_violations", 0),
        "연속 근무 위반": metrics.get("consecutive_violations", 0),
        "야간 근무 위반": metrics.get("night_violations", 0)
    }
    
    # 간호사별 위반 사항 계산
    for n_idx, nurse in enumerate(roster_system.nurses):
        is_night_nurse = nurse.is_night_nurse
        nurse_specific_metrics[nurse.name] = {
            "근무 횟수": metrics.get("nurse_shift_counts", {}).get(nurse.name, {}),
            "주말 근무 분포": metrics.get("weekend_distribution", {}).get(nurse.name, 0),
            "미배정 근무": 0,  # 배정되지 않은 날짜 수 계산 예정
            "연속 근무 위반": 0,
            "야간 근무 위반": 0
        }
        
        # Count unassigned slots
        unassigned_days = 0
        for day in range(roster_system.num_days):
            if not np.any(roster_system.roster[n_idx, day]):
                unassigned_days += 1
        nurse_specific_metrics[nurse.name]["미배정 근무"] = unassigned_days
        
        # Count consecutive work days violations
        for day in range(roster_system.num_days):
            if not roster_system._check_consecutive_work_days(n_idx, day):
                nurse_specific_metrics[nurse.name]["연속 근무 위반"] += 1
        
        # Count night shift violations (only relevant for night nurses)
        if is_night_nurse:
            for day in range(roster_system.num_days):
                if not roster_system._check_night_constraints(n_idx, day):
                    nurse_specific_metrics[nurse.name]["야간 근무 위반"] += 1
        
        # For staffing and experience violations, distribute evenly
        if global_metrics["인원 요구사항 위반"] > 0:
            nurse_specific_metrics[nurse.name]["인원 요구사항 위반"] = "-"
        else:
            nurse_specific_metrics[nurse.name]["인원 요구사항 위반"] = 0
            
        if global_metrics["경력 요구사항 위반"] > 0:
            nurse_specific_metrics[nurse.name]["경력 요구사항 위반"] = "-"
        else:
            nurse_specific_metrics[nurse.name]["경력 요구사항 위반"] = 0
    
    # Add nurse data rows
    for row, nurse_name in enumerate(nurse_specific_metrics.keys(), 2):
        ws_metrics.cell(row=row, column=1, value=nurse_name)
        
        # Add nurse_shift_counts
        shift_counts = nurse_specific_metrics[nurse.name]["근무 횟수"]
        if shift_counts:
            shift_counts_str = ", ".join([f"'{s}': {c}" for s, c in shift_counts.items()])
            shift_counts_str = "{" + shift_counts_str + "}"
            ws_metrics.cell(row=row, column=2, value=shift_counts_str)
        
        # Add other metrics
        ws_metrics.cell(row=row, column=3, value=nurse_specific_metrics[nurse.name]["미배정 근무"])
        ws_metrics.cell(row=row, column=4, value=nurse_specific_metrics[nurse.name]["인원 요구사항 위반"])
        ws_metrics.cell(row=row, column=5, value=nurse_specific_metrics[nurse.name]["경력 요구사항 위반"])
        ws_metrics.cell(row=row, column=6, value=nurse_specific_metrics[nurse.name]["연속 근무 위반"])
        ws_metrics.cell(row=row, column=7, value=nurse_specific_metrics[nurse.name]["야간 근무 위반"])
        ws_metrics.cell(row=row, column=8, value=nurse_specific_metrics[nurse.name]["주말 근무 분포"])
    
    # Add global metrics (in rows beneath nurses)
    global_metrics_row = len(nurse_specific_metrics) + 3
    ws_metrics.cell(row=global_metrics_row, column=1, value="전체 지표")
    
    # Add global metrics values
    ws_metrics.cell(row=global_metrics_row, column=3, value=global_metrics["미배정 근무"])
    ws_metrics.cell(row=global_metrics_row, column=4, value=global_metrics["인원 요구사항 위반"])
    ws_metrics.cell(row=global_metrics_row, column=5, value=global_metrics["경력 요구사항 위반"])
    ws_metrics.cell(row=global_metrics_row, column=6, value=global_metrics["연속 근무 위반"])
    ws_metrics.cell(row=global_metrics_row, column=7, value=global_metrics["야간 근무 위반"])
    
    # Add OFF allocation section to Metrics sheet
    off_section_row = global_metrics_row + 3
    ws_metrics.cell(row=off_section_row, column=1, value="휴무일 설정").font = Font(bold=True)
    ws_metrics.cell(row=off_section_row+1, column=1, value="공통 월간 휴무일")
    ws_metrics.cell(row=off_section_row+1, column=2, value=roster_system.config.global_monthly_off_days)
    ws_metrics.cell(row=off_section_row+2, column=1, value="기본 개인 휴무일")
    ws_metrics.cell(row=off_section_row+2, column=2, value=roster_system.config.standard_personal_off_days)
    
    # Save the workbook
    wb.save(filename)
    print(f"\n근무표가 {filename}에 저장되었습니다.")

class RosterGenerator:
    def __init__(self, roster_system):
        self.roster_system = roster_system
        self.nurses = roster_system.nurses
        self.config = roster_system.config
        self.num_days = roster_system.num_days
        # Initialize all days as OFF
        self.roster_system._initialize_roster()
        
    def _is_weekend(self, day):
        """Check if given day is weekend."""
        return day % 7 >= 5
        
    def _get_available_nurses(self, day, exclude_nurses=None):
        """Get nurses available for work on given day."""
        exclude_nurses = exclude_nurses or set()
        available = []
        
        for n_idx, nurse in enumerate(self.nurses):
            if n_idx in exclude_nurses:
                continue
                
            # Check if nurse already has assignment
            if np.any(self.roster_system.roster[n_idx, day]):
                continue
                
            # Check consecutive work days
            if not self.roster_system._check_consecutive_work_days(n_idx, day):
                continue
                
            # Check night shift constraints
            if not self.roster_system._check_night_constraints(n_idx, day):
                continue
                
            available.append(n_idx)
            
        return available
        
    def _assign_shift(self, nurse_idx, day, shift):
        """Assign a shift to a nurse."""
        # Clear any existing assignments for this day (including OFF)
        self.roster_system.roster[nurse_idx, day] = 0
        # Assign the new shift
        shift_idx = self.config.shift_types.index(shift)
        self.roster_system.roster[nurse_idx, day, shift_idx] = 1
        
    def _get_shift_preference(self, nurse_idx, day, shift):
        """Get nurse's preference for a shift."""
        shift_idx = self.config.shift_types.index(shift)
        return self.roster_system.preference_matrix[nurse_idx, day, shift_idx]
        
    def generate_roster(self):
        """Generate roster with improved constraints handling."""
        print("\nGenerating roster with prioritized constraints...")
        
        # Step 1: Pre-assign OFF days
        self._assign_off_days()
        
        # Step 2: Pre-assign night shifts to night nurses
        self._assign_night_shifts()
        
        # Step 3: Assign remaining shifts (D and E) with better balancing
        for week in range((self.num_days + 6) // 7):
            start_day = week * 7
            end_day = min(start_day + 7, self.num_days)
            self._assign_day_evening_shifts_for_week(start_day, end_day)
        
        # Step 4: Fill any remaining gaps
        self._fill_gaps()
        
    def _assign_off_days(self):
        """Pre-assign OFF days based on patterns and requests."""
        print("Assigning OFF days...")
        off_idx = self.config.shift_types.index('OFF')
        
        for n_idx, nurse in enumerate(self.nurses):
            # Handle head nurse weekend pattern
            if nurse.is_head_nurse:
                for day in range(self.num_days):
                    if self._is_weekend(day):
                        if nurse.head_nurse_off_pattern == 'weekend':
                            self.roster_system.roster[n_idx, day, off_idx] = 1
                        elif nurse.head_nurse_off_pattern == 'mixed' and day % 14 >= 7:
                            self.roster_system.roster[n_idx, day, off_idx] = 1
                            
            # Handle resignation dates
            if nurse.resignation_date:
                resignation_day = (nurse.resignation_date - self.roster_system.target_month).days
                if 0 <= resignation_day < self.num_days:
                    for day in range(resignation_day, self.num_days):
                        self.roster_system.roster[n_idx, day, off_idx] = 1
                        
    def _assign_night_shifts(self):
        """Assign night shifts prioritizing night nurses."""
        print("Assigning night shifts...")
        
        # Sort nurses by night shift preference
        night_nurses = [(n_idx, nurse) for n_idx, nurse in enumerate(self.nurses) 
                       if nurse.is_night_nurse]
        other_nurses = [(n_idx, nurse) for n_idx, nurse in enumerate(self.nurses) 
                       if not nurse.is_night_nurse]
        
        for day in range(self.num_days):
            required = self.config.daily_shift_requirements['N']
            assigned = 0
            
            # First try to assign night nurses
            for n_idx, nurse in night_nurses:
                if assigned >= required:
                    break
                    
                if self._can_assign_shift(n_idx, day, 'N'):
                    self._assign_shift(n_idx, day, 'N')
                    assigned += 1
                    
            # If still need more, use other nurses
            if assigned < required:
                available = [
                    n_idx for n_idx, _ in other_nurses
                    if self._can_assign_shift(n_idx, day, 'N')
                ]
                
                for n_idx in available:
                    if assigned >= required:
                        break
                    self._assign_shift(n_idx, day, 'N')
                    assigned += 1

    def _check_staffing_requirements(self, day):
        """Check if staffing requirements are met for a given day."""
        requirements_met = True
        messages = []
        
        for shift in ['D', 'E', 'N']:
            shift_idx = self.config.shift_types.index(shift)
            required = self.config.daily_shift_requirements[shift]
            assigned = np.sum(self.roster_system.roster[:, day, shift_idx])
            
            if assigned < required:
                requirements_met = False
                messages.append(f"Need {required - assigned} more nurses for {shift} shift")
                
            # Check experienced nurse requirement
            exp_nurses = sum(
                1 for n_idx, nurse in enumerate(self.nurses)
                if (nurse.experience_years >= self.config.min_experience_per_shift and
                    self.roster_system.roster[n_idx, day, shift_idx] == 1)
            )
            
            if exp_nurses < self.config.required_experienced_nurses:
                requirements_met = False
                messages.append(
                    f"Need {self.config.required_experienced_nurses - exp_nurses} "
                    f"more experienced nurses for {shift} shift"
                )
                
        return requirements_met, messages

    def _calculate_fatigue_score(self, nurse_idx: int, day: int) -> float:
        """Calculate fatigue score for a nurse based on recent work history."""
        if day < 1:
            return 0.0
            
        # Look back up to 7 days
        lookback = min(day, 7)
        recent_work = self.roster_system.roster[nurse_idx, day-lookback:day]
        
        # Calculate weighted sum of recent work days
        weights = np.exp(-np.arange(lookback) * 0.5)  # Exponential decay
        work_days = np.sum(recent_work, axis=1) > 0
        fatigue = np.sum(work_days * weights) / np.sum(weights)
        
        return fatigue
        
    def _calculate_assignment_score(self, nurse_idx: int, nurse: Nurse, day: int, shift: str) -> float:
        """Calculate overall score for assigning a nurse to a shift."""
        shift_idx = self.config.shift_types.index(shift)
        score = 0.0
        
        # Base preference score (0-1)
        pref_score = self._get_shift_preference(nurse_idx, day, shift)
        score += 0.4 * pref_score  # 40% weight
        
        # Fatigue score (0-1, inverted so less fatigue is better)
        fatigue = self._calculate_fatigue_score(nurse_idx, day)
        score += 0.3 * (1 - fatigue)  # 30% weight
        
        # Experience bonus for complex shifts
        if shift in ['N', 'E'] and nurse.experience_years >= self.config.min_experience_per_shift:
            score += 0.15  # 15% weight
            
        # Specialization bonus
        if (shift == 'N' and nurse.is_night_nurse) or \
           (nurse.is_head_nurse and shift in ['D', 'E']):
            score += 0.15  # 15% weight
            
        return score

    def _assign_nurses_to_shift(self, day: int, shift: str, required: int) -> List[int]:
        """Assign nurses to a shift using improved scoring system."""
        assigned = []
        available = self._get_available_nurses(day)
        
        if not available:
            return assigned
            
        # Calculate scores for all available nurses
        scores = []
        for n_idx in available:
            if not self._can_assign_shift(n_idx, day, shift):
                continue
            score = self._calculate_assignment_score(n_idx, self.nurses[n_idx], day, shift)
            scores.append((n_idx, score))
            
        # Sort by score and assign best matches
        scores.sort(key=lambda x: x[1], reverse=True)
        for n_idx, _ in scores[:required]:
            self._assign_shift(n_idx, day, shift)
            assigned.append(n_idx)
            
        return assigned

    def _assign_day_evening_shifts_for_week(self, start_day: int, end_day: int):
        """Assign day and evening shifts for a week with improved balancing."""
        shifts = ['D', 'E']
        days = range(start_day, end_day)
        
        # First pass: assign based on preferences and scores
        for day in days:
            for shift in shifts:
                required = self.config.daily_shift_requirements[shift]
                self._assign_nurses_to_shift(day, shift, required)
                
        # Second pass: balance workload within the week
        self._balance_weekly_workload(start_day, end_day)
        
    def _balance_weekly_workload(self, start_day: int, end_day: int):
        """Balance workload within a week to avoid overwork."""
        shifts = ['D', 'E']
        
        # Calculate weekly workload for each nurse
        workloads = {}
        for n_idx, nurse in enumerate(self.nurses):
            work_days = 0
            for day in range(start_day, end_day):
                if np.any(self.roster_system.roster[n_idx, day, :-1]):  # Exclude OFF
                    work_days += 1
            workloads[n_idx] = work_days
            
        # Identify overworked nurses (more than 5 days in the week)
        overworked = [n_idx for n_idx, days in workloads.items() if days > 5]
        
        # Try to redistribute some shifts
        for n_idx in overworked:
            for day in range(start_day, end_day):
                for shift in shifts:
                    shift_idx = self.config.shift_types.index(shift)
                    if self.roster_system.roster[n_idx, day, shift_idx] == 1:
                        # Try to find a replacement
                        replacement = self._find_replacement(n_idx, day, shift)
                        if replacement is not None:
                            # Swap assignments
                            self._assign_shift(replacement, day, shift)
                            self.roster_system.roster[n_idx, day] = 0
                            break
                            
    def _find_replacement(self, current_nurse_idx: int, day: int, shift: str) -> Optional[int]:
        """Find a replacement nurse for a shift assignment."""
        available = self._get_available_nurses(day, {current_nurse_idx})
        
        best_score = -1
        best_nurse = None
        
        for n_idx in available:
            if not self._can_assign_shift(n_idx, day, shift):
                continue
                
            score = self._calculate_assignment_score(n_idx, self.nurses[n_idx], day, shift)
            if score > best_score:
                best_score = score
                best_nurse = n_idx
                
        return best_nurse

    def _fill_gaps(self):
        """Fill any remaining gaps in the roster."""
        print("Filling remaining gaps in roster...")
        
        for day in range(self.num_days):
            # Find unassigned nurses
            unassigned = [
                idx for idx in range(len(self.nurses))
                if not np.any(self.roster_system.roster[idx, day])
            ]
            
            # Set them to OFF
            off_idx = self.config.shift_types.index('OFF')
            for idx in unassigned:
                self.roster_system.roster[idx, day, off_idx] = 1

    def _can_assign_shift(self, nurse_idx, day, shift):
        """Check if a nurse can be assigned to a shift."""
        # Check if already assigned
        if np.any(self.roster_system.roster[nurse_idx, day]):
            return False
        
        nurse = self.nurses[nurse_idx]
        
        # Night nurse restrictions
        if nurse.is_night_nurse and shift in ['D', 'E']:
            return False
        
        # Check consecutive work days
        if not self.roster_system._check_consecutive_work_days(nurse_idx, day):
            return False
        
        # Check night shift constraints
        if shift == 'N' and not self.roster_system._check_night_constraints(nurse_idx, day):
            return False
        
        # Check head nurse weekend pattern
        if (nurse.is_head_nurse and nurse.head_nurse_off_pattern == 'weekend' and
            self._is_weekend(day)):
            return False
        
        return True

def main():
    """메인 함수"""
    print("\n=== 간호사 근무표 생성 시스템 V2 시작 (전역 최적화 적용) ===")
    
    # OR-Tools 설치 확인
    try:
        import ortools
    except ImportError:
        print("\nOR-Tools 설치 중...")
        import subprocess
        subprocess.check_call(["pip", "install", "ortools"])
    
    # 테스트 데이터 로드
    with Timer("테스트 데이터 로드"):
        data = load_test_data('test_data.json')
        
    # 간호사 객체 생성
    with Timer("간호사 객체 생성"):
        nurses = create_nurses_from_data(data['nurses'])
        print(f"{len(nurses)}명의 간호사 객체가 생성되었습니다.")
        
    # 설정된 전역 월간 휴무일로 설정 생성
    with Timer("설정 초기화"):
        config_data = data['config']
        
        # 전역 월간 휴무일이 설정에 있는지 확인
        if 'global_monthly_off_days' not in config_data:
            print(f"기본 전역 월간 휴무일 사용: 3일")
            config_data['global_monthly_off_days'] = 3
        else:
            print(f"설정된 전역 월간 휴무일 사용: {config_data['global_monthly_off_days']}일")
            
        config = NurseRosterConfig(**config_data)
        
        # 설정에 따라 각 간호사의 휴무일 초기화
        total_personal_off = 0
        for nurse in nurses:
            avail_days = nurse.initialize_off_days(config)
            total_personal_off += avail_days
            
        print(f"간호사 휴무일 초기화 완료: 총 {total_personal_off}일의 개인 휴무일")
        print(f"전역 월간 휴무일: {config.global_monthly_off_days}일")
        
    # 근무표 시스템 생성
    with Timer("근무표 시스템 초기화"):
        target_month = datetime.strptime(data['target_month'], '%Y-%m-%d').date()
        roster_system = RosterSystem(
            nurses=nurses,
            target_month=target_month,
            config=config
        )
        print(f"{target_month.strftime('%Y년 %m월')} 근무표 시스템이 초기화되었습니다.")
    
    # 먼저 휴무 요청 적용 (하드 제약조건으로)
    with Timer("휴무 요청 적용"):
        off_requests = {int(k): v for k, v in data['off_requests'].items()}
        roster_system.apply_off_requests(off_requests)
        print(f"{len(off_requests)}개의 휴무 요청이 적용되었습니다.")
    
    # RosterGenerator를 사용하여 초기 근무표 생성
    with Timer("초기 근무표 생성"):
        generator = RosterGenerator(roster_system)
        generator.generate_roster()
        
    # CP-SAT를 사용한 전역 최적화
    with Timer("CP-SAT를 사용한 근무표 최적화 (전역 최적화)"):
        success = roster_system.optimize_roster_with_cp_sat(time_limit_seconds=60)
        if success:
            print("전역 최적화가 성공적으로 완료되었습니다!")
        else:
            print("전역 최적화 실패, LNS 접근법으로 전환합니다...")
            # 전역 최적화 실패 시 LNS 시도
            with Timer("대규모 근린 탐색(LNS)으로 개선"):
                success = roster_system.optimize_with_lns(max_iterations=5, time_limit_per_iteration=20)
                if success:
                    print("LNS 개선이 성공적으로 완료되었습니다!")
                else:
                    print("LNS 개선이 완료되었으나 일부 제약조건 위반이 남아있습니다.")
    
    # 지표 계산 및 출력
    with Timer("상세 지표 계산"):
        try:
            detailed_metrics = roster_system.calculate_detailed_metrics()
            violations = detailed_metrics.get('constraint_violations', {})
            
            print("\n=== 제약조건 위반 현황 ===")
            if not violations:
                print("위반 사항이 없습니다! 완벽한 해결책을 찾았습니다.")
            else:
                for violation_type, count in violations.items():
                    print(f"{violation_type}: {count}건")
                
            if 'workload_distribution' in detailed_metrics and 'statistics' in detailed_metrics['workload_distribution']:
                workload = detailed_metrics['workload_distribution']['statistics']
                print(f"\n근무 부하 통계:")
                print(f"  간호사당 평균 근무 수: {workload.get('mean_shifts', 0):.2f}")
                print(f"  최소 근무 수: {workload.get('min_shifts', 0)}, 최대 근무 수: {workload.get('max_shifts', 0)}")
            
            if 'nurse_satisfaction' in detailed_metrics:
                satisfaction = detailed_metrics['nurse_satisfaction'].get('average', 0)
                print(f"\n평균 간호사 만족도 점수: {satisfaction:.2f}")
        except Exception as e:
            print(f"상세 지표 계산 중 오류 발생: {e}")
            # 기본 지표로 대체
            basic_metrics = roster_system.calculate_metrics()
            print("\n=== 기본 지표 ===")
            for key, value in basic_metrics.items():
                if not isinstance(value, dict):
                    print(f"{key}: {value}")
    
    # 최종 근무표 출력
    print("\n=== 최종 근무표 ===")
    roster_system.print_roster()
    
    # 지표와 함께 Excel로 내보내기
    with Timer("결과 내보내기"):
        export_roster_to_excel(roster_system, 'roster_eval/roster_v6.xlsx')
        print(f"결과가 roster_eval/roster_v6.xlsx 파일로 저장되었습니다.")
        
        # 상세 지표가 계산된 경우 별도 파일로 내보내기
        try:
            if 'detailed_metrics' in locals() and detailed_metrics:
                with open('detailed_metrics.json', 'w') as f:
                    import json
                    json.dump(detailed_metrics, f, indent=2, default=lambda x: float(x) if isinstance(x, np.float32) else x)
                print("상세 지표가 detailed_metrics.json 파일로 저장되었습니다.")
            else:
                # 기본 지표로 대체하여 저장
                basic_metrics = roster_system.calculate_metrics()
                with open('basic_metrics.json', 'w') as f:
                    import json
                    json.dump(basic_metrics, f, indent=2, default=lambda x: float(x) if isinstance(x, np.float32) else x)
                print("기본 지표가 basic_metrics.json 파일로 저장되었습니다.")
        except Exception as e:
            print(f"지표 내보내기 중 오류 발생: {e}")

if __name__ == "__main__":
    main() 