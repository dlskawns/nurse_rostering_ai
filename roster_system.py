from typing import List, Dict, Tuple, Optional
import numpy as np
from datetime import date, datetime, timedelta
import calendar
import time
from config import NurseRosterConfig, DEFAULT_CONFIG
from nurse import Nurse
import pandas as pd
import logging

class RosterSystem:
    """간호사 근무표 생성 및 관리를 위한 주요 클래스."""
    
    def __init__(
        self,
        nurses: List[Nurse],
        target_month: date,
        config: NurseRosterConfig = DEFAULT_CONFIG
    ):
        print("\nRosterSystem 초기화 중...")
        start_time = time.time()
        
        self.nurses = nurses
        self.target_month = target_month
        self.config = config
        self.num_days = calendar.monthrange(target_month.year, target_month.month)[1]
        
        # 근무표 행렬 초기화: [간호사 × 일수 × 교대]
        self.roster = np.zeros((len(nurses), self.num_days, config.num_shifts))
        self.preference_matrix = np.zeros_like(self.roster)
        
        # 선호도 행렬 초기화
        self._initialize_preferences()
        
        # 로깅 설정
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        print(f"초기화 완료: {time.time() - start_time:.4f}초 소요")
        
    def _initialize_preferences(self):
        """모든 간호사와 날짜에 대한 선호도 행렬을 초기화합니다."""
        print("선호도 행렬 계산 중...")
        start_time = time.time()
        
        for n_idx, nurse in enumerate(self.nurses):
            for day in range(self.num_days):
                self.preference_matrix[n_idx, day] = nurse.get_shift_preferences(
                    day, self.num_days, self.config
                )
                
        print(f"선호도 행렬 계산 완료: {time.time() - start_time:.4f}초 소요")
        
    def _check_night_constraints(self, nurse_idx: int, day: int) -> bool:
        """간호사에 대한 야간 근무 관련 제약 조건을 확인합니다."""
        if day < 2:  # 확인할 이력이 충분하지 않음
            return True
            
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        
        # 연속 야간 근무 확인
        if day >= self.config.max_consecutive_nights:
            consecutive_nights = np.all(
                self.roster[nurse_idx, day-self.config.max_consecutive_nights:day, night_idx] == 1
            )
            if consecutive_nights:
                return False
                
        # 야간 근무 후 주간 근무 확인
        if day > 0 and self.roster[nurse_idx, day-1, night_idx] == 1:
            if self.roster[nurse_idx, day, day_idx] == 1:
                return False
                
        # 월별 야간 근무 제한 확인
        total_nights = np.sum(self.roster[nurse_idx, :day+1, night_idx])
        if total_nights >= self.config.max_night_shifts_per_month:
            return False
            
        return True
        
    def _check_consecutive_work_days(self, nurse_idx: int, day: int) -> bool:
        """교대 추가가 연속 근무일 제약 조건을 위반하는지 확인합니다."""
        if day < self.config.max_consecutive_work_days:
            return True
            
        off_idx = self.config.shift_types.index('OFF')
        work_days = np.sum(
            self.roster[nurse_idx, day-self.config.max_consecutive_work_days:day, :off_idx], 
            axis=1
        )
        return not np.all(work_days > 0)
        
    def _check_experience_requirements(self, day: int) -> bool:
        """각 교대에 대한 경력 요구사항이 충족되는지 확인합니다."""
        experienced_nurses = [n for n in self.nurses if n.experience_years >= self.config.min_experience_per_shift]
        
        for shift in ['D', 'E', 'N']:
            shift_idx = self.config.shift_types.index(shift)
            exp_count = sum(
                1 for n_idx, nurse in enumerate(experienced_nurses)
                if self.roster[n_idx, day, shift_idx] == 1
            )
            if exp_count < self.config.required_experienced_nurses:
                return False
        return True
        
    def apply_off_requests(self, off_requests: Dict[int, List[int]]):
        """간호사의 휴무일 요청을 적용합니다.
        
        Args:
            off_requests: 간호사 ID를 요청된 휴무일 목록(1부터 시작)에 매핑하는 딕셔너리
        """
        for nurse_id, days in off_requests.items():
            nurse_idx = next(i for i, n in enumerate(self.nurses) if n.id == nurse_id)
            nurse = self.nurses[nurse_idx]
            
            # 월 내에 있는 날짜만 필터링
            valid_days = [d - 1 for d in days if 1 <= d <= self.num_days]  # 0부터 시작하는 인덱싱으로 변환
            
            if not valid_days:
                continue
            
            if not nurse.can_take_off(len(valid_days)):
                print(f"경고: {nurse.name} 간호사는 충분한 휴무일이 없습니다 "
                      f"(요청: {len(valid_days)}일, 가능: {nurse.remaining_off_days}일)")
                continue
            
            off_idx = self.config.shift_types.index('OFF')
            for day in valid_days:
                if np.any(self.roster[nurse_idx, day]):
                    # 기존 배정 제거
                    self.roster[nurse_idx, day] = 0
                self.roster[nurse_idx, day, off_idx] = 1
                
            nurse.update_off_days(len(valid_days))
            
    
        
    def _find_violations(self) -> List[dict]:
        """Find all constraint violations in current roster."""
        violations = []
        
        # Check each type of violation
        for day in range(self.num_days):
            # Check shift requirements
            for shift, required in self.config.daily_shift_requirements.items():
                shift_idx = self.config.shift_types.index(shift)
                actual = np.sum(self.roster[:, day, shift_idx])
                if actual != required:
                    violations.append({
                        'type': 'shift_requirement',
                        'day': day,
                        'shift': shift,
                        'required': required,
                        'actual': actual
                    })
                    
            # Check experience requirements
            if not self._check_experience_requirements(day):
                violations.append({
                    'type': 'experience',
                    'day': day
                })
                
        # Check nurse-specific constraints
        for n_idx, nurse in enumerate(self.nurses):
            for day in range(self.num_days):
                if not self._check_night_constraints(n_idx, day):
                    violations.append({
                        'type': 'night',
                        'nurse_idx': n_idx,
                        'day': day
                    })
                if not self._check_consecutive_work_days(n_idx, day):
                    violations.append({
                        'type': 'consecutive',
                        'nurse_idx': n_idx,
                        'day': day
                    })
                    
        return violations

    def get_roster_matrix(self) -> np.ndarray:
        """Return the current roster matrix."""
        return self.roster
        
    def print_roster(self):
        """Print current roster in readable format."""
        shift_map = {i: s for i, s in enumerate(self.config.shift_types)}
        
        print(f"\nRoster for {self.target_month.strftime('%B %Y')}:")
        print("=" * 50)
        print("Nurse".ljust(20), end="")
        for day in range(self.num_days):
            print(f"{day+1:2}", end=" ")
        print("\n" + "-" * 50)
        
        for n_idx, nurse in enumerate(self.nurses):
            print(f"{nurse.name[:19].ljust(20)}", end="")
            for day in range(self.num_days):
                shift_idx = np.where(self.roster[n_idx, day] == 1)[0]
                if len(shift_idx) == 0:
                    print(" - ", end="")
                else:
                    print(f" {shift_map[shift_idx[0]]} ", end="")
            print()

    def calculate_metrics(self) -> Dict:
        """Calculate roster metrics and statistics.
        
        Returns:
            Dict containing various roster metrics
        """
        metrics = {}
        
        # Shift distribution metrics
        shift_counts = {shift: 0 for shift in self.config.shift_types}
        nurse_shift_counts = {nurse.name: {shift: 0 for shift in self.config.shift_types} 
                             for nurse in self.nurses}
        
        unassigned_slots = 0
        staffing_violations = 0
        experience_violations = 0
        
        for day in range(self.num_days):
            # Check staffing requirements
            for shift in ['D', 'E', 'N']:
                shift_idx = self.config.shift_types.index(shift)
                assigned = np.sum(self.roster[:, day, shift_idx])
                required = self.config.daily_shift_requirements[shift]
                
                if assigned < required:
                    staffing_violations += 1
                    
            # Check experience requirements
            exp_violations = 0
            for shift in ['D', 'E', 'N']:
                shift_idx = self.config.shift_types.index(shift)
                exp_nurses = sum(
                    1 for n_idx, nurse in enumerate(self.nurses)
                    if (nurse.experience_years >= self.config.min_experience_per_shift and
                        self.roster[n_idx, day, shift_idx] == 1)
                )
                if exp_nurses < self.config.required_experienced_nurses:
                    exp_violations += 1
            experience_violations += exp_violations
            
            # Count shifts per nurse
            for n_idx, nurse in enumerate(self.nurses):
                assigned = False
                for shift in self.config.shift_types:
                    shift_idx = self.config.shift_types.index(shift)
                    if self.roster[n_idx, day, shift_idx] == 1:
                        shift_counts[shift] += 1
                        nurse_shift_counts[nurse.name][shift] += 1
                        assigned = True
                if not assigned:
                    unassigned_slots += 1
                    
        # Calculate weekend distribution
        weekend_shifts = {nurse.name: 0 for nurse in self.nurses}
        for day in range(self.num_days):
            if self._is_weekend(day):
                for n_idx, nurse in enumerate(self.nurses):
                    if np.any(self.roster[n_idx, day, :-1]):  # Exclude OFF shifts
                        weekend_shifts[nurse.name] += 1
                        
        # Calculate consecutive work days violations
        consecutive_violations = 0
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                if not self._check_consecutive_work_days(n_idx, day):
                    consecutive_violations += 1
                    
        # Calculate night shift violations
        night_violations = 0
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                if not self._check_night_constraints(n_idx, day):
                    night_violations += 1
                    
        # Compile metrics
        metrics['shift_distribution'] = shift_counts
        metrics['nurse_shift_counts'] = nurse_shift_counts
        metrics['unassigned_slots'] = unassigned_slots
        metrics['staffing_violations'] = staffing_violations
        metrics['experience_violations'] = experience_violations
        metrics['consecutive_violations'] = consecutive_violations
        metrics['night_violations'] = night_violations
        metrics['weekend_distribution'] = weekend_shifts
        
        return metrics

    def _is_weekend(self, day):
        """Check if given day is weekend."""
        return day % 7 >= 5

    def _initialize_roster(self):
        """Initialize roster with zeros."""
        self.roster = np.zeros((len(self.nurses), self.num_days, self.config.num_shifts))

    def _assign_shift(self, nurse_idx: int, day: int, shift: str):
        """Assign a shift to a nurse, clearing any existing assignments."""
        # Clear all shifts for this day first
        self.roster[nurse_idx, day] = 0
        # Then assign the new shift
        shift_idx = self.config.shift_types.index(shift)
        self.roster[nurse_idx, day, shift_idx] = 1 

    def calculate_detailed_metrics(self) -> Dict:
        """Calculate detailed metrics for roster evaluation."""
        metrics = {
            'constraint_violations': self._count_constraint_violations(),
            'workload_distribution': self._analyze_workload_distribution(),
            'shift_patterns': self._analyze_shift_patterns(),
            'nurse_satisfaction': self._estimate_nurse_satisfaction(),
            'coverage_metrics': self._analyze_coverage(),
            'fairness_metrics': self._analyze_fairness()
        }
        return metrics
        
    def _count_constraint_violations(self) -> Dict:
        """Count different types of constraint violations."""
        violations = self._find_violations()
        counts = {}
        for v in violations:
            v_type = v['type']
            counts[v_type] = counts.get(v_type, 0) + 1
        return counts
        
    def _analyze_workload_distribution(self) -> Dict:
        """Analyze the distribution of workload among nurses."""
        workloads = {}
        for n_idx, nurse in enumerate(self.nurses):
            shifts = {
                'total': np.sum(self.roster[n_idx, :, :-1]),  # Exclude OFF
                'day': np.sum(self.roster[n_idx, :, self.config.shift_types.index('D')]),
                'evening': np.sum(self.roster[n_idx, :, self.config.shift_types.index('E')]),
                'night': np.sum(self.roster[n_idx, :, self.config.shift_types.index('N')]),
                'off': np.sum(self.roster[n_idx, :, self.config.shift_types.index('OFF')])
            }
            workloads[nurse.name] = shifts
            
        return {
            'per_nurse': workloads,
            'statistics': {
                'mean_shifts': np.mean([w['total'] for w in workloads.values()]),
                'std_shifts': np.std([w['total'] for w in workloads.values()]),
                'min_shifts': min(w['total'] for w in workloads.values()),
                'max_shifts': max(w['total'] for w in workloads.values())
            }
        }
        
    def _analyze_shift_patterns(self) -> Dict:
        """Analyze patterns in shift assignments."""
        patterns = {
            'consecutive_shifts': self._analyze_consecutive_shifts(),
            'weekend_distribution': self._analyze_weekend_distribution(),
            'shift_transitions': self._analyze_shift_transitions()
        }
        return patterns
        
    def _analyze_consecutive_shifts(self) -> Dict:
        """Analyze consecutive shift patterns."""
        consecutive_counts = {
            'day': [],     # For 'D' shift
            'evening': [], # For 'E' shift
            'night': [],   # For 'N' shift
            'off': []      # For 'OFF' shift
        }
        
        # Map shift types to dictionary keys
        shift_map = {
            'D': 'day',
            'E': 'evening',
            'N': 'night',
            'OFF': 'off'
        }
        
        for n_idx in range(len(self.nurses)):
            for shift in self.config.shift_types:
                shift_idx = self.config.shift_types.index(shift)
                assignments = self.roster[n_idx, :, shift_idx]
                
                # Count consecutive assignments
                count = 0
                max_consecutive = 0
                for day in range(self.num_days):
                    if assignments[day]:
                        count += 1
                        max_consecutive = max(max_consecutive, count)
                    else:
                        count = 0
                
                # Use the mapping to get the correct key
                key = shift_map.get(shift, 'other')
                consecutive_counts[key].append(max_consecutive)
                
        return {
            shift: {
                'max': max(counts) if counts else 0,
                'avg': np.mean(counts) if counts else 0,
                'std': np.std(counts) if counts else 0
            }
            for shift, counts in consecutive_counts.items()
        }
        
    def _analyze_weekend_distribution(self) -> Dict:
        """Analyze the distribution of weekend shifts."""
        weekend_stats = {
            'per_nurse': {},
            'overall': {'total_weekends': 0, 'nurses_per_weekend': []}
        }
        
        try:
            for n_idx, nurse in enumerate(self.nurses):
                weekend_count = 0
                for day in range(self.num_days):
                    if self._is_weekend(day) and np.any(self.roster[n_idx, day, :-1]):
                        weekend_count += 1
                weekend_stats['per_nurse'][nurse.name] = weekend_count
                
            # Calculate nurses per weekend
            for day in range(self.num_days):
                if self._is_weekend(day):
                    weekend_stats['overall']['total_weekends'] += 1
                    nurses_working = sum(
                        1 for n_idx in range(len(self.nurses))
                        if np.any(self.roster[n_idx, day, :-1])
                    )
                    weekend_stats['overall']['nurses_per_weekend'].append(nurses_working)
        except Exception as e:
            print(f"Warning: Error calculating weekend distribution: {e}")
            # Return empty stats if there's an error
            return {
                'per_nurse': {},
                'overall': {'total_weekends': 0, 'nurses_per_weekend': []}
            }
                
        return weekend_stats
        
    def _analyze_shift_transitions(self) -> Dict:
        """Analyze transitions between different shifts."""
        transitions = {
            f"{s1}->{s2}": 0
            for s1 in self.config.shift_types
            for s2 in self.config.shift_types
        }
        
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - 1):
                try:
                    # Find which shift is assigned for current day
                    current_shifts = np.where(self.roster[n_idx, day] == 1)[0]
                    next_shifts = np.where(self.roster[n_idx, day + 1] == 1)[0]
                    
                    if len(current_shifts) > 0 and len(next_shifts) > 0:
                        current = current_shifts[0]
                        next_day = next_shifts[0]
                        
                        transition = f"{self.config.shift_types[current]}->{self.config.shift_types[next_day]}"
                        transitions[transition] += 1
                except IndexError:
                    # Skip if there's any missing assignment
                    continue
                    
        return transitions
        
    def _estimate_nurse_satisfaction(self) -> Dict:
        """Estimate nurse satisfaction based on preferences and assignments."""
        satisfaction = {}
        
        for n_idx, nurse in enumerate(self.nurses):
            matches = 0
            total = 0
            
            for day in range(self.num_days):
                assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                pref_score = self.preference_matrix[n_idx, day, assigned_shift]
                matches += pref_score
                total += 1
                
            satisfaction[nurse.name] = {
                'score': matches / total if total > 0 else 0,
                'preferred_shifts_ratio': matches / total if total > 0 else 0
            }
            
        return {
            'per_nurse': satisfaction,
            'average': np.mean([s['score'] for s in satisfaction.values()])
        }
        
    def _analyze_coverage(self) -> Dict:
        """Analyze shift coverage and staffing levels."""
        coverage = {
            'daily': {},
            'overall': {}
        }
        
        for day in range(self.num_days):
            coverage['daily'][day] = {}
            for shift in self.config.shift_types[:-1]:  # Exclude OFF
                shift_idx = self.config.shift_types.index(shift)
                required = self.config.daily_shift_requirements[shift]
                actual = np.sum(self.roster[:, day, shift_idx])
                coverage['daily'][day][shift] = {
                    'required': required,
                    'actual': actual,
                    'difference': actual - required
                }
                
        # Calculate overall statistics
        for shift in self.config.shift_types[:-1]:
            shift_idx = self.config.shift_types.index(shift)
            required_total = self.config.daily_shift_requirements[shift] * self.num_days
            actual_total = np.sum(self.roster[:, :, shift_idx])
            coverage['overall'][shift] = {
                'required_total': required_total,
                'actual_total': actual_total,
                'coverage_ratio': actual_total / required_total if required_total > 0 else 1.0
            }
            
        return coverage
        
    def _analyze_fairness(self) -> Dict:
        """Analyze fairness in shift distribution."""
        fairness = {
            'shift_distribution': {},
            'weekend_fairness': {},
            'workload_balance': {}
        }
        
        # Analyze shift type distribution
        for shift in self.config.shift_types[:-1]:
            shift_idx = self.config.shift_types.index(shift)
            assignments = [
                np.sum(self.roster[n_idx, :, shift_idx])
                for n_idx in range(len(self.nurses))
            ]
            fairness['shift_distribution'][shift] = {
                'gini_coefficient': self._calculate_gini(assignments),
                'coefficient_of_variation': np.std(assignments) / np.mean(assignments) if np.mean(assignments) > 0 else 0
            }
            
        return fairness
        
    def _calculate_gini(self, array: List[float]) -> float:
        """Calculate Gini coefficient as a measure of inequality."""
        array = np.array(array)
        if np.all(array == 0):
            return 0
        array = array.flatten()
        if np.amin(array) < 0:
            array -= np.amin(array)
        array += 0.0000001
        array = np.sort(array)
        index = np.arange(1, array.shape[0] + 1)
        n = array.shape[0]
        return ((np.sum((2 * index - n - 1) * array)) / (n * np.sum(array)))

    def optimize_roster_with_cp_sat(self, time_limit_seconds=30):
        """Optimize the roster using CP-SAT global constraint solver.
        
        This approach models all constraints simultaneously and finds a globally optimal solution.
        """
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("Error: OR-Tools is not installed. Please install it with: pip install ortools")
            return False
            
        print("\nStarting global optimization with CP-SAT solver...")
        start_time = time.time()
        
        # Create the model
        model = cp_model.CpModel()
        
        # 1. Define variables
        # x[nurse, day, shift] = 1 if nurse is assigned to shift on day
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{shift}')
        
        # Generate a solution hint from current roster
        # Note: Instead of using SetHint which might not be available in all versions,
        # we'll use the hint parameter when creating variables
        solution_hint = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                try:
                    assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                    for s_idx in range(len(self.config.shift_types)):
                        if s_idx == assigned_shift:
                            model.AddHint(x[n_idx, day, s_idx], 1)
                        else:
                            model.AddHint(x[n_idx, day, s_idx], 0)
                except:
                    # If no assignment is found, skip hint
                    pass

        # 2. Add exactly-one constraint: each nurse must be assigned exactly one shift per day
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(len(self.config.shift_types)))
        
        # 3. Add staffing requirements
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                # Sum of nurses assigned to this shift must equal required number
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses))) == required)
        
        # 4. Add experience requirements
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                # Sum of experienced nurses assigned to this shift
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                # Must have at least the required number of experienced nurses
                model.Add(exp_nurses_assigned >= self.config.required_experienced_nurses)
        
        # 5. Night nurse constraints - night nurses CANNOT work day shifts (HARD constraint)
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    # Force day shift assignment to be 0 for night nurses
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 6. Add consecutive work days constraint
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_work_days + 1):
                # If nurse works max_consecutive_work_days days in a row, must have a day off
                consecutive_work = []
                for d in range(day, day + self.config.max_consecutive_work_days):
                    # Working = any shift except OFF
                    off_idx = self.config.shift_types.index('OFF') 
                    work_vars = [x[n_idx, d, s_idx] for s_idx in range(len(self.config.shift_types)) if s_idx != off_idx]
                    is_working = model.NewBoolVar(f'n{n_idx}_d{d}_working')
                    model.AddMaxEquality(is_working, work_vars)
                    consecutive_work.append(is_working)
                
                # Can't have all consecutive_work days be true
                model.Add(sum(consecutive_work) < len(consecutive_work))
        
        # 7. Add night shift constraints
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        
        # 7.1 Max consecutive nights
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_nights):
                # Can't have more than max_consecutive_nights in a row
                consecutive_nights = [x[n_idx, d, night_idx] for d in range(day, day + self.config.max_consecutive_nights + 1)]
                model.Add(sum(consecutive_nights) <= self.config.max_consecutive_nights)
        
        # 7.2 No day shift after night shift
        for n_idx in range(len(self.nurses)):
            for day in range(1, self.num_days):
                # If worked night shift yesterday, can't work day shift today
                model.Add(x[n_idx, day, day_idx] <= 1 - x[n_idx, day-1, night_idx])
        
        # 7.3 Monthly night shift limit
        for n_idx in range(len(self.nurses)):
            total_nights = sum(x[n_idx, day, night_idx] for day in range(self.num_days))
            model.Add(total_nights <= self.config.max_night_shifts_per_month)
        
        # 8. Head nurse weekend pattern
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_head_nurse:
                off_idx = self.config.shift_types.index('OFF')
                
                if nurse.head_nurse_off_pattern == 'weekend':
                    # Weekend days must be OFF
                    for day in range(self.num_days):
                        if self._is_weekend(day):
                            model.Add(x[n_idx, day, off_idx] == 1)
                            
                elif nurse.head_nurse_off_pattern == 'mixed':
                    # Every other weekend must be OFF
                    for day in range(self.num_days):
                        if self._is_weekend(day) and day % 14 >= 7:
                            model.Add(x[n_idx, day, off_idx] == 1)
        
        # 9. Handle resignation dates
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.resignation_date:
                resignation_day = (nurse.resignation_date - self.target_month).days
                if 0 <= resignation_day < self.num_days:
                    off_idx = self.config.shift_types.index('OFF')
                    for day in range(resignation_day, self.num_days):
                        model.Add(x[n_idx, day, off_idx] == 1)
        
        # 10. Objective function: maximize preference satisfaction
        objective_terms = []
        
        # 10.1 Preference satisfaction
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    # Scale preference to integer (CP-SAT needs integer coefficients)
                    pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 100)
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 10.2 Night nurse specialization bonus
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                # Bonus for night nurses working night shifts
                night_bonus = sum(200 * x[n_idx, day, night_idx] for day in range(self.num_days))
                objective_terms.append(night_bonus)
        
        # 10.3 Workload balance penalty - Simplified to avoid non-affine expressions
        # Calculate total work days for each nurse directly
        off_idx = self.config.shift_types.index('OFF')
        
        # Create workday count variables for each nurse
        work_days = {}
        for n_idx in range(len(self.nurses)):
            # Count non-OFF shifts for each nurse
            work_shifts = [
                x[n_idx, day, s_idx] 
                for day in range(self.num_days) 
                for s_idx in range(len(self.config.shift_types)) 
                if s_idx != off_idx
            ]
            work_days[n_idx] = model.NewIntVar(0, self.num_days, f'work_days_n{n_idx}')
            model.Add(work_days[n_idx] == sum(work_shifts))
        
        # Add fairness constraints - target at least min_work_days per nurse
        min_work_days = (self.num_days * sum(self.config.daily_shift_requirements.values())) // (len(self.nurses) * 2)
        for n_idx in range(len(self.nurses)):
            # Encourage at least minimum workdays
            objective_terms.append(50 * work_days[n_idx])
            # But penalize excessive workdays
            excess_var = model.NewIntVar(0, self.num_days, f'excess_n{n_idx}')
            model.Add(excess_var >= work_days[n_idx] - (self.num_days - min_work_days))
            objective_terms.append(-100 * excess_var)  # Penalize excess
        
        # 11. 휴무일 제한 추가
        off_idx = self.config.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            total_off = sum(x[n_idx, day, off_idx] for day in range(self.num_days))
            allowed_off = nurse.remaining_off_days
            model.Add(total_off <= allowed_off)


        
        # Set the objective
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        
        # Solve the model
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract the solution
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Clear current assignments
                    self.roster[n_idx, day] = 0
                    # Set new assignment
                    for s_idx in range(len(self.config.shift_types)):
                        if solver.Value(x[n_idx, day, s_idx]) == 1:
                            self.roster[n_idx, day, s_idx] = 1
                            break
            
            print(f"Optimization completed in {time.time() - start_time:.2f} seconds")
            print(f"Objective value: {solver.ObjectiveValue()}")
            
            if status == cp_model.OPTIMAL:
                print("Found optimal solution!")
            else:
                print("Found feasible solution (may not be optimal)")
                
            return True
        else:
            print("No solution found.")
            return False
        
    def optimize_with_lns(self, max_iterations=10, time_limit_per_iteration=10):
        """Optimize roster using Large Neighborhood Search.
        
        This approach keeps part of the roster fixed and re-optimizes
        a selected part using CP-SAT, gradually improving the solution.
        """
        print("\nStarting optimization with Large Neighborhood Search...")
        start_time = time.time()
        
        best_roster = self.roster.copy()
        best_violations = len(self._find_violations())
        
        for iteration in range(max_iterations):
            print(f"\nLNS Iteration {iteration+1}/{max_iterations}")
            
            # Keep a copy of the current roster
            current_roster = self.roster.copy()
            
            # Randomly select a subset of days and nurses to re-optimize
            days_to_optimize = np.random.choice(range(self.num_days), 
                                              size=min(7, self.num_days), 
                                              replace=False)
            nurses_to_optimize = np.random.choice(range(len(self.nurses)), 
                                               size=min(5, len(self.nurses)), 
                                               replace=False)
            
            print(f"Re-optimizing days {sorted(days_to_optimize)} for {len(nurses_to_optimize)} nurses...")
            
            # Fix assignments for non-selected days and nurses
            fixed_assignments = []
            for n_idx in range(len(self.nurses)):
                if n_idx not in nurses_to_optimize:
                    for day in range(self.num_days):
                        shift_idx = np.where(self.roster[n_idx, day] == 1)[0][0]
                        fixed_assignments.append((n_idx, day, shift_idx))
                else:
                    for day in range(self.num_days):
                        if day not in days_to_optimize:
                            shift_idx = np.where(self.roster[n_idx, day] == 1)[0][0]
                            fixed_assignments.append((n_idx, day, shift_idx))
            
            # Run CP-SAT on this neighborhood
            success = self._optimize_neighborhood(fixed_assignments, time_limit_per_iteration)
            
            if success:
                # Count violations after optimization
                new_violations = len(self._find_violations())
                print(f"Violations: {best_violations} -> {new_violations}")
                
                if new_violations < best_violations:
                    best_violations = new_violations
                    best_roster = self.roster.copy()
                    print("Solution improved!")
                else:
                    # Rollback if no improvement
                    self.roster = current_roster
                    print("No improvement, rolling back changes")
            else:
                # Rollback if optimization failed
                self.roster = current_roster
                print("Optimization failed, rolling back changes")
        
        # Always use the best roster found
        self.roster = best_roster
        
        print(f"LNS completed in {time.time() - start_time:.2f} seconds")
        print(f"Final violations: {best_violations}")
        return best_violations == 0
        
    def _optimize_neighborhood(self, fixed_assignments, time_limit_seconds):
        """Optimize a neighborhood of the roster with some assignments fixed."""
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("Error: OR-Tools is not installed")
            return False
            
        # Create the model
        model = cp_model.CpModel()
        
        # Define variables
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{shift}')
        
        # Fix the specified assignments
        for n_idx, day, s_idx in fixed_assignments:
            model.Add(x[n_idx, day, s_idx] == 1)
        
        # Generate hints from current roster for non-fixed assignments
        try:
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Skip if this is a fixed assignment
                    is_fixed = any((n_idx, day, _) in fixed_assignments for _ in range(len(self.config.shift_types)))
                    if not is_fixed:
                        assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                        for s_idx in range(len(self.config.shift_types)):
                            if s_idx == assigned_shift:
                                model.AddHint(x[n_idx, day, s_idx], 1)
                            else:
                                model.AddHint(x[n_idx, day, s_idx], 0)
        except:
            # If there's any error with hints, just proceed without them
            pass
            
        # Add constraints
        
        # 1. Add exactly-one constraint
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(len(self.config.shift_types)))
        
        # 2. Add staffing requirements
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses))) == required)
        
        # 3. Add experience requirements
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                # Sum of experienced nurses assigned to this shift
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                model.Add(exp_nurses_assigned >= self.config.required_experienced_nurses)
                
        # 4. Night nurse constraints - CANNOT work day shifts
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 5. Add other necessary constraints (simplified)
        
        # Set the objective (simplified from the full version)
        objective_terms = []
        
        # Preference satisfaction
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx in range(len(self.config.shift_types)):
                    pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 100)
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # Night nurse specialization bonus
        night_idx = self.config.shift_types.index('N')
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                night_bonus = sum(200 * x[n_idx, day, night_idx] for day in range(self.num_days))
                objective_terms.append(night_bonus)
        
        # Workload balance (simplified)
        off_idx = self.config.shift_types.index('OFF')
        for n_idx in range(len(self.nurses)):
            # Encourage working
            work_shifts = [
                x[n_idx, day, s_idx] 
                for day in range(self.num_days) 
                for s_idx in range(len(self.config.shift_types)) 
                if s_idx != off_idx
            ]
            objective_terms.append(25 * sum(work_shifts))
        
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        
        # Solve the model
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract the solution
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Clear current assignments
                    self.roster[n_idx, day] = 0
                    # Set new assignment
                    for s_idx in range(len(self.config.shift_types)):
                        if solver.Value(x[n_idx, day, s_idx]) == 1:
                            self.roster[n_idx, day, s_idx] = 1
                            break
            return True
        else:
            return False 

    def generate_roster(self, num_days: int) -> np.ndarray:
        """근무표를 생성합니다.
        
        Args:
            num_days: 근무표를 생성할 일수
            
        Returns:
            생성된 근무표 (numpy array)
        """
        start_time = time.time()
        self.logger.info(f"근무표 생성 시작: {len(self.nurses)}명의 간호사, {num_days}일")
        
        # 근무표 초기화
        self.roster = np.full((len(self.nurses), num_days), 'OFF', dtype='U3')
        
        # 각 날짜에 대해 근무 배정
        for day in range(num_days):
            self._assign_shifts_for_day(day)
            
            # 진행 상황 로깅
            if (day + 1) % 7 == 0:
                self.logger.info(f"{day + 1}일 완료 ({((day + 1) / num_days * 100):.1f}%)")
                
        # 만족도 지표 계산
        self._calculate_satisfaction_metrics()
        
        end_time = time.time()
        self.logger.info(f"근무표 생성 완료. 소요 시간: {end_time - start_time:.2f}초")
        
        return self.roster
        
    def _assign_shifts_for_day(self, day: int):
        """특정 날짜의 근무를 배정합니다.
        
        Args:
            day: 근무를 배정할 날짜 인덱스
        """
        # 각 교대 유형별로 필요한 인원 수만큼 배정
        for shift_type, required_nurses in self.config.daily_shift_requirements.items():
            assigned_count = 0
            
            # 선호도에 따라 간호사 정렬
            nurse_preferences = []
            for idx, nurse in enumerate(self.nurses):
                if self.roster[idx, day] == 'OFF':  # 아직 배정되지 않은 간호사만 고려
                    preference = nurse.get_shift_preference(shift_type, self.config)
                    nurse_preferences.append((preference, idx))
            
            # 선호도 순으로 정렬
            nurse_preferences.sort(reverse=True)
            
            # 필요한 인원만큼 배정
            for _, nurse_idx in nurse_preferences:
                if assigned_count >= required_nurses:
                    break
                    
                nurse = self.nurses[nurse_idx]
                self.roster[nurse_idx, day] = shift_type
                nurse.update_shift_history(shift_type, day)
                assigned_count += 1
                
            if assigned_count < required_nurses:
                self.logger.warning(f"일자 {day + 1}: {shift_type} 교대에 필요한 인원을 배정하지 못했습니다 ({assigned_count}/{required_nurses})")
                
    def _calculate_satisfaction_metrics(self):
        """근무표에 대한 만족도 지표를 계산합니다."""
        metrics = {
            '총 야간 근무 수': [],
            '연속 야간 근무 발생 횟수': [],
            '연속 근무일 수 초과 횟수': [],
            '주당 휴무일 부족 횟수': []
        }
        
        for nurse_idx, nurse in enumerate(self.nurses):
            night_shifts = np.sum(self.roster[nurse_idx] == 'N')
            metrics['총 야간 근무 수'].append(night_shifts)
            
            # 연속 야간 근무 체크
            consecutive_nights = 0
            consecutive_nights_violations = 0
            for shift in self.roster[nurse_idx]:
                if shift == 'N':
                    consecutive_nights += 1
                    if consecutive_nights > self.config.max_consecutive_nights:
                        consecutive_nights_violations += 1
                else:
                    consecutive_nights = 0
            metrics['연속 야간 근무 발생 횟수'].append(consecutive_nights_violations)
            
            # 연속 근무일 체크
            consecutive_work = 0
            consecutive_work_violations = 0
            for shift in self.roster[nurse_idx]:
                if shift != 'OFF':
                    consecutive_work += 1
                    if consecutive_work > self.config.max_consecutive_work_days:
                        consecutive_work_violations += 1
                else:
                    consecutive_work = 0
            metrics['연속 근무일 수 초과 횟수'].append(consecutive_work_violations)
            
            # 주당 휴무일 체크
            weekly_off_violations = 0
            for week in range(len(self.roster[nurse_idx]) // 7):
                week_shifts = self.roster[nurse_idx][week * 7:(week + 1) * 7]
                off_days = np.sum(week_shifts == 'OFF')
                if off_days < 2:  # 주 2일 휴무 기준
                    weekly_off_violations += 1
            metrics['주당 휴무일 부족 횟수'].append(weekly_off_violations)
            
        self.satisfaction_metrics = metrics
        
    def export_to_excel(self, filename: str):
        """근무표를 Excel 파일로 내보냅니다.
        
        Args:
            filename: 저장할 Excel 파일 이름
        """
        if self.roster is None:
            raise ValueError("근무표가 아직 생성되지 않았습니다.")
            
        # 근무표 데이터프레임 생성
        df = pd.DataFrame(
            self.roster,
            index=[f"{nurse.name} ({nurse.experience_years}년차)" for nurse in self.nurses],
            columns=[f"Day {i+1}" for i in range(self.roster.shape[1])]
        )
        
        # 만족도 지표 데이터프레임 생성
        metrics_df = pd.DataFrame(self.satisfaction_metrics)
        metrics_df.index = [nurse.name for nurse in self.nurses]
        
        # Excel 파일로 저장
        with pd.ExcelWriter(filename) as writer:
            df.to_excel(writer, sheet_name='근무표')
            metrics_df.to_excel(writer, sheet_name='만족도 지표')
            
        self.logger.info(f"근무표가 {filename}에 저장되었습니다.") 