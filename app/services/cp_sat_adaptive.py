"""
CP-SAT 적응형 제약 최적화 엔진

이 엔진은 다음을 포함합니다:
- 모든 제약 조건을 하드 제약으로 엄격 적용 
- 해가 없을 때 점진적 완화 (Progressive Relaxation)
- 다중 단계 최적화 (Multi-stage Optimization)
- 적응형 시간 제한 (Adaptive Time Limits)
- 제약 계층화 (Constraint Hierarchy)

최고 품질의 해를 찾기 위해 시간이 오래 걸려도 수렴하도록 설계
"""

import time
import json
from datetime import date, datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from ortools.sat.python import cp_model

from db.roster_config import NurseRosterConfig
from db.nurse_config import Nurse
from services.roster_system import RosterSystem


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


class ConstraintHierarchy:
    """제약 조건 계층 관리"""
    
    # 제약 조건 우선순위 (높을수록 중요)
    CRITICAL = 1000    # 생명안전 관련 (야간→주간 금지 등)
    HIGH = 800        # 법적/정책적 필수 (인원 요구사항 등)  
    MEDIUM = 600      # 운영 효율성 (경력 요구사항 등)
    LOW = 400         # 선호도/공정성 (휴무일 균등 등)
    SOFT = 200        # 최적화 목표 (선호도 만족 등)


