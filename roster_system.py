from typing import List, Dict, Tuple, Optional, Union
import numpy as np
from datetime import date, datetime, timedelta
import calendar
import time
import pandas as pd
import logging
from config import NurseRosterConfig, DEFAULT_CONFIG
from nurse import Nurse

class RosterSystem:
    """간호사 근무표 생성 및 관리를 위한 주요 클래스."""
    
    def __init__(
        self,
        nurses: List[Nurse],
        target_month: date,
        config: NurseRosterConfig = DEFAULT_CONFIG,
        preference_matrix: Optional[np.ndarray] = None
    ):
        print("\nRosterSystem 초기화 중...")
        start_time = time.time()
        
        self.nurses = nurses
        self.target_month = target_month
        self.config = config
        self.num_days = calendar.monthrange(target_month.year, target_month.month)[1]
        
        # 근무표 행렬 초기화: [간호사 × 일수 × 교대]
        self.roster = np.zeros((len(nurses), self.num_days, config.num_shifts))
        
        # 선호도 행렬 설정
        if preference_matrix is not None:
            self.preference_matrix = preference_matrix
            print("외부 제공 선호도 행렬 사용.")
        else:
            self.preference_matrix = np.zeros_like(self.roster)
            # 선호도 행렬 초기화
            self._initialize_preferences()

        #### 수정된곳
        self.max_off_per_nurse = []
        for nurse in self.nurses:
            # 글로벌 + 기본 개인 + 개인 조정치(음/양수) = 총 허용 OFF
            max_allowed = (
                self.config.global_monthly_off_days
                + self.config.standard_personal_off_days
                + nurse.personal_off_adjustment
            )
            # 음수라도 0 이하로 떨어지지 않도록 보정
            self.max_off_per_nurse.append(max(0, max_allowed))
        ####
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
        """
        간호사의 휴무(OFF) 요청을 날짜·강도(Δ-weight) 단위로 적용합니다.

        Args
        ----
        off_requests : {
            "간호사ID(문자열)": { "날짜(문자열)": delta_weight, ... }, ...
        }
        - 날짜는 1-based(예: "6" → 6일).
        - delta_weight 는 기본 OFF-가중치(config.shift_preference_weights["OFF"])
            에 더해질 추가점수.   (총점 = 기본 + delta)
        """
        off_idx     = self.config.shift_types.index("OFF")
        base_weight = self.config.shift_preference_weights.get("OFF", 10.0)
        print('\n\n\n\n\noff_requests', off_requests, '\n\n\n\n\n')
        for target_nurse_id, day_map in off_requests.items():
            if target_nurse_id is None:
                print(f"[OFF] 경고: ID {target_nurse_id} 간호사 없음");  continue

            valid_days = []
            for day_str, delta in day_map.items():
                d = int(day_str)
                if 1 <= d <= self.num_days:
                    valid_days.append(d)
            
            if not valid_days:
                continue
            nurse = next((n for n in self.nurses if n.db_id == target_nurse_id), None)

            # if not nurse.can_take_off(len(valid_days)):
            #     print(f"[OFF] 경고: {nurse.name} – 잔여 휴무 부족 "
            #         f"(요청 {len(valid_days)}, 가능 {nurse.remaining_off_days})")
            #     continue

            # ★ 가중치 반영
            for d in valid_days:
                day_idx = d-1
                delta   = day_map[str(d)]
                self.preference_matrix[nurse.id, day_idx, off_idx] = base_weight + delta
        
        # nurse.update_off_days(len(valid_days))
            
    def apply_shift_preferences(self, shift_preferences: Dict[str, Dict[str, Dict[str, float]]]):
        """
        간호사의 특정 근무 유형(D, E, N)에 대한 날짜별 선호도를 반영합니다.

        shift_preferences 예시:
        {
            "1": {
                "D": {"4": 1.0, "5": 3.2},
                "E": {"10": 1.0, "11": 1.5}
            }
        }
        """
        print("근무 유형 선호도 적용 중...")
        for target_nurse_id, shifts in shift_preferences.items():
            
            if target_nurse_id is None:
                print(f"경고: ID {target_nurse_id}인 간호사를 찾을 수 없습니다.")
                continue
            
            for shift_type, day_weight_map in shifts.items():
                if shift_type not in self.config.shift_types:
                    print(f"경고: 유효하지 않은 근무 유형: {shift_type}")
                    continue
                
                shift_idx = self.config.shift_types.index(shift_type)
                default_weight = self.config.shift_preference_weights.get(shift_type, 5.0)
                nurse = next((n for n in self.nurses if n.db_id == target_nurse_id), None)
                for day_str, delta in day_weight_map.items():
                    day = int(day_str)
                    if 1 <= day <= self.num_days:
                        day_idx = day - 1
                        self.preference_matrix[nurse.id, day_idx, shift_idx] = default_weight + delta
                        
        print("근무 유형 선호도 적용 완료")
        
    def apply_pair_preferences(self, pair_preferences: Dict[str, List[Dict[str, Union[int, float]]]]):
        """간호사 간의 페어링 선호도를 적용합니다.
        
        Args:
            pair_preferences: 함께 또는 따로 일하고 싶은 간호사 쌍의 정보
                예: {
                    "work_together": [{"nurse_1": 1, "nurse_2": 5, "weight": 3.0}, ...],
                    "work_apart": [{"nurse_1": 1, "nurse_2": 6, "weight": 3.0}, ...]
                }
        """
        print("간호사 페어링 선호도 초기화 중...")
        
        # 간호사 페어링 선호도 매트릭스 초기화 (간호사 × 간호사)
        self.pair_matrix = {
            "together": np.zeros((len(self.nurses), len(self.nurses))),
            "apart": np.zeros((len(self.nurses), len(self.nurses)))
        }
        
        # together (함께 일하기 원하는 쌍) 처리
        if "work_together" in pair_preferences:
            for pair in pair_preferences["work_together"]:
                nurse_1_id = pair["nurse_1"]
                nurse_2_id = pair["nurse_2"]
                weight = pair.get("weight", self.config.pair_preference_weight)
                nurse_1_idx = next((n.id for n in self.nurses if n.db_id == nurse_1_id), None)
                nurse_2_idx = next((n.id for n in self.nurses if n.db_id == nurse_2_id), None)
                # nurse_1_idx = next((i for i, n in enumerate(self.nurses) if n.id == nurse_1_id), None)
                # nurse_2_idx = next((i for i, n in enumerate(self.nurses) if n.id == nurse_2_id), None)
                
                if nurse_1_idx is not None and nurse_2_idx is not None:
                    self.pair_matrix["together"][nurse_1_idx, nurse_2_idx] = weight
                    self.pair_matrix["together"][nurse_2_idx, nurse_1_idx] = weight  # 대칭적으로 설정
                else:
                    if nurse_1_idx is None:
                        print(f"경고: ID {nurse_1_id}인 간호사를 찾을 수 없습니다.")
                    if nurse_2_idx is None:
                        print(f"경고: ID {nurse_2_id}인 간호사를 찾을 수 없습니다.")
        
        # apart (따로 일하기 원하는 쌍) 처리
        if "work_apart" in pair_preferences:
            for pair in pair_preferences["work_apart"]:
                nurse_1_id = pair["nurse_1"]
                nurse_2_id = pair["nurse_2"]
                weight = pair.get("weight", self.config.pair_preference_weight)
                nurse_1_idx = next((n.id for n in self.nurses if n.db_id == nurse_1_id), None)
                nurse_2_idx = next((n.id for n in self.nurses if n.db_id == nurse_2_id), None)
                # nurse_1_idx = next((i for i, n in enumerate(self.nurses) if n.id == nurse_1_id), None)
                # nurse_2_idx = next((i for i, n in enumerate(self.nurses) if n.id == nurse_2_id), None)
                
                if nurse_1_idx is not None and nurse_2_idx is not None:
                    self.pair_matrix["apart"][nurse_1_idx, nurse_2_idx] = weight
                    self.pair_matrix["apart"][nurse_2_idx, nurse_1_idx] = weight  # 대칭적으로 설정
                else:
                    if nurse_1_idx is None:
                        print(f"경고: ID {nurse_1_id}인 간호사를 찾을 수 없습니다.")
                    if nurse_2_idx is None:
                        print(f"경고: ID {nurse_2_id}인 간호사를 찾을 수 없습니다.")
                        
        print("간호사 페어링 선호도 초기화 완료")
        
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


    def optimize_roster_with_cp_sat(self, time_limit_seconds=30):
        """CP-SAT를 사용하여 근무표를 최적화합니다. 모든 제약 조건을 Hard Constraint로 적용합니다."""
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("Error: OR-Tools is not installed. Please install it with: pip install ortools")
            return False
            
        print("\nCP-SAT solver로 전역 최적화 시작 (Hard Constraints Mode)...")
        start_time = time.time()
        
        model = cp_model.CpModel()
        
        # --- 변수 정의 ---
        # x[nurse, day, shift] = 1 if nurse is assigned to shift on day
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx in range(self.config.num_shifts):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{s_idx}')

        # --- Hard Constraints ---

        # 1. 한 간호사는 하루에 정확히 하나의 근무만 배정받습니다.
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(self.config.num_shifts))

        # 2. 일일 교대별 필수 인원을 충족해야 합니다.
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses))) == required)

        # 3. 수간호사 요구사항 (주말 휴무 등)은 반드시 지켜져야 합니다.
        off_idx = self.config.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_head_nurse and nurse.head_nurse_off_pattern == 'weekend':
                for day in range(self.num_days):
                    if self._is_weekend(day):
                        model.Add(x[n_idx, day, off_idx] == 1)

        # 4. 최대 연속 근무일은 6일을 넘을 수 없습니다. (7일 연속 근무 금지)
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_work_days):
                # 7일 동안의 근무 수를 계산합니다 (OFF가 아닌 근무).
                work_days_in_window = []
                for d in range(day, day + self.config.max_consecutive_work_days + 1):
                    work_day = model.NewBoolVar(f'work_n{n_idx}_d{d}')
                    model.Add(work_day == 1 - x[n_idx, d, off_idx])
                    work_days_in_window.append(work_day)
                # 7일 동안의 근무일 수가 6일을 초과할 수 없습니다.
                model.Add(sum(work_days_in_window) <= self.config.max_consecutive_work_days)

        # 5. 7일 중 2회 휴무가 보장되어야 합니다.
        if self.config.enforce_two_offs_per_week:
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days - 6):
                    model.Add(sum(x[n_idx, d, off_idx] for d in range(day, day + 7)) >= 2)

        # 6. 야간 근무(N) 관련 제약 조건
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        evening_idx = self.config.shift_types.index('E')

        for n_idx in range(len(self.nurses)):
            # 6.1. 월간 야간 근무는 15회를 넘을 수 없습니다.
            model.Add(sum(x[n_idx, day, night_idx] for day in range(self.num_days)) <= self.config.max_night_shifts_per_month)

            # 6.2. N 근무는 3개 연달아 나올 수 없습니다 (최대 2연속).
            for day in range(self.num_days - self.config.max_consecutive_nights):
                model.Add(sum(x[n_idx, d, night_idx] for d in range(day, day + self.config.max_consecutive_nights + 1)) <= self.config.max_consecutive_nights)

            # 6.3. N 근무 다음 날 D 근무는 불가합니다.
            for day in range(1, self.num_days):
                model.AddBoolOr([x[n_idx, day-1, night_idx].Not(), x[n_idx, day, day_idx].Not()])

            # 6.4. E 근무 다음 날 D 근무는 불가합니다 (설정에 따라).
            if self.config.enforce_E_after_D_constraint:
                 for day in range(1, self.num_days):
                    model.AddBoolOr([x[n_idx, day-1, evening_idx].Not(), x[n_idx, day, day_idx].Not()])

        # 7. 시니어-주니어 페어링 제약 조건
        if self.config.enforce_seniority_pairing:
            juniors = [i for i, n in enumerate(self.nurses) if n.experience_years <= self.config.junior_pairing_max_experience]
            seniors = [i for i, n in enumerate(self.nurses) if n.experience_years >= self.config.senior_pairing_min_experience]
            
            for day in range(self.num_days):
                for s_idx in range(self.config.num_shifts):
                    # 해당 교대에 근무하는 주니어 수
                    num_juniors = sum(x[j, day, s_idx] for j in juniors)
                    # 해당 교대에 근무하는 시니어 수
                    num_seniors = sum(x[s, day, s_idx] for s in seniors)

                    # 주니어가 한 명이라도 있으면, 시니어도 반드시 한 명 이상 있어야 합니다.
                    # (num_juniors > 0) => (num_seniors > 0)
                    # 이를 위해 (num_juniors == 0) or (num_seniors > 0) 형태로 변환
                    
                    has_juniors = model.NewBoolVar(f'has_juniors_d{day}_s{s_idx}')
                    model.Add(num_juniors > 0).OnlyEnforceIf(has_juniors)
                    model.Add(num_juniors == 0).OnlyEnforceIf(has_juniors.Not())

                    has_seniors = model.NewBoolVar(f'has_seniors_d{day}_s{s_idx}')
                    model.Add(num_seniors > 0).OnlyEnforceIf(has_seniors)
                    model.Add(num_seniors == 0).OnlyEnforceIf(has_seniors.Not())
                    
                    model.AddImplication(has_juniors, has_seniors)

        # --- 목적 함수: 선호도 점수 최대화 ---
        objective_terms = []
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx in range(self.config.num_shifts):
                    # 선호도 행렬에서 가중치를 가져와 목적 함수에 추가
                    pref_score = int(self.preference_matrix[n_idx, day, s_idx])
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 목적 함수 설정
        model.Maximize(sum(objective_terms))

        # --- 솔버 실행 ---
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        solver.parameters.num_search_workers = 8  # 병렬 처리
        
        status = solver.Solve(model)
        # --- 결과 처리 ---
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print(f"최적화 완료: {time.time() - start_time:.2f}초 소요")
            print(f"최적 목표 값: {solver.ObjectiveValue()}")
            
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    for s_idx in range(self.config.num_shifts):
                        if solver.Value(x[n_idx, day, s_idx]):
                            self.roster[n_idx, day, s_idx] = 1
                        else:
                            self.roster[n_idx, day, s_idx] = 0
            
            if status == cp_model.OPTIMAL:
                print("최적해를 찾았습니다!")
            else:
                print("가능한 해를 찾았습니다 (최적해가 아닐 수 있음).")
            return True
        else:
            print("해를 찾지 못했습니다. 제약 조건이 너무 엄격하거나 충돌할 수 있습니다.")
            if status == cp_model.INFEASIBLE:
                print("상태: INFEASIBLE")
            elif status == cp_model.MODEL_INVALID:
                print("상태: MODEL_INVALID")
            else:
                print(f"상태: {status}")

            return False
    def optimize_roster_with_cp_sat_v2(self, time_limit_seconds=30):
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
        
        # Get shift requirement priority
        shift_req_priority = getattr(self.config, 'shift_requirement_priority', 0.8)
        print(f"Shift requirement priority: {shift_req_priority:.2f}")
        
        # 가중치 계산 로직 개선 - 비선형 변환으로 더 효과적인 제어 
        # Higher priority → higher staffing penalty and lower preference boost
        staffing_penalty_base = 2000 
        staffing_penalty_weight = int(staffing_penalty_base * (shift_req_priority ** 2))
        
        # 선호도에 대한 가중치는 요구사항 우선순위에 반비례하게 설정
        # For preferences: non-linear inverse effect to create stronger contrast
        pref_boost_min = 0.8
        pref_boost_max = 2.5
        preference_boost_factor = pref_boost_min + (pref_boost_max - pref_boost_min) * ((1 - shift_req_priority) ** 1.5)
        
        # 요구사항 우선순위가 극단적으로 높은 경우에 대한 특별 처리
        if shift_req_priority > 0.95:
            staffing_penalty_weight = int(staffing_penalty_base * 5)  # 매우 높은 패널티
            preference_boost_factor = 0.5  # 선호도 가중치 크게 감소
        
        print(f"Dynamic weights: staffing penalty={staffing_penalty_weight}, preference boost={preference_boost_factor:.2f}")
        
        # Create the model
        model = cp_model.CpModel()
        off_idx = self.config.shift_types.index('OFF')
        # 1. Define variables
        # x[nurse, day, shift] = 1 if nurse is assigned to shift on day
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{shift}')
        
        # Generate a solution hint from current roster
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
        
        # 3. Add staffing requirements - 소프트 제약으로 구현 (위반 시 패널티 적용)
        staffing_penalty_vars = []
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                # Sum of nurses assigned to this shift
                num_assigned = sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses)))
                
                # 인원수 부족에 대한 패널티 변수
                shortage = model.NewIntVar(0, len(self.nurses), f'shortage_d{day}_s{shift}')
                model.Add(shortage >= required - num_assigned)
                staffing_penalty_vars.append(shortage)
        
        # 4. Add experience requirements - 소프트 제약으로 구현
        exp_penalty_vars = []
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                # Sum of experienced nurses assigned to this shift
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                # 경력 간호사 부족에 대한 패널티
                exp_shortage = model.NewIntVar(0, self.config.required_experienced_nurses, f'exp_shortage_d{day}_s{shift}')
                model.Add(exp_shortage >= self.config.required_experienced_nurses - exp_nurses_assigned)
                exp_penalty_vars.append(exp_shortage)
        
        # 5. Night nurse constraints - night nurses CANNOT work day shifts (HARD constraint 유지)
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    # Force day shift assignment to be 0 for night nurses
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 6. Add consecutive work days constraint - 소프트 제약으로 구현
        consecutive_penalty_vars = []
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_work_days):
                # 최대 연속 근무일 초과 여부 확인
                consecutive_work = []
                for d in range(day, day + self.config.max_consecutive_work_days + 1):
                    if d < self.num_days:  # 범위 확인
                        # Working = any shift except OFF
                        off_idx = self.config.shift_types.index('OFF') 
                        work_vars = [x[n_idx, d, s_idx] for s_idx in range(len(self.config.shift_types)) if s_idx != off_idx]
                        is_working = model.NewBoolVar(f'n{n_idx}_d{d}_working')
                        model.AddMaxEquality(is_working, work_vars)
                        consecutive_work.append(is_working)
                
                # 연속 근무일 초과 패널티
                if len(consecutive_work) > 0:
                    # 모든 날이 근무일인 경우 패널티
                    all_working = model.NewBoolVar(f'all_working_n{n_idx}_d{day}')
                    model.AddMinEquality(all_working, consecutive_work)
                    consecutive_penalty_vars.append(all_working)
        
        # 7. Add night shift constraints
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        
        # 7.1 Max consecutive nights - 소프트 제약으로 구현
        night_penalty_vars = []
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_nights):
                # 최대 연속 야간 근무 초과 확인
                consecutive_nights = [x[n_idx, d, night_idx] for d in range(day, day + self.config.max_consecutive_nights + 1) if d < self.num_days]
                if len(consecutive_nights) > 0:
                    nights_exceed = model.NewBoolVar(f'nights_exceed_n{n_idx}_d{day}')
                    model.AddMinEquality(nights_exceed, consecutive_nights)
                    night_penalty_vars.append(nights_exceed)
        
        # 7.2 No day shift after night shift - HARD 제약 유지
        for n_idx in range(len(self.nurses)):
            for day in range(1, self.num_days):
                # If worked night shift yesterday, can't work day shift today
                model.Add(x[n_idx, day, day_idx] <= 1 - x[n_idx, day-1, night_idx])
        
        # 7.3 Monthly night shift limit - 소프트 제약으로 구현
        monthly_night_penalty_vars = []
        for n_idx in range(len(self.nurses)):
            total_nights = sum(x[n_idx, day, night_idx] for day in range(self.num_days))
            # 월간 야간 근무 초과 패널티
            night_excess = model.NewIntVar(0, self.num_days, f'night_excess_n{n_idx}')
            model.Add(night_excess >= total_nights - self.config.max_night_shifts_per_month)
            monthly_night_penalty_vars.append(night_excess)
        
        # 8. Head nurse weekend pattern - HARD 제약 유지
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
        
        # 9. Handle resignation dates - HARD 제약 유지
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.resignation_date:
                resignation_day = (nurse.resignation_date - self.target_month).days
                if 0 <= resignation_day < self.num_days:
                    off_idx = self.config.shift_types.index('OFF')
                    for day in range(resignation_day, self.num_days):
                        model.Add(x[n_idx, day, off_idx] == 1)
        
        # 10. Objective function: maximize preference satisfaction with adjusted weights
        objective_terms = []
        
        # 10.1 Preference satisfaction with dynamic weight scaling
        # 선호도 가중치도 기본값을 높여서 더 강한 값을 가지도록 조정
        preference_base_multiplier = int(400 * preference_boost_factor)  # 기본 선호도 가중치 증가
        off_preference_multiplier = int(800 * preference_boost_factor)   # 휴무 선호도 가중치 증가
        
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    # Get base and current preference values
                    base_weight = self.config.shift_preference_weights.get(shift, 5.0)
                    pref_value = self.preference_matrix[n_idx, day, s_idx]
                    
                    # 선호 근무 유형에 대한 가중치 계산 (동적 가중치 적용)
                    if s_idx == off_idx and pref_value > 0:
                        # 선호 휴무일에 매우 높은 가중치 적용
                        # 선호도 값을 기반으로 비선형 점수 계산 (선호도 차이를 더 크게 만듦)
                        pref_score = int((pref_value ** 1.5) * off_preference_multiplier)
                    else:
                        # 다른 근무 유형에 대한 선호도 점수 계산 (D, E, N 선호도 반영)
                        # 비선형 변환으로 높은 선호도에 보너스 부여
                        pref_score = int((pref_value ** 1.3) * preference_base_multiplier)
                    
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 10.2 Night nurse specialization bonus - 동적 가중치 적용
        night_nurse_bonus = int(500 * preference_boost_factor)
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                # Bonus for night nurses working night shifts
                night_bonus = sum(night_nurse_bonus * x[n_idx, day, night_idx] for day in range(self.num_days))
                objective_terms.append(night_bonus)
                
        # 10.3 간호사 페어링 선호도 반영 - 동적 가중치 적용
        pair_weight_multiplier = int(300 * preference_boost_factor)
        
        if hasattr(self, 'pair_matrix'):
            # 함께 일하기 선호도 반영
            for n1 in range(len(self.nurses)):
                for n2 in range(n1 + 1, len(self.nurses)):
                    # 함께 일하기 선호도
                    if self.pair_matrix["together"][n1, n2] > 0:
                        weight = int(self.pair_matrix["together"][n1, n2] * pair_weight_multiplier)
                        for day in range(self.num_days):
                            for shift in self.config.daily_shift_requirements.keys():
                                s_idx = self.config.shift_types.index(shift)
                                
                                # n1과 n2가 같은 교대에 배정될 때 보너스
                                together_var = model.NewBoolVar(f'together_{n1}_{n2}_{day}_{shift}')
                                model.Add(together_var == 1).OnlyEnforceIf([x[n1, day, s_idx], x[n2, day, s_idx]])
                                model.Add(together_var == 0).OnlyEnforceIf([x[n1, day, s_idx].Not()])
                                model.Add(together_var == 0).OnlyEnforceIf([x[n2, day, s_idx].Not()])
                                objective_terms.append(weight * together_var)
                                
                    # 따로 일하기 선호도
                    if self.pair_matrix["apart"][n1, n2] > 0:
                        weight = int(self.pair_matrix["apart"][n1, n2] * pair_weight_multiplier)
                        for day in range(self.num_days):
                            # n1과 n2가 다른 교대에 배정될 때 보너스
                            # 각 근무 유형 쌍에 대해
                            for s1 in self.config.daily_shift_requirements.keys():
                                s1_idx = self.config.shift_types.index(s1)
                                for s2 in self.config.daily_shift_requirements.keys():
                                    if s1 == s2:
                                        continue
                                    s2_idx = self.config.shift_types.index(s2)
                                    
                                    # n1은 s1에, n2는 s2에 배정된 경우
                                    apart_var = model.NewBoolVar(f'apart_{n1}_{n2}_{day}_{s1}_{s2}')
                                    model.Add(apart_var == 1).OnlyEnforceIf([x[n1, day, s1_idx], x[n2, day, s2_idx]])
                                    model.Add(apart_var == 0).OnlyEnforceIf([x[n1, day, s1_idx].Not()])
                                    model.Add(apart_var == 0).OnlyEnforceIf([x[n2, day, s2_idx].Not()])
                                    objective_terms.append(weight * apart_var)
        
        # 10.4 Workload balance - Simplified to avoid non-affine expressions
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
        
        # 11. 휴무일 제한 추가 - 상한 제약은 유지, 하한은 변경
        off_idx = self.config.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            total_off = sum(x[n_idx, day, off_idx] for day in range(self.num_days))
            allowed_off = nurse.remaining_off_days
            model.Add(total_off <= allowed_off)
            
            # 최소 휴무일 제약 완화 (남은 휴무일의 일부는 사용하도록)
            min_off = int(allowed_off * 0.6)  # 60% 정도는 사용하도록 유도
            min_off_shortage = model.NewIntVar(0, allowed_off, f'min_off_shortage_n{n_idx}')
            model.Add(min_off_shortage >= min_off - total_off)
            objective_terms.append(-50 * min_off_shortage)  # 최소 휴무일 부족에 대한 패널티

        # Add fairness constraints (동적 가중치 적용)
        fairness_weight = int(20 * preference_boost_factor)
        min_work_days = (self.num_days * sum(self.config.daily_shift_requirements.values())) // (len(self.nurses) * 2)
        for n_idx in range(len(self.nurses)):
            # Encourage at least minimum workdays
            objective_terms.append(fairness_weight * work_days[n_idx])
            
            # But penalize excessive workdays
            excess_var = model.NewIntVar(0, self.num_days, f'excess_n{n_idx}')
            model.Add(excess_var >= work_days[n_idx] - (self.num_days - min_work_days))
            objective_terms.append(-fairness_weight * 2 * excess_var)
        
        # 제약 위반에 대한 패널티 추가 (소프트 제약) - 동적 가중치 적용
        # 인원 요구사항 위반 패널티 - 시프트별 중요도에 따라 차등 적용
        for idx, var in enumerate(staffing_penalty_vars):
            # 현재 이 패널티 변수가 어떤 시프트에 대한 것인지 파악
            day_idx = idx // len(self.config.daily_shift_requirements)
            shift_idx = idx % len(self.config.daily_shift_requirements)
            shifts = list(self.config.daily_shift_requirements.keys())
            
            # 기본 패널티에 시프트별 추가 가중치
            shift_penalty_factor = 1.0
            if shift_idx < len(shifts):
                current_shift = shifts[shift_idx]
                # 야간 시프트는 더 중요하게 여김
                if current_shift == 'N':
                    shift_penalty_factor = 1.2
            
            # 패널티 적용 - 높은 값으로 조정
            penalty = -int(staffing_penalty_weight * shift_penalty_factor) * var
            objective_terms.append(penalty)
        
        # 경력 간호사 요구사항 위반 패널티 - 강화
        exp_penalty_weight = int(500 * shift_req_priority)
        for var in exp_penalty_vars:
            objective_terms.append(-exp_penalty_weight * var)
        
        # 건강 관련 제약은 shift_req_priority와 관계없이 항상 높은 가중치 유지
        # 연속 근무일 초과 패널티 - 매우 높은 가중치 유지 
        consecutive_penalty_weight = 600
        for var in consecutive_penalty_vars:
            objective_terms.append(-consecutive_penalty_weight * var)
        
        # 연속 야간 근무 초과 패널티 - 매우 높은 가중치 유지
        night_penalty_weight = 600
        for var in night_penalty_vars:
            objective_terms.append(-night_penalty_weight * var)
        
        # 월간 야간 근무 초과 패널티
        monthly_night_penalty = int(400 * shift_req_priority)
        for var in monthly_night_penalty_vars:
            objective_terms.append(-monthly_night_penalty * var)
        
        # Set the objective
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        
        # 추가: 목표 함수 최적화 중지 기준 설정
        solver.parameters.num_search_workers = 8  # 병렬 검색 워커 수 증가
        solver.parameters.relative_gap_limit = 0.05  # 5% 상대 갭 제한 (완화)
        solver.parameters.solution_pool_size = 5  # 여러 해결책을 찾도록 설정
        # 추가 매개변수
        solver.parameters.max_time_in_seconds = time_limit_seconds + 30  # 시간 제한 증가
        solver.parameters.log_to_stdout = True  # 로그 출력 활성화
        
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
            
            # 제약 위반 카운트
            staffing_violations = sum(solver.Value(var) for var in staffing_penalty_vars)
            exp_violations = sum(solver.Value(var) for var in exp_penalty_vars)
            
            print(f"제약 위반 통계:")
            print(f"  인원 요구사항 위반: {staffing_violations}건")
            print(f"  경력자 요구사항 위반: {exp_violations}건")
            
            if status == cp_model.OPTIMAL:
                print("Found optimal solution!")
            else:
                print("Found feasible solution (may not be optimal)")
                
            # 일일 근무 배정 분석
            for day in range(self.num_days):
                for shift in self.config.daily_shift_requirements.keys():
                    s_idx = self.config.shift_types.index(shift)
                    required = self.config.daily_shift_requirements[shift]
                    assigned = sum(self.roster[n_idx, day, s_idx] for n_idx in range(len(self.nurses)))
                    
                    if assigned != required:
                        print(f"날짜 {day+1}, {shift} 근무: {assigned}명 배정됨 (요구: {required}명)")
                
            # 선호 휴무일 반영 분석
            off_idx = self.config.shift_types.index('OFF')
            total_preferences = 0
            satisfied_preferences = 0
            
            for n_idx in range(len(self.nurses)):
                nurse_prefs = 0
                nurse_satisfied = 0
                
                for day in range(self.num_days):
                    # 선호도가 높은 휴무일 (4점 이상)인 경우
                    if self.preference_matrix[n_idx, day, off_idx] >= 4:
                        nurse_prefs += 1
                        # 실제로 OFF를 받았는지 확인
                        if self.roster[n_idx, day, off_idx] == 1:
                            nurse_satisfied += 1
                
                if nurse_prefs > 0:
                    print(f"{self.nurses[n_idx].name}: 선호 휴무일 {nurse_satisfied}/{nurse_prefs} 반영됨 ({nurse_satisfied/nurse_prefs*100:.1f}%)")
                    total_preferences += nurse_prefs
                    satisfied_preferences += nurse_satisfied
            
            if total_preferences > 0:
                print(f"전체 선호 휴무일 반영률: {satisfied_preferences}/{total_preferences} ({satisfied_preferences/total_preferences*100:.1f}%)")
            
            return True
        else:
            print("No solution found.")
            print("Best objective bound:", solver.BestObjectiveBound())
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
        best_off_satisfaction = self._calculate_off_preference_satisfaction()
        print(f"초기 선호 휴무일 만족도: {best_off_satisfaction:.2f}%")
        
        # 선호 휴무일이 있는 날짜를 찾습니다
        off_idx = self.config.shift_types.index('OFF')
        preferred_off_days = {}
        for n_idx in range(len(self.nurses)):
            nurse_preferred_days = []
            for day in range(self.num_days):
                if self.preference_matrix[n_idx, day, off_idx] >= 4:
                    nurse_preferred_days.append(day)
            if nurse_preferred_days:
                preferred_off_days[n_idx] = nurse_preferred_days
        
        # 선호도 높은 간호사들의 순위 계산 (선호 휴무일이 많은 순서)
        nurse_priority = [(n_idx, len(days)) for n_idx, days in preferred_off_days.items()]
        nurse_priority.sort(key=lambda x: x[1], reverse=True)
        
        for iteration in range(max_iterations):
            print(f"\nLNS Iteration {iteration+1}/{max_iterations}")
            
            # Keep a copy of the current roster
            current_roster = self.roster.copy()
            
            # 이전 최적화에서 선호 휴무일 만족도를 계산
            current_off_satisfaction = self._calculate_off_preference_satisfaction()
            
            # 최적화 전략 선택 (반복마다 다양한 접근법 적용)
            strategy = iteration % 3
            
            if strategy == 0:
                # 전략 1: 선호 휴무일이 많은 간호사들 먼저 최적화
                nurses_to_optimize = [n_idx for n_idx, _ in nurse_priority[:min(5, len(nurse_priority))]]
                # 추가 랜덤 간호사 (다양성을 위해)
                if len(nurses_to_optimize) < 5:
                    other_nurses = [n for n in range(len(self.nurses)) if n not in nurses_to_optimize]
                    nurses_to_optimize.extend(np.random.choice(other_nurses, 
                                                            size=min(5-len(nurses_to_optimize), len(other_nurses)), 
                                                            replace=False))
                
                # 해당 간호사들의 선호 휴무일을 포함하는 날짜들 선택
                priority_days = set()
                for n_idx in nurses_to_optimize:
                    if n_idx in preferred_off_days:
                        priority_days.update(preferred_off_days[n_idx])
                
                days_to_optimize = list(priority_days)
                if len(days_to_optimize) > 7:
                    days_to_optimize = np.random.choice(days_to_optimize, size=7, replace=False)
                elif len(days_to_optimize) < 7:
                    other_days = [d for d in range(self.num_days) if d not in days_to_optimize]
                    additional_days = np.random.choice(other_days, 
                                                     size=min(7-len(days_to_optimize), len(other_days)), 
                                                     replace=False)
                    days_to_optimize.extend(additional_days)
                
                print(f"전략 1: 선호 휴무일 우선 최적화 ({len(days_to_optimize)} 일, {len(nurses_to_optimize)} 간호사)")
                
            elif strategy == 1:
                # 전략 2: 선호 휴무일 중에서 아직 만족되지 않은 날짜 위주로 최적화
                unsatisfied_days = []
                for n_idx, days in preferred_off_days.items():
                    for day in days:
                        if self.roster[n_idx, day, off_idx] == 0:  # OFF가 할당되지 않은 날
                            unsatisfied_days.append((n_idx, day))
                
                # 가장 많이 불만족된 날짜 선택
                day_counts = {}
                for _, day in unsatisfied_days:
                    day_counts[day] = day_counts.get(day, 0) + 1
                
                # 불만족도가 높은 순서로 정렬
                sorted_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)
                days_to_optimize = [day for day, _ in sorted_days[:min(7, len(sorted_days))]]
                
                # 해당 날짜에 선호가 있는 간호사 선택
                nurses_set = set()
                for n_idx, day in unsatisfied_days:
                    if day in days_to_optimize:
                        nurses_set.add(n_idx)
                
                nurses_to_optimize = list(nurses_set)
                if len(nurses_to_optimize) > 5:
                    nurses_to_optimize = np.random.choice(nurses_to_optimize, size=5, replace=False)
                elif len(nurses_to_optimize) < 5:
                    other_nurses = [n for n in range(len(self.nurses)) if n not in nurses_to_optimize]
                    additional_nurses = np.random.choice(other_nurses, 
                                                       size=min(5-len(nurses_to_optimize), len(other_nurses)), 
                                                       replace=False)
                    nurses_to_optimize.extend(additional_nurses)
                
                print(f"전략 2: 불만족 휴무일 중심 최적화 ({len(days_to_optimize)} 일, {len(nurses_to_optimize)} 간호사)")
                
            else:
                # 전략 3: 전체 랜덤 선택 (다양성 확보)
                days_to_optimize = np.random.choice(range(self.num_days), 
                                                  size=min(7, self.num_days), 
                                                  replace=False)
                nurses_to_optimize = np.random.choice(range(len(self.nurses)), 
                                                   size=min(5, len(self.nurses)), 
                                                   replace=False)
                print(f"전략 3: 랜덤 최적화 ({len(days_to_optimize)} 일, {len(nurses_to_optimize)} 간호사)")
            
            print(f"Re-optimizing days {sorted(days_to_optimize)} for nurse indices: {sorted(nurses_to_optimize)}")
            
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
                # 결과 평가
                new_violations = len(self._find_violations())
                new_off_satisfaction = self._calculate_off_preference_satisfaction()
                
                print(f"제약위반: {best_violations} -> {new_violations}")
                print(f"휴무 선호도 만족도: {current_off_satisfaction:.2f}% -> {new_off_satisfaction:.2f}%")
                
                # 해결책 수락 기준: 제약 위반 수가 감소하거나 동일하면서 선호도 만족도 증가
                if (new_violations < best_violations) or (new_violations == best_violations and new_off_satisfaction > best_off_satisfaction):
                    best_violations = new_violations
                    best_off_satisfaction = new_off_satisfaction
                    best_roster = self.roster.copy()
                    print("개선된 해결책 발견!")
                else:
                    # Rollback if no improvement
                    self.roster = current_roster
                    print("개선 없음, 변경 취소")
            else:
                # Rollback if optimization failed
                self.roster = current_roster
                print("최적화 실패, 변경 취소")
        
        # Always use the best roster found
        self.roster = best_roster
        
        print(f"LNS 완료: {time.time() - start_time:.2f}초 소요")
        print(f"최종 제약위반: {best_violations}")
        print(f"최종 휴무 선호도 만족도: {self._calculate_off_preference_satisfaction():.2f}%")
        return best_violations == 0
        
    def _calculate_off_preference_satisfaction(self):
        """선호 휴무일 만족도를 계산합니다."""
        off_idx = self.config.shift_types.index('OFF')
        total_preferences = 0
        satisfied_preferences = 0
        
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                # 선호도가 높은 휴무일 (4점 이상)인 경우
                if self.preference_matrix[n_idx, day, off_idx] >= 4:
                    total_preferences += 1
                    # 실제로 OFF를 받았는지 확인
                    if self.roster[n_idx, day, off_idx] == 1:
                        satisfied_preferences += 1
        
        if total_preferences == 0:
            return 100.0  # 선호 휴무일이 없으면 100% 만족
        
        return (satisfied_preferences / total_preferences) * 100.0
        
    def _calculate_shift_preference_satisfaction(self):
        """근무 유형(D, E, N) 선호도 만족도를 계산합니다."""
        total_preferences = 0
        satisfied_preferences = 0
        
        # 각 근무 유형에 대해 (OFF 제외)
        for shift in self.config.daily_shift_requirements.keys():
            s_idx = self.config.shift_types.index(shift)
            weight = self.config.shift_preference_weights.get(shift, 1.0) if hasattr(self.config, 'shift_preference_weights') else 1.0
            
            # 각 간호사와 날짜에 대해
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # 해당 근무 유형의 가중치가 특정 값 이상이면 선호 근무로 간주
                    if self.preference_matrix[n_idx, day, s_idx] >= weight:
                        total_preferences += 1
                        # 실제로 해당 근무 유형이 배정된 경우
                        if self.roster[n_idx, day, s_idx] == 1:
                            satisfied_preferences += 1
        
        if total_preferences == 0:
            return 100.0  # 선호 근무 유형이 없으면 100% 만족
        
        return (satisfied_preferences / total_preferences) * 100.0
        
    def _calculate_pair_preference_satisfaction(self):
        """간호사 페어링 선호도 만족도를 계산합니다."""
        if not hasattr(self, 'pair_matrix'):
            return {"together": 100.0, "apart": 100.0, "overall": 100.0}
            
        # 함께 일하기 선호도 만족도
        total_together_prefs = 0
        satisfied_together_prefs = 0
        
        # 따로 일하기 선호도 만족도
        total_apart_prefs = 0
        satisfied_apart_prefs = 0
        
        # 각 날짜에 대해
        for day in range(self.num_days):
            # 각 근무 유형에 대해
            for shift in self.config.daily_shift_requirements.keys():
                shift_idx = self.config.shift_types.index(shift)
                
                # 이 근무 유형에 배정된 간호사 찾기
                assigned_nurses = [i for i in range(len(self.nurses)) 
                                 if self.roster[i, day, shift_idx] == 1]
                
                # 함께 일하는 선호도 계산
                for i in range(len(assigned_nurses)):
                    for j in range(i+1, len(assigned_nurses)):
                        n1 = assigned_nurses[i]
                        n2 = assigned_nurses[j]
                        
                        # 함께 일하기 원하는 쌍인 경우
                        if self.pair_matrix["together"][n1, n2] > 0:
                            total_together_prefs += 1
                            satisfied_together_prefs += 1
                
                # 다른 교대에 배정된 간호사들과의 관계 확인
                for other_shift in self.config.daily_shift_requirements.keys():
                    if shift == other_shift:
                        continue
                        
                    other_shift_idx = self.config.shift_types.index(other_shift)
                    other_assigned = [i for i in range(len(self.nurses)) 
                                     if self.roster[i, day, other_shift_idx] == 1]
                    
                    # 두 교대 간의 간호사 쌍 확인
                    for n1 in assigned_nurses:
                        for n2 in other_assigned:
                            # 따로 일하기 원하는 쌍인 경우
                            if self.pair_matrix["apart"][n1, n2] > 0:
                                total_apart_prefs += 1
                                satisfied_apart_prefs += 1
        
        # 불만족 케이스 확인
        for n1 in range(len(self.nurses)):
            for n2 in range(n1+1, len(self.nurses)):
                # 함께 일하기 원하는 쌍인 경우
                if self.pair_matrix["together"][n1, n2] > 0:
                    # 각 날짜에 대해 함께 근무했는지 확인
                    for day in range(self.num_days):
                        together_today = False
                        
                        # 각 근무 유형에 대해
                        for shift in self.config.daily_shift_requirements.keys():
                            shift_idx = self.config.shift_types.index(shift)
                            
                            # 둘 다 같은 교대에 배정된 경우
                            if (self.roster[n1, day, shift_idx] == 1 and 
                                self.roster[n2, day, shift_idx] == 1):
                                together_today = True
                                break
                        
                        # 이날 함께 근무하지 않았으면 총 선호도 카운트만 추가
                        if not together_today:
                            total_together_prefs += 1
                
                # 따로 일하기 원하는 쌍인 경우
                if self.pair_matrix["apart"][n1, n2] > 0:
                    # 각 날짜에 대해 같은 근무에 배정되었는지 확인
                    for day in range(self.num_days):
                        for shift in self.config.daily_shift_requirements.keys():
                            shift_idx = self.config.shift_types.index(shift)
                            
                            # 둘 다 같은 교대에 배정된 경우 (선호도 불만족)
                            if (self.roster[n1, day, shift_idx] == 1 and 
                                self.roster[n2, day, shift_idx] == 1):
                                total_apart_prefs += 1
        
        # 종합 만족도 계산
        together_satisfaction = 100.0 if total_together_prefs == 0 else (satisfied_together_prefs / total_together_prefs) * 100.0
        apart_satisfaction = 100.0 if total_apart_prefs == 0 else (satisfied_apart_prefs / total_apart_prefs) * 100.0
        
        # 종합 선호도 점수
        total_prefs = total_together_prefs + total_apart_prefs
        satisfied_prefs = satisfied_together_prefs + satisfied_apart_prefs
        overall_satisfaction = 100.0 if total_prefs == 0 else (satisfied_prefs / total_prefs) * 100.0
        
        return {
            "together": together_satisfaction,
            "apart": apart_satisfaction,
            "overall": overall_satisfaction
        }
        
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
            
        # Add constraints - 소프트 제약 사용
        
        # 1. Add exactly-one constraint (HARD)
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(len(self.config.shift_types)))
        
        # 2. Add staffing requirements (SOFT)
        staffing_penalty_vars = []
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                num_assigned = sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses)))
                
                # 인원수 부족에 대한 패널티 변수
                shortage = model.NewIntVar(0, len(self.nurses), f'shortage_d{day}_s{shift}')
                model.Add(shortage >= required - num_assigned)
                staffing_penalty_vars.append(shortage)
        
        # 3. Experience requirements (SOFT)
        exp_penalty_vars = []
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                
                exp_shortage = model.NewIntVar(0, self.config.required_experienced_nurses, f'exp_shortage_d{day}_s{shift}')
                model.Add(exp_shortage >= self.config.required_experienced_nurses - exp_nurses_assigned)
                exp_penalty_vars.append(exp_shortage)
                
        # 4. Night nurse constraints (HARD) - night nurses CANNOT work day shifts
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 5. No day shift after night shift (HARD)
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        for n_idx in range(len(self.nurses)):
            for day in range(1, self.num_days):
                model.Add(x[n_idx, day, day_idx] <= 1 - x[n_idx, day-1, night_idx])
        
        # 6. 휴무일 제한 추가 (HARD) - 상한만 유지
        off_idx = self.config.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            total_off = sum(x[n_idx, day, off_idx] for day in range(self.num_days))
            allowed_off = nurse.remaining_off_days
            model.Add(total_off <= allowed_off)
        
        # Set the objective (preference focus)
        objective_terms = []
        
        # Preference satisfaction - 특히 선호 휴무일에 높은 가중치 부여
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    # 선호 근무 유형에 대한 가중치 계산
                    if s_idx == off_idx and self.preference_matrix[n_idx, day, s_idx] >= 4:
                        # 선호 휴무일에 매우 높은 가중치 (더 증가)
                        pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 1000)
                    else:
                        # 다른 근무 유형에 대한 선호도 점수 계산 (D, E, N 선호도 반영)
                        weight = self.config.shift_preference_weights.get(self.config.shift_types[s_idx], 1.0) if hasattr(self.config, 'shift_preference_weights') else 1.0
                        pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 100 * weight)
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 페어링 선호도 반영 - 함께 일하기 원하는 간호사 쌍
        if hasattr(self, 'pair_matrix'):
            for n1 in range(len(self.nurses)):
                for n2 in range(n1+1, len(self.nurses)):
                    # 함께 일하기 선호도
                    if self.pair_matrix["together"][n1, n2] > 0:
                        weight = int(self.pair_matrix["together"][n1, n2] * 100)
                        for day in range(self.num_days):
                            for shift in self.config.daily_shift_requirements.keys():
                                s_idx = self.config.shift_types.index(shift)
                                
                                # n1과 n2가 같은 교대에 배정될 때 보너스
                                together_var = model.NewBoolVar(f'together_{n1}_{n2}_{day}_{shift}')
                                model.Add(together_var == 1).OnlyEnforceIf([x[n1, day, s_idx], x[n2, day, s_idx]])
                                model.Add(together_var == 0).OnlyEnforceIf([x[n1, day, s_idx].Not()])
                                model.Add(together_var == 0).OnlyEnforceIf([x[n2, day, s_idx].Not()])
                                objective_terms.append(weight * together_var)
                                
                    # 따로 일하기 선호도
                    if self.pair_matrix["apart"][n1, n2] > 0:
                        weight = int(self.pair_matrix["apart"][n1, n2] * 100)
                        for day in range(self.num_days):
                            # n1과 n2가 다른 교대에 배정될 때 보너스
                            # 각 근무 유형 쌍에 대해
                            for s1 in self.config.daily_shift_requirements.keys():
                                s1_idx = self.config.shift_types.index(s1)
                                for s2 in self.config.daily_shift_requirements.keys():
                                    if s1 == s2:
                                        continue
                                    s2_idx = self.config.shift_types.index(s2)
                                    
                                    # n1은 s1에, n2는 s2에 배정된 경우
                                    apart_var = model.NewBoolVar(f'apart_{n1}_{n2}_{day}_{s1}_{s2}')
                                    model.Add(apart_var == 1).OnlyEnforceIf([x[n1, day, s1_idx], x[n2, day, s2_idx]])
                                    model.Add(apart_var == 0).OnlyEnforceIf([x[n1, day, s1_idx].Not()])
                                    model.Add(apart_var == 0).OnlyEnforceIf([x[n2, day, s2_idx].Not()])
                                    objective_terms.append(weight * apart_var)
        
        # Night nurse specialization bonus
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
            objective_terms.append(15 * sum(work_shifts))  # 25에서 15로 감소
            
        # 제약 위반 패널티 추가
        for var in staffing_penalty_vars:
            objective_terms.append(-800 * var)
            
        for var in exp_penalty_vars:
            objective_terms.append(-200 * var)
        
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        
        # 추가 최적화 설정
        solver.parameters.num_search_workers = 8
        solver.parameters.relative_gap_limit = 0.03  # 3% 상대 갭 제한
        solver.parameters.log_to_stdout = True
        
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
            
            # 제약 위반 통계
            staffing_violations = sum(solver.Value(var) for var in staffing_penalty_vars)
            exp_violations = sum(solver.Value(var) for var in exp_penalty_vars)
            
            print(f"LNS 최적화 완료:")
            print(f"  목표 함수 값: {solver.ObjectiveValue()}")
            print(f"  인원 요구사항 위반: {staffing_violations}건")
            print(f"  경력자 요구사항 위반: {exp_violations}건")
            
            return True
        else:
            print("Neighborhood optimization failed.")
            return False

#### 평가용 로직 
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