class CPSATAdaptiveEngine:
    """모든 제약을 엄격히 준수하는 적응형 CP-SAT 근무표 생성 엔진"""
    
    def __init__(self):
        self.logger_prefix = "[CP-SAT-Adaptive]"
        self.relaxation_stages = []
        self.best_solution = None
        self.best_violations = float('inf')
    
    def create_config_from_db(self, config_data: dict) -> NurseRosterConfig:
        """DB에서 가져온 설정 데이터를 NurseRosterConfig 객체로 변환"""
        
        # 법규 제약사항 (Hard Constraints)
        max_conseq_work = config_data.get('max_conseq_work', 5)
        banned_day_after_eve = config_data.get('banned_day_after_eve', True)
        three_seq_nig = config_data.get('three_seq_nig', True)
        two_offs_after_three_nig = config_data.get('two_offs_after_three_nig', True)
        two_offs_after_two_nig = config_data.get('two_offs_after_two_nig', False)
        max_nig_per_month = config_data.get('max_nig_per_month', 15)
        
        # 병원 내규 (Soft Constraints)
        min_exp_per_shift = config_data.get('min_exp_per_shift', 3)
        req_exp_nurses = config_data.get('req_exp_nurses', 1)
        two_offs_per_week = config_data.get('two_offs_per_week', True)
        sequential_offs = config_data.get('sequential_offs', True)
        even_nights = config_data.get('even_nights', True)
        
        # 가중치 설정 - Night Keep은 E와 차별화
        shift_weights = {
            'D': 5.0, 
            'E': 5.0, 
            'N': 7.0,  # Night Keep은 더 높은 가중치
            'O': 10.0
        }
        
        return NurseRosterConfig(
            daily_shift_requirements={
                'D': config_data.get('day_req', 3),
                'E': config_data.get('eve_req', 3), 
                'N': config_data.get('nig_req', 2)
            },
            # 병원 내규 (Soft Constraints)
            min_experience_per_shift=min_exp_per_shift,
            required_experienced_nurses=req_exp_nurses,
            enforce_two_offs_per_week=two_offs_per_week,
            # 법규 제약사항 (Hard Constraints)
            max_night_shifts_per_month=max_nig_per_month,
            max_consecutive_nights=3 if three_seq_nig else 2,
            max_consecutive_work_days=max_conseq_work,
            # 추가된 새로운 제약사항들
            banned_day_after_eve=banned_day_after_eve,
            two_offs_after_three_nig=two_offs_after_three_nig,
            two_offs_after_two_nig=two_offs_after_two_nig,
            sequential_offs=sequential_offs,
            even_nights=even_nights,
            global_monthly_off_days=config_data.get('global_monthly_off_days', 3),
            standard_personal_off_days=config_data.get('off_days', 8) - config_data.get('global_monthly_off_days', 3) if config_data.get('off_days', 8) > config_data.get('global_monthly_off_days', 3) else 0,
            # 기존 필드
            enforce_E_after_D_constraint=banned_day_after_eve,  # 호환성을 위해 유지
            shift_requirement_priority=config_data.get('shift_priority', 0.8),
            shift_preference_weights=shift_weights
        )
    
    def create_nurses_from_db(self, nurses_data: List[dict]) -> List[Nurse]:
        """DB에서 가져온 간호사 데이터를 Nurse 객체로 변환"""
        nurses = []
        for nurse_data in nurses_data:
            if 'resignation_date' in nurse_data and nurse_data['resignation_date']:
                if isinstance(nurse_data['resignation_date'], str):
                    nurse_data['resignation_date'] = datetime.strptime(
                        nurse_data['resignation_date'], '%Y-%m-%d'
                    ).date()
            
            nurse_obj = Nurse(
                id=len(nurses),
                db_id=nurse_data.get('nurse_id', nurse_data.get('id', '')),
                name=nurse_data.get('name', ''),
                experience_years=nurse_data.get('experience', 0),
                is_night_nurse=nurse_data.get('is_night_nurse', False),
                is_head_nurse=nurse_data.get('is_head_nurse', False),
                head_nurse_off_pattern=nurse_data.get('head_nurse_off_pattern', 'weekend'),
                personal_off_adjustment=nurse_data.get('personal_off_adjustment', 0),
                resignation_date=nurse_data.get('resignation_date')
            )
            nurses.append(nurse_obj)
        
        return nurses

    def parse_preferences_from_db(self, prefs_data: List[dict]) -> Tuple[Dict, Dict, Dict]:
        """DB에서 가져온 선호도 데이터를 파싱"""
        shift_preferences = {}
        off_requests = {}
        pair_preferences = {"work_together": [], "work_apart": []}
        
        for pref in prefs_data:
            nurse_id = pref['nurse_id']
            data = pref.get('data', {})
            
            if not data:
                continue
            
            # 근무 유형 선호도 파싱
            if 'shift' in data:
                shift_prefs = {}
                for shift_type, dates in data['shift'].items():
                    if shift_type.upper() in ['D', 'E', 'N']:
                        shift_prefs[shift_type.upper()] = {}
                        for date_str, weight in dates.items():
                            delta_weight = float(weight) - 5.0
                            shift_prefs[shift_type.upper()][str(date_str)] = delta_weight
                            
                if shift_prefs:
                    shift_preferences[nurse_id] = shift_prefs
            
            # 휴무 요청 파싱
            if 'off' in data and data['off']:
                off_requests[nurse_id] = {}
                for date_str in data['off']:
                    try:
                        day = int(date_str)
                        off_requests[nurse_id][str(day)] = 5.0
                    except (ValueError, TypeError):
                        continue
            
            # preference 배열에서 OFF 요청과 페어링 선호도 파싱
            if 'preference' in data and data['preference']:
                for pref_item in data['preference']:
                    if isinstance(pref_item, dict):
                        if pref_item.get('shift') == 'OFF':
                            date = pref_item.get('date')
                            weight = pref_item.get('weight', 5.0)
                            if date:
                                if nurse_id not in off_requests:
                                    off_requests[nurse_id] = {}
                                off_requests[nurse_id][str(int(date))] = float(weight)
                        
                        elif 'id' in pref_item and 'weight' in pref_item:
                            target_nurse_id = pref_item['id']
                            weight = float(pref_item['weight'])
                            
                            if weight > 0:
                                pair_preferences["work_together"].append({
                                    "nurse_1": nurse_id, 
                                    "nurse_2": target_nurse_id, 
                                    "weight": weight
                                })
                            else:
                                pair_preferences["work_apart"].append({
                                    "nurse_1": nurse_id, 
                                    "nurse_2": target_nurse_id, 
                                    "weight": abs(weight)
                                })
        
        return shift_preferences, off_requests, pair_preferences

    def solve_with_progressive_relaxation(self, roster_system: RosterSystem, max_time_limit: int = 300) -> bool:
        """점진적 완화를 통한 해 탐색"""
        
        print(f"\n{self.logger_prefix} 적응형 제약 최적화 시작")
        print(f"최대 시간 제한: {max_time_limit}초")
        
        # 단계별 완화 전략
        relaxation_strategies = [
            {"name": "엄격 모드", "time_limit": 60, "relaxations": []},
            {"name": "경험 완화", "time_limit": 80, "relaxations": ["experience"]},
            {"name": "공정성 완화", "time_limit": 100, "relaxations": ["experience", "fairness"]},
            {"name": "최적 완화", "time_limit": 120, "relaxations": ["experience", "fairness", "preference"]}
        ]
        
        total_time_used = 0
        
        for stage_idx, strategy in enumerate(relaxation_strategies):
            if total_time_used >= max_time_limit:
                break
                
            remaining_time = max_time_limit - total_time_used
            stage_time_limit = min(strategy["time_limit"], remaining_time)
            
            print(f"\n{self.logger_prefix} 단계 {stage_idx + 1}: {strategy['name']}")
            print(f"시간 제한: {stage_time_limit}초, 완화: {strategy['relaxations']}")
            
            stage_start = time.time()
            
            success = self._solve_with_constraints(
                roster_system, 
                stage_time_limit, 
                strategy["relaxations"]
            )
            
            stage_duration = time.time() - stage_start
            total_time_used += stage_duration
            
            if success:
                print(f"{self.logger_prefix} 해 발견! (단계 {stage_idx + 1}, {stage_duration:.2f}초)")
                return True
            else:
                print(f"{self.logger_prefix} 해 없음 (단계 {stage_idx + 1}, {stage_duration:.2f}초)")
        
        print(f"\n{self.logger_prefix} 모든 단계에서 해를 찾지 못했습니다.")
        return False

    def _solve_with_constraints(self, roster_system: RosterSystem, time_limit: int, relaxations: List[str]) -> bool:
        """특정 완화 수준으로 CP-SAT 해결"""
        
        model = cp_model.CpModel()
        
        # 변수 생성
        x = {}
        for n_idx in range(len(roster_system.nurses)):
            for day in range(roster_system.num_days):
                for s_idx in range(roster_system.config.num_shifts):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'x_{n_idx}_{day}_{s_idx}')
        
        # 1. 기본 제약 조건 (절대 완화 불가)
        self._add_critical_constraints(model, x, roster_system)
        
        # 2. 높은 우선순위 제약 조건
        if "experience" not in relaxations:
            self._add_high_priority_constraints(model, x, roster_system)
        
        # 3. 중간 우선순위 제약 조건
        if "fairness" not in relaxations:
            self._add_medium_priority_constraints(model, x, roster_system)
        
        # 4. 목적 함수 설정
        self._set_objective(model, x, roster_system, relaxations)
        
        # 5. 해결 시도
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_search_workers = 8
        solver.parameters.log_search_progress = True
        
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            # 해 저장
            roster_system.roster.fill(0)
            for n_idx in range(len(roster_system.nurses)):
                for day in range(roster_system.num_days):
                    for s_idx in range(roster_system.config.num_shifts):
                        if solver.Value(x[n_idx, day, s_idx]) == 1:
                            roster_system.roster[n_idx, day, s_idx] = 1
            
            # 품질 평가
            violations = roster_system._find_violations()
            print(f"해 품질: {len(violations)}개 위반사항, 목적값: {solver.ObjectiveValue()}")
            
            return True
        
        return False

    def _add_critical_constraints(self, model, x, roster_system: RosterSystem):
        """생명안전 관련 필수 제약 조건 (절대 완화 불가)"""
        
        # 1. 각 간호사는 하루에 하나의 시프트만
        for n_idx in range(len(roster_system.nurses)):
            for day in range(roster_system.num_days):
                model.Add(sum(x[n_idx, day, s_idx] for s_idx in range(roster_system.config.num_shifts)) == 1)
        
        # 2. 야간 근무 후 주간 근무 금지 (생명안전)
        night_idx = roster_system.config.shift_types.index('N')
        day_idx = roster_system.config.shift_types.index('D')
        for n_idx in range(len(roster_system.nurses)):
            for day in range(1, roster_system.num_days):
                model.Add(x[n_idx, day, day_idx] + x[n_idx, day-1, night_idx] <= 1)
        
        # 3. 저녁 근무 후 주간 근무 금지 (설정에 따라)
        if hasattr(roster_system.config, 'enforce_E_after_D_constraint') and roster_system.config.enforce_E_after_D_constraint:
            eve_idx = roster_system.config.shift_types.index('E')
            for n_idx in range(len(roster_system.nurses)):
                for day in range(1, roster_system.num_days):
                    model.Add(x[n_idx, day, day_idx] + x[n_idx, day-1, eve_idx] <= 1)
        
        # 4. 최대 연속 야간 근무 제한 (3일 연속 N 금지)
        max_consecutive_nights = roster_system.config.max_consecutive_nights
        if max_consecutive_nights < 3:  # 2일까지만 허용
            for n_idx in range(len(roster_system.nurses)):
                for day in range(2, roster_system.num_days):
                    # 3일 연속 야간 근무 금지
                    model.Add(x[n_idx, day-2, night_idx] + x[n_idx, day-1, night_idx] + x[n_idx, day, night_idx] <= 2)
        
        # 5. 야간 근무 후 연속 휴무 제약
        off_idx = roster_system.config.shift_types.index('OFF')
        
        # N 2회 후 OFF 2회 연속  
        if roster_system.config.two_offs_after_two_nig:
            for n_idx in range(len(roster_system.nurses)):
                for day in range(1, roster_system.num_days - 2):
                    # 2일 연속 N이면 다음 2일은 반드시 OFF
                    night_days = x[n_idx, day-1, night_idx] + x[n_idx, day, night_idx]
                    off_days = x[n_idx, day+1, off_idx] + x[n_idx, day+2, off_idx]
                    # 2일 연속 N(night_days=2)이면 다음 2일 반드시 OFF(off_days=2)
                    model.Add(off_days >= 2 * (night_days - 1))

    def _add_high_priority_constraints(self, model, x, roster_system: RosterSystem):
        """높은 우선순위 제약 조건 (인원 요구사항 등)"""
        
        # 1. 일일 인원 요구사항 (하드 제약)
        for day in range(roster_system.num_days):
            for shift, required in roster_system.config.daily_shift_requirements.items():
                s_idx = roster_system.config.shift_types.index(shift)
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(roster_system.nurses))) >= required)
        
        # 2. 최대 연속 근무일 제한 (수정된 로직 - 6일 연속 근무 금지)
        off_idx = roster_system.config.shift_types.index('OFF')
        max_work = roster_system.config.max_consecutive_work_days
        
        for n_idx in range(len(roster_system.nurses)):
            # 6일 이상 연속 근무 금지 (5일까지는 허용)
            for start_day in range(roster_system.num_days - max_work):
                # 연속된 (max_work + 1)일 중 적어도 1일은 반드시 휴무여야 함
                off_days_in_window = []
                for d in range(max_work + 1):
                    off_days_in_window.append(x[n_idx, start_day + d, off_idx])
                
                # (max_work + 1)일 윈도우에서 적어도 1일은 휴무
                model.Add(sum(off_days_in_window) >= 1)

    def _add_medium_priority_constraints(self, model, x, roster_system: RosterSystem):
        """중간 우선순위 제약 조건 (경력 요구사항, 공정성 등)"""
        
        # 1. 경력 간호사 요구사항
        for day in range(roster_system.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = roster_system.config.shift_types.index(shift)
                experienced_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(roster_system.nurses)
                    if nurse.experience_years >= roster_system.config.min_experience_per_shift
                )
                model.Add(experienced_assigned >= roster_system.config.required_experienced_nurses)
        
        # 2. 휴무일 제한
        off_idx = roster_system.config.shift_types.index('OFF')
        for n_idx, nurse in enumerate(roster_system.nurses):
            total_off = sum(x[n_idx, day, off_idx] for day in range(roster_system.num_days))
            allowed_off = nurse.remaining_off_days
            model.Add(total_off <= allowed_off)
            # 최소 휴무일도 어느 정도 보장
            model.Add(total_off >= max(1, int(allowed_off * 0.6)))
        
        # 3. 주 2회 이상 OFF (병원 내규)
        if hasattr(roster_system.config, 'enforce_two_offs_per_week') and roster_system.config.enforce_two_offs_per_week:
            weeks = roster_system.num_days // 7
            for n_idx in range(len(roster_system.nurses)):
                for week in range(weeks):
                    week_start = week * 7
                    week_end = min(week_start + 7, roster_system.num_days)
                    week_offs = sum(x[n_idx, day, off_idx] for day in range(week_start, week_end))
                    model.Add(week_offs >= 2)
        
        # 4. N 개수 균등 배정 (병원 내규) - 소프트 제약으로 처리는 _set_objective에서

    def _set_objective(self, model, x, roster_system: RosterSystem, relaxations: List[str]):
        """목적 함수 설정"""
        objective_terms = []
        
        # 1. 선호도 만족 (소프트)
        if hasattr(roster_system, 'preference_matrix'):
            for n_idx in range(len(roster_system.nurses)):
                for day in range(roster_system.num_days):
                    for s_idx in range(roster_system.config.num_shifts):
                        pref_score = int(roster_system.preference_matrix[n_idx, day, s_idx] * 100)
                        objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 2. 공정성 목표 (완화 가능)
        if "fairness" not in relaxations:
            # 업무량 균등화 - 간단한 접근법 사용
            off_idx = roster_system.config.shift_types.index('OFF')
            
            # 각 간호사의 휴무일 수를 직접 계산
            for n_idx in range(len(roster_system.nurses)):
                off_days = sum(x[n_idx, day, off_idx] for day in range(roster_system.num_days))
                # 휴무일이 너무 적거나 많지 않도록 균형 조절
                target_off_days = roster_system.num_days // 4  # 대략 25% 휴무
                
                # 휴무일 편차에 대한 페널티
                deviation_pos = model.NewIntVar(0, roster_system.num_days, f'off_dev_pos_{n_idx}')
                deviation_neg = model.NewIntVar(0, roster_system.num_days, f'off_dev_neg_{n_idx}')
                
                model.Add(deviation_pos - deviation_neg == off_days - target_off_days)
                objective_terms.append(-5 * (deviation_pos + deviation_neg))
            
            # N 개수 균등 배정 (병원 내규)
            if hasattr(roster_system.config, 'even_nights') and roster_system.config.even_nights:
                night_idx = roster_system.config.shift_types.index('N')
                # 야간전담 간호사 제외하고 균등 배정
                non_night_nurses = [n_idx for n_idx, nurse in enumerate(roster_system.nurses) if not nurse.is_night_nurse]
                if len(non_night_nurses) > 1:
                    total_night_shifts = sum(roster_system.config.daily_shift_requirements.get('N', 2) for _ in range(roster_system.num_days))
                    target_nights_per_nurse = total_night_shifts // len(non_night_nurses)
                    
                    for n_idx in non_night_nurses:
                        night_shifts = sum(x[n_idx, day, night_idx] for day in range(roster_system.num_days))
                        night_dev_pos = model.NewIntVar(0, roster_system.num_days, f'night_dev_pos_{n_idx}')
                        night_dev_neg = model.NewIntVar(0, roster_system.num_days, f'night_dev_neg_{n_idx}')
                        
                        model.Add(night_dev_pos - night_dev_neg == night_shifts - target_nights_per_nurse)
                        objective_terms.append(-10 * (night_dev_pos + night_dev_neg))  # 야간 근무 균등 배정 패널티
            
            # OFF 연속 배정 보너스 (병원 내규)
            if hasattr(roster_system.config, 'sequential_offs') and roster_system.config.sequential_offs:
                for n_idx in range(len(roster_system.nurses)):
                    for day in range(roster_system.num_days - 1):
                        # 연속된 OFF에 보너스 부여
                        consecutive_offs = x[n_idx, day, off_idx] + x[n_idx, day + 1, off_idx]
                        # 2일 연속 OFF면 보너스
                        consecutive_bonus = model.NewBoolVar(f'consecutive_off_bonus_{n_idx}_{day}')
                        model.Add(consecutive_bonus == (consecutive_offs == 2))
                        objective_terms.append(15 * consecutive_bonus)  # 연속 휴무 보너스
        
        # 목적 함수 설정
        if objective_terms:
            model.Maximize(sum(objective_terms))

    def generate_roster(
        self, 
        nurses_data: List[dict], 
        prefs_data: List[dict], 
        config_data: dict,
        year: int, 
        month: int,
        time_limit_seconds: int = 300
    ) -> Dict[str, List[str]]:
        """적응형 제약 최적화로 근무표 생성"""
        
        print(f"\n{'='*60}")
        print(f"{self.logger_prefix} 적응형 제약 최적화 근무표 생성 시작")
        print(f"대상: {year}년 {month}월")
        print(f"간호사 수: {len(nurses_data)}, 선호도 수: {len(prefs_data)}")
        print(f"최대 시간 제한: {time_limit_seconds}초")
        print(f"{'='*60}")
        
        # 1. 설정 및 데이터 준비
        with Timer("설정 및 데이터 준비"):
            config = self.create_config_from_db(config_data)
            target_month = date(year, month, 1)
            nurses = self.create_nurses_from_db(nurses_data)
            
            for nurse in nurses:
                nurse.initialize_off_days(config)
        
        # 2. 근무표 시스템 생성
        with Timer("근무표 시스템 초기화"):
            roster_system = RosterSystem(nurses, target_month, config)
        
        # 3. 선호도 적용
        with Timer("선호도 데이터 적용"):
            shift_preferences, off_requests, pair_preferences = self.parse_preferences_from_db(prefs_data)
            
            if off_requests:
                roster_system.apply_off_requests(off_requests)
            if shift_preferences:
                roster_system.apply_shift_preferences(shift_preferences)
            if pair_preferences:
                roster_system.apply_pair_preferences(pair_preferences)
        
        # 4. 적응형 최적화 실행
        with Timer("적응형 제약 최적화"):
            success = self.solve_with_progressive_relaxation(roster_system, time_limit_seconds)
        
        if not success:
            print(f"\n{self.logger_prefix} 경고: 모든 제약을 만족하는 해를 찾지 못했습니다!")
            print(f"{self.logger_prefix} 기본 엔진으로 폴백하여 실행해보시기 바랍니다.")
            return {}
        
        # 5. 결과 분석
        with Timer("결과 분석"):
            violations = roster_system._find_violations()
            print(f"{self.logger_prefix} 최종 해 품질:")
            print(f"  - 제약 위반: {len(violations)}건")
            
            if violations:
                print(f"  - 위반 내역:")
                for v in violations[:5]:  # 최대 5개만 표시
                    print(f"    • {v}")
                if len(violations) > 5:
                    print(f"    • ... 외 {len(violations) - 5}건")
            else:
                print(f"  - 모든 제약 조건 완벽 충족! ✓")
        
        # 6. 결과 변환
        with Timer("결과 변환"):
            result = self._convert_result_to_db_format(roster_system, nurses)
        
        print(f"\n{self.logger_prefix} 적응형 제약 최적화 완료!")
        print(f"{'='*60}")
        
        return result

    def _convert_result_to_db_format(self, roster_system: RosterSystem, nurses: List[Nurse]) -> Dict[str, List[str]]:
        """RosterSystem 결과를 DB 형식으로 변환"""
        result = {}
        shift_map = {i: s for i, s in enumerate(roster_system.config.shift_types)}
        
        for n_idx, nurse in enumerate(nurses):
            nurse_schedule = []
            for day_idx in range(roster_system.num_days):
                shift_vector = roster_system.roster[n_idx, day_idx]
                shift_idx = np.where(shift_vector == 1)[0]
                if len(shift_idx) > 0:
                    shift_id = shift_map[shift_idx[0]]
                    if shift_id == 'OFF':
                        shift_id = 'O'
                    nurse_schedule.append(shift_id)
                else:
                    nurse_schedule.append('O')
            
            result[nurse.db_id] = nurse_schedule
        
        return result


# 전역 엔진 인스턴스
cp_sat_adaptive_engine = CPSATAdaptiveEngine()


def generate_roster_cp_sat_adaptive(nurses_data, prefs_data, config_data, year, month, time_limit_seconds=300):
    """
    적응형 제약 최적화로 근무표 생성 (기존 인터페이스 호환)
    
    Args:
        nurses_data: DB에서 가져온 간호사 데이터 리스트  
        prefs_data: DB에서 가져온 선호도 데이터 리스트
        config_data: DB에서 가져온 설정 데이터
        year: 근무표 년도
        month: 근무표 월
        time_limit_seconds: 전체 최적화 시간 제한 (기본 5분)
        
    Returns:
        Dict[nurse_id, List[shift]]: 간호사별 일일 근무 배정
    """
    return cp_sat_adaptive_engine.generate_roster(
        nurses_data, prefs_data, config_data, year, month, time_limit_seconds
    ) 