from datetime import date, datetime, timedelta
import time
import numpy as np
from typing import List, Dict, Optional, Tuple
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


class CPSATBasicEngine:
    """CP-SAT 기반 근무표 생성 엔진"""
    
    def __init__(self):
        self.logger_prefix = "[CP-SAT-Basic]"
    
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
            'OFF': 10.0
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
            global_monthly_off_days=2,
            standard_personal_off_days=config_data.get('off_days', 8) - 2 if config_data.get('off_days', 8) > 2 else 0,
            shift_requirement_priority=config_data.get('shift_priority', 0.7),
            shift_preference_weights=shift_weights,
            pair_preference_weight=3.0
        )
    
    def create_nurses_from_db(self, nurses_data: List[dict]) -> List[Nurse]:
        """DB에서 가져온 간호사 데이터를 Nurse 객체 리스트로 변환"""
        nurses = []
        for i, nurse_data in enumerate(nurses_data):
            # DB 모델을 Nurse 객체로 변환
            nurse_dict = {
                'id': i,  # 엔진에서 사용할 인덱스 ID
                'db_id': nurse_data['nurse_id'],  # DB ID
                'name': nurse_data['name'],
                'experience_years': nurse_data.get('experience', 0),
                'is_head_nurse': nurse_data.get('is_head_nurse', False),
                'is_night_nurse': nurse_data.get('is_night_nurse', False),
                'personal_off_adjustment': nurse_data.get('personal_off_adjustment', 0),
                'remaining_off_days': 0,  # 초기화, 나중에 계산됨
                'joining_date': nurse_data.get('joining_date', None),
                'resignation_date': nurse_data.get('resignation_date', None)
            }
            
            # resignation_date 처리
            if nurse_data.get('resignation_date'):
                if isinstance(nurse_data['resignation_date'], str):
                    nurse_dict['resignation_date'] = datetime.strptime(
                        nurse_data['resignation_date'], '%Y-%m-%d'
                    ).date()
                else:
                    nurse_dict['resignation_date'] = nurse_data['resignation_date']
            
            nurses.append(Nurse(**nurse_dict))
        
        return nurses
    
    def parse_preferences_from_db(self, prefs_data: List[dict]) -> Tuple[Dict, Dict, Dict]:
        """
        DB에서 가져온 선호도 데이터를 main_v3.py 형식으로 변환
        
        Returns:
            Tuple[shift_preferences, off_requests, pair_preferences]
        """
        shift_preferences = {}
        off_requests = {}
        pair_preferences = {"work_together": [], "work_apart": []}
        
        for pref in prefs_data:
            nurse_id = pref['nurse_id']
            data = pref.get('data', {})
            if not data:
                continue
            # print('\n\n\n\n\ndata', data, '\n\n\n\n\n')
            # 근무 유형 선호도 파싱
            if 'shift' in data:
                shift_prefs = {}
                for shift_type, dates in data['shift'].items():
                    if shift_type.upper() in ['D', 'E', 'N']:
                        shift_prefs[shift_type.upper()] = dates
                if shift_prefs:
                    shift_preferences[nurse_id] = shift_prefs

            # 휴무 요청 파싱
            if 'O' in data['shift']:
                # off_dict = {}
                # for date_str in data['O']:
                #     try:
                #         day = int(date_str)
                #         # 기본 휴무 요청 가중치 설정
                #         off_dict[str(day)] += 5.0  
                #     except (ValueError, TypeError):
                #         continue
                # if off_dict:
                off_requests[nurse_id] = data['shift']['O']
                print('\n\n\n\n\noff_requests', off_requests, '\n\n\n\n\n')
            
            # preference 파싱
            if 'preference' in data and data['preference']:
                print(data['preference'])
                for d in data['preference']:
                    if d['weight'] <0:
                        pair_preferences["work_apart"].append({"nurse_1":nurse_id, "nurse_2": d['id'], "weight": d['weight']})
                    elif d['weight'] >0:
                        pair_preferences["work_together"].append({"nurse_1":nurse_id, "nurse_2":d['id'], "weight": d['weight']})
        return shift_preferences, off_requests, pair_preferences
    
    def generate_roster(
        self, 
        nurses_data: List[dict], 
        prefs_data: List[dict], 
        config_data: dict,
        year: int, 
        month: int,
        time_limit_seconds: int = 60
    ) -> Dict[str, List[str]]:
        """
        DB 데이터를 기반으로 CP-SAT를 사용해 근무표를 생성
        
        Args:
            nurses_data: DB에서 가져온 간호사 데이터 리스트
            prefs_data: DB에서 가져온 선호도 데이터 리스트  
            config_data: DB에서 가져온 설정 데이터
            year: 근무표 년도
            month: 근무표 월
            time_limit_seconds: CP-SAT 최적화 시간 제한
            
        Returns:
            Dict[nurse_id, List[shift]]: 간호사별 일일 근무 배정
        """
        
        print(f"{self.logger_prefix} 근무표 생성 시작: {year}년 {month}월")
        
        # 1. 설정 객체 생성
        with Timer("설정 생성"):
            config = self.create_config_from_db(config_data)
        
        # 2. 대상 월 설정
        target_month = date(year, month, 1)
        
        # 3. 간호사 객체 생성
        with Timer("간호사 객체 생성"):
            nurses = self.create_nurses_from_db(nurses_data)
            for nurse in nurses:
                nurse.initialize_off_days(config)
        
        # 4. 근무표 시스템 생성
        with Timer("근무표 시스템 초기화"):
            roster_system = RosterSystem(nurses, target_month, config)
        
        # 5. 선호도 데이터 파싱 및 적용
        with Timer("선호도 데이터 파싱"):
            shift_preferences, off_requests, pair_preferences = self.parse_preferences_from_db(prefs_data)
        
        # 6. 휴무 요청 적용
        if off_requests:
            with Timer("휴무 요청 적용"):
                print(f"{self.logger_prefix} 휴무 요청 적용 중...")
                # DB nurse_id를 키로 사용하여 매핑
                mapped_off_requests = {}
                for nurse_id, requests in off_requests.items():
                    # DB nurse_id를 그대로 키로 사용 (roster_system.py에서 n.db_id와 비교하므로)
                    mapped_off_requests[nurse_id] = {str(k): v for k, v in requests.items()}
                
                roster_system.apply_off_requests(mapped_off_requests)
        
        # 7. 선호 근무 유형 적용  
        if shift_preferences:
            with Timer("선호 근무 유형 적용"):
                print(f"{self.logger_prefix} 선호 근무 유형 적용 중...")
                # DB nurse_id를 키로 사용하여 매핑
                mapped_shift_preferences = {}
                for nurse_id, prefs in shift_preferences.items():
                    # DB nurse_id를 그대로 키로 사용
                    mapped_shift_preferences[nurse_id] = prefs
                
                roster_system.apply_shift_preferences(mapped_shift_preferences)
        
        # 8. 페어링 선호도 적용
        with Timer("페어링 선호도 적용"):
            print(f"{self.logger_prefix} 페어링 선호도 적용 중...")
            # 기본값으로 빈 페어링 선호도 설정
            roster_system.apply_pair_preferences(pair_preferences)
        
        # 9. CP-SAT으로 최적화 (새로운 제약사항 포함)
        with Timer("CP-SAT으로 최적화"):
            print(f"{self.logger_prefix} CP-SAT 최적화 시작 (시간 제한: {time_limit_seconds}초)...")
            success = self._optimize_with_enhanced_constraints(roster_system, time_limit_seconds, nurses)
            
            if not success:
                print(f"{self.logger_prefix} 개선된 제약사항으로 실패, 기본 알고리즘으로 폴백...")
                roster_system.optimize_roster_with_cp_sat_v2(time_limit_seconds=time_limit_seconds)
        
        # 10. 결과 변환
        with Timer("결과 변환"):
            result = self._convert_result_to_db_format(roster_system, nurses)
        
        # 11. 최적화 결과 출력
        self._print_optimization_results(roster_system)
        
        print(f"{self.logger_prefix} 근무표 생성 완료")
        return result
    
    def _optimize_with_enhanced_constraints(self, roster_system: RosterSystem, time_limit_seconds: int, nurses) -> bool:
        """법규 제약사항과 병원 내규를 포함한 CP-SAT 최적화"""
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("OR-Tools를 찾을 수 없습니다.")
            return False


        """입사일·법규·내규를 모두 반영한 CP‑SAT 최적화"""
        from datetime import date
        from ortools.sat.python import cp_model
        import time
        start_time = time.time()
        model = cp_model.CpModel()
        # ───── 0. 사전 계산 ─────────────────────────────────────────────
        N = len(roster_system.nurses)
        D = roster_system.num_days
        S = roster_system.config.num_shifts

        first_day: date = roster_system.target_month          # 해당 월 1일
        join_idx:  list[int] = []    # 입사일부터 근무
        leave_idx: list[int] = []    # 퇴사전날까지 근무
        for nurse in roster_system.nurses:
            if nurse.joining_date:
                idx = (nurse.joining_date - first_day).days
                join_idx.append(max(idx, 0))                  # 음수(기존 입사) → 0
            else:
                join_idx.append(0)
            # ─ leave ─
            if nurse.resignation_date:
                delta = (nurse.resignation_date - first_day).days
                # Δ < 0 👉 이미 퇴사 → 이번 달엔 근무 X
                leave_idx.append(min(delta, roster_system.num_days - 1))
            else:
                leave_idx.append(roster_system.num_days - 1)


        # ───── 1. 변수 정의  x[n,d,s] ∈ {0,1} ──────────────────────────
        x: dict[tuple[int, int, int], cp_model.IntVar] = {}
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n] + 1):                   # 입사 전 날짜 skip
                for s in range(S):
                    x[n, d, s] = model.NewBoolVar(f'n{n}_d{d}_s{s}')

        def X(n: int, d: int, s: int):
            """존재하지 않는 인덱스 → 0 반환"""
            return x.get((n, d, s), 0)


        # ───── 2. 기본 제약 ────────────────────────────────────────────
        # (1) exactly‑one
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n] + 1):
                model.AddExactlyOne(X(n, d, s) for s in range(S))

        # (2) 일별 인원 충족
        for d in range(D):
            for shift_code, req in roster_system.config.daily_shift_requirements.items():
                s = roster_system.config.shift_types.index(shift_code)
                model.Add(
                    sum(X(n, d, s)
                        for n in range(N)
                        if join_idx[n] <= d <= leave_idx[n])       # ★
                    >= req
                )

        # ───── 3. 법규 하드 제약 ──────────────────────────────────────
        night = roster_system.config.shift_types.index('N')
        day   = roster_system.config.shift_types.index('D')
        eve   = roster_system.config.shift_types.index('E')
        off   = roster_system.config.shift_types.index('OFF')

        # (3‑1) 최대 연속 근무 K+1‑윈도우에 OFF ≥1
        K = roster_system.config.max_consecutive_work_days
        for n in range(N):
            for start_d in range(join_idx[n], leave_idx[n] - K + 1):
                model.Add(
                    sum(X(n, start_d + t, off)
                        for t in range(K + 1)
                        if start_d + t <= leave_idx[n]) >= 1
                )

        # (3‑2) E→D 금지
        if getattr(roster_system.config, 'banned_day_after_eve', False):
            for n in range(N):
                for d in range(max(1, join_idx[n]), leave_idx[n] + 1):
                    model.Add(X(n, d, day) + X(n, d - 1, eve) <= 1)

        # (3‑3) N→D 금지
        for n in range(N):
            for d in range(max(1, join_idx[n]), leave_idx[n] + 1):
                model.Add(X(n, d, day) + X(n, d - 1, night) <= 1)
                
        # (3‑7) Night 전담 간호사는 Day(D)‧Evening(E) 근무 금지
        for n, nurse in enumerate(roster_system.nurses):
            if nurse.is_night_nurse:                       # ★ night 전담 여부
                for d in range(join_idx[n], leave_idx[n] + 1):
                    # print(f'n: {n}, d: {d}, day: {X(n, d, day)}, eve: {X(n, d, eve)}')
                    model.Add(X(n, d, day) == 0)           # D 배정 불가
                    model.Add(X(n, d, eve) == 0)           # E 배정 불가

        # (3‑4) 최대 연속 야간
        L = roster_system.config.max_consecutive_nights
        for n in range(N):
            for start_d in range(join_idx[n], leave_idx[n] - L + 1):
                model.Add(
                    sum(X(n, start_d + t, night)
                        for t in range(L + 1)
                        if start_d + t <= leave_idx[n]) <= L
                )

        # (3‑5) 월 야간 근무 수
        max_N_month = roster_system.config.max_night_shifts_per_month
        for n in range(N):
            model.Add(
                sum(X(n, d, night) for d in range(join_idx[n], leave_idx[n] + 1))
                <= max_N_month
            )

        # (3‑6) N연속→OFF 법규
        if getattr(roster_system.config, 'two_offs_after_three_nig', False):
            for n in range(N):
                for d in range(join_idx[n] + 2, leave_idx[n] - 1):
                    threeN = X(n, d - 2, night) + X(n, d - 1, night) + X(n, d, night)
                    twoOff = X(n, d + 1, off)   + X(n, d + 2, off)
                    model.Add(twoOff >= 2 * (threeN - 2))

        if getattr(roster_system.config, 'two_offs_after_two_nig', False):
            for n in range(N):
                for d in range(join_idx[n] + 1, leave_idx[n] - 1):
                    twoN  = X(n, d - 1, night) + X(n, d, night)
                    twoOff = X(n, d + 1, off)  + X(n, d + 2, off)
                    model.Add(twoOff >= 2 * (twoN - 1))

        # ───── 4. 병원 내규 (Soft) ───────────────────────────────────
        penalty_vars = []

        # (4‑1) 경력자 부족 ────────────────────────────────────────
        exp_short_vars = []
        min_exp  = roster_system.config.min_experience_per_shift
        need_exp = roster_system.config.required_experienced_nurses

        for d in range(D):
            for shift_code in ('D', 'E', 'N'):
                s = roster_system.config.shift_types.index(shift_code)

                # d 가 각 간호사의 근무 기간 안에 있을 때만 카운트
                exp_assigned = sum(
                    X(n, d, s)
                    for n, nurse in enumerate(roster_system.nurses)
                    if (join_idx[n] <= d <= leave_idx[n])                # ★ NEW
                    and nurse.experience_years >= min_exp
                )

                shortage = model.NewIntVar(
                    0, need_exp, f'expShort_d{d}_s{shift_code}'
                )
                model.Add(shortage >= need_exp - exp_assigned)
                exp_short_vars.append(shortage)

        # (4‑2) 주 2OFF ───────────────────────────────────────────
        weekly_short = []
        if getattr(roster_system.config, 'enforce_two_offs_per_week', False):
            weeks = D // 7
            for n in range(N):
                for w in range(weeks):
                    w_start, w_end = w * 7, min(w * 7 + 7, D)

                    # 해당 주가 간호사의 근무 기간과 겹치지 않으면 skip
                    if w_end   <= join_idx[n] or w_start > leave_idx[n]:
                        continue

                    offs = sum(
                        X(n, d, off)
                        for d in range(max(w_start, join_idx[n]),
                                    min(w_end,   leave_idx[n] + 1))    # ★ NEW
                    )

                    short = model.NewIntVar(0, 2, f'weekOffShort_n{n}_w{w}')
                    model.Add(short >= 2 - offs)
                    weekly_short.append(short)

        # (4‑3) 야간 균등 ─────────────────────────────────────────
        night_dev = []
        if getattr(roster_system.config, 'even_nights', False):
            non_night = [
                i for i, nurse in enumerate(roster_system.nurses)
                if not nurse.is_night_nurse
            ]
            if len(non_night) > 1:
                total_N_req = sum(
                    roster_system.config.daily_shift_requirements.get('N', 2)
                    for d in range(D)
                )
                target = total_N_req // len(non_night)

                for n in non_night:
                    totN = sum(
                        X(n, d, night)
                        for d in range(join_idx[n], leave_idx[n] + 1)     # ★ NEW
                    )
                    pos = model.NewIntVar(0, D, f'Npos_n{n}')
                    neg = model.NewIntVar(0, D, f'Nneg_n{n}')
                    model.Add(pos - neg == totN - target)
                    night_dev.extend([pos, neg])
        # (4‑4) N → O → D/E 패턴 패널티  (‑100점)
        no_de_pattern = []            # 패널티 변수 모음

        for n in range(N):
            # 패턴 길이가 3일이므로 leave‑2 까지만 검사
            for d in range(join_idx[n], max(join_idx[n], leave_idx[n] - 1) - 1):
                # (i) N‑O‑D
                pat_NOD = model.NewIntVar(0, 1, f'NOD_n{n}_d{d}')
                model.Add(pat_NOD >=
                        X(n, d,     night) +     # N
                        X(n, d + 1, off)   +     # O
                        X(n, d + 2, day)   - 2)  # D
                no_de_pattern.append(pat_NOD)

                # (ii) N‑O‑E
                pat_NOE = model.NewIntVar(0, 1, f'NOE_n{n}_d{d}')
                model.Add(pat_NOE >=
                        X(n, d,     night) +     # N
                        X(n, d + 1, off)   +     # O
                        X(n, d + 2, eve)   - 2)  # E
                no_de_pattern.append(pat_NOE)
        # (4‑5) OFF 클러스터 – ‘O’가 양쪽 모두 근무(D/E/N)인 경우 패널티 100
        iso_off_vars = []

        for n in range(N):
            for d in range(join_idx[n], leave_idx[n] + 1):
                iso = model.NewIntVar(0, 1, f'isoOff_n{n}_d{d}')

                # iso == 1  ⇔  [d]가 OFF 이고 [d‑1], [d+1] 이 모두 OFF 가 아님
                model.Add(iso >= X(n, d, off) - X(n, d - 1, off) - X(n, d + 1, off))
                model.Add(iso <= X(n, d, off))           # OFF 가 아니면 iso = 0
                model.Add(iso <= 1 - X(n, d - 1, off))   # 앞날 OFF 면 iso = 0
                model.Add(iso <= 1 - X(n, d + 1, off))   # 뒷날 OFF 면 iso = 0


                iso_off_vars.append(iso)
        # ───── 5. 목적함수 ────────────────────────────────────────────
        obj = []

        # 선호도
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n] + 1):
                for s in range(S):
                    score = int(roster_system.preference_matrix[n, d, s] * 100)
                    obj.append(score * X(n, d, s))

        # 패널티
        obj.extend(-100 * v for v in exp_short_vars)
        obj.extend(-500 * v for v in weekly_short)
        obj.extend( -50 * v for v in night_dev)
        obj.extend(-100 * v for v in no_de_pattern)   # ★ 추가
        obj.extend(-100 * v for v in iso_off_vars)   # ★ 추가
        model.Maximize(sum(obj))

        # ───── 6. Solve ──────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers  = 8
        solver.parameters.log_search_progress = True

        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("❌ 해를 찾지 못했습니다.")
            return False
        # ───── 7. 결과 반영 ──────────────────────────────────────────
        roster_system.roster.fill(0)
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n] + 1):
                for s in range(S):
                    if solver.Value(X(n, d, s)):
                        roster_system.roster[n, d, s] = 1

        print(
            f"✅ 완료 – {time.time()-start_time:.1f}s, "
            f"obj {solver.ObjectiveValue():.0f}"
        )
        return True

        # # 변수 정의: x[nurse, day, shift] = 1 if nurse is assigned to shift on day
        # x = {}
        # for n_idx in range(len(roster_system.nurses)):
        #     for day in range(roster_system.num_days):
        #         for s_idx in range(roster_system.config.num_shifts):
        #             x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{s_idx}')

        # # ============ 기본 제약사항 ============
        
        # # 1. 각 간호사는 하루에 정확히 하나의 근무만 배정
        # for n_idx in range(len(roster_system.nurses)):
        #     for day in range(roster_system.num_days):
        #         model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(roster_system.config.num_shifts))

        # # 2. 일일 교대별 인원 요구사항 (하드 제약)
        # for day in range(roster_system.num_days):
        #     for shift, required in roster_system.config.daily_shift_requirements.items():
        #         s_idx = roster_system.config.shift_types.index(shift)
        #         model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(roster_system.nurses))) >= required)

        # # ============ 법규 제약사항 (Hard Constraints) ============
        
        # night_idx = roster_system.config.shift_types.index('N')
        # day_idx = roster_system.config.shift_types.index('D')
        # eve_idx = roster_system.config.shift_types.index('E')
        # off_idx = roster_system.config.shift_types.index('OFF')
        
        # # 3. 최대 연속 근무일 수 제한
        # max_work = roster_system.config.max_consecutive_work_days
        # for n_idx in range(len(roster_system.nurses)):
        #     for start_day in range(roster_system.num_days - max_work):
        #         # 연속된 (max_work + 1)일 중 적어도 1일은 반드시 휴무여야 함
        #         off_days_in_window = []
        #         for d in range(max_work + 1):
        #             if start_day + d < roster_system.num_days:
        #                 off_days_in_window.append(x[n_idx, start_day + d, off_idx])
                
        #         if off_days_in_window:
        #             model.Add(sum(off_days_in_window) >= 1)

        # # 4. E → D 근무 금지 (법규)
        # if hasattr(roster_system.config, 'banned_day_after_eve') and roster_system.config.banned_day_after_eve:
        #     for n_idx in range(len(roster_system.nurses)):
        #         for day in range(1, roster_system.num_days):
        #             model.Add(x[n_idx, day, day_idx] + x[n_idx, day-1, eve_idx] <= 1)

        # # 5. N → D 근무 금지 (항상 적용)
        # for n_idx in range(len(roster_system.nurses)):
        #     for day in range(1, roster_system.num_days):
        #         model.Add(x[n_idx, day, day_idx] + x[n_idx, day-1, night_idx] <= 1)

        # # 6. 최대 연속 야간 근무 제한
        # max_nights = roster_system.config.max_consecutive_nights
        # for n_idx in range(len(roster_system.nurses)):
        #     for day in range(roster_system.num_days - max_nights):
        #         model.Add(sum(x[n_idx, d, night_idx] for d in range(day, day + max_nights + 1) if d < roster_system.num_days) <= max_nights)

        # # 7. 월 최대 야간 근무 수 제한
        # for n_idx in range(len(roster_system.nurses)):
        #     model.Add(sum(x[n_idx, day, night_idx] for day in range(roster_system.num_days)) <= roster_system.config.max_night_shifts_per_month)

        # # 8. N 3회 후 OFF 2회 (법규)
        # if hasattr(roster_system.config, 'two_offs_after_three_nig') and roster_system.config.two_offs_after_three_nig:
        #     for n_idx in range(len(roster_system.nurses)):
        #         for day in range(2, roster_system.num_days - 2):
        #             # 3일 연속 N이면 다음 2일은 반드시 OFF
        #             three_nights = x[n_idx, day-2, night_idx] + x[n_idx, day-1, night_idx] + x[n_idx, day, night_idx]
        #             if day + 2 < roster_system.num_days:
        #                 two_offs = x[n_idx, day+1, off_idx] + x[n_idx, day+2, off_idx]
        #                 # 3일 연속 N(three_nights=3)이면 다음 2일 반드시 OFF(two_offs=2)
        #                 model.Add(two_offs >= 2 * (three_nights - 2))

        # # 9. N 2회 후 OFF 2회 (법규)
        # if hasattr(roster_system.config, 'two_offs_after_two_nig') and roster_system.config.two_offs_after_two_nig:
        #     for n_idx in range(len(roster_system.nurses)):
        #         for day in range(1, roster_system.num_days - 2):
        #             # 2일 연속 N이면 다음 2일은 반드시 OFF
        #             two_nights = x[n_idx, day-1, night_idx] + x[n_idx, day, night_idx]
        #             if day + 2 < roster_system.num_days:
        #                 two_offs = x[n_idx, day+1, off_idx] + x[n_idx, day+2, off_idx]
        #                 # 2일 연속 N(two_nights=2)이면 다음 2일 반드시 OFF(two_offs=2)
        #                 model.Add(two_offs >= 2 * (two_nights - 1))

        # # ============ 병원 내규 (Soft Constraints via Penalty) ============
        
        # penalty_terms = []
        
        # # 10. 경력 간호사 요구사항 (소프트)
        # exp_penalty_vars = []
        # for day in range(roster_system.num_days):
        #     for shift in ['D', 'E', 'N']:
        #         s_idx = roster_system.config.shift_types.index(shift)
        #         experienced_assigned = sum(
        #             x[n_idx, day, s_idx] 
        #             for n_idx, nurse in enumerate(roster_system.nurses)
        #             if nurse.experience_years >= roster_system.config.min_experience_per_shift
        #         )
        #         exp_shortage = model.NewIntVar(0, roster_system.config.required_experienced_nurses, f'exp_shortage_d{day}_s{shift}')
        #         model.Add(exp_shortage >= roster_system.config.required_experienced_nurses - experienced_assigned)
        #         exp_penalty_vars.append(exp_shortage)

        # # 11. 주 2회 이상 OFF (소프트)
        # if hasattr(roster_system.config, 'enforce_two_offs_per_week') and roster_system.config.enforce_two_offs_per_week:
        #     weekly_off_penalty_vars = []
        #     weeks = roster_system.num_days // 7
        #     for n_idx in range(len(roster_system.nurses)):
        #         for week in range(weeks):
        #             week_start = week * 7
        #             week_end = min(week_start + 7, roster_system.num_days)
        #             week_offs = sum(x[n_idx, day, off_idx] for day in range(week_start, week_end))
        #             off_shortage = model.NewIntVar(0, 2, f'week_off_shortage_n{n_idx}_w{week}')
        #             model.Add(off_shortage >= 2 - week_offs)
        #             weekly_off_penalty_vars.append(off_shortage)

        # # 12. N 개수 균등 배정 (소프트)
        # if hasattr(roster_system.config, 'even_nights') and roster_system.config.even_nights:
        #     night_penalty_vars = []
        #     # 야간전담 간호사 제외하고 균등 배정
        #     non_night_nurses = [n_idx for n_idx, nurse in enumerate(roster_system.nurses) if not nurse.is_night_nurse]
        #     if len(non_night_nurses) > 1:
        #         target_nights = sum(roster_system.config.daily_shift_requirements.get('N', 2) for _ in range(roster_system.num_days)) // len(non_night_nurses)
                
        #         for n_idx in non_night_nurses:
        #             total_nights = sum(x[n_idx, day, night_idx] for day in range(roster_system.num_days))
        #             night_deviation_pos = model.NewIntVar(0, roster_system.num_days, f'night_dev_pos_n{n_idx}')
        #             night_deviation_neg = model.NewIntVar(0, roster_system.num_days, f'night_dev_neg_n{n_idx}')
        #             model.Add(night_deviation_pos - night_deviation_neg == total_nights - target_nights)
        #             night_penalty_vars.extend([night_deviation_pos, night_deviation_neg])

        # # ============ 목적 함수 ============
        
        # objective_terms = []
        
        # # 선호도 만족
        # for n_idx in range(len(roster_system.nurses)):
        #     for day in range(roster_system.num_days):
        #         for s_idx in range(roster_system.config.num_shifts):
        #             pref_score = int(roster_system.preference_matrix[n_idx, day, s_idx] * 100)
        #             objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # # 소프트 제약 위반 패널티
        # for var in exp_penalty_vars:
        #     # print('\n\n\n\n\nvar', -100 * var, '\n\n\n\n\n')
        #     objective_terms.append(-100 * var)  # 경력 간호사 부족 패널티
            
        # if hasattr(roster_system.config, 'enforce_two_offs_per_week') and roster_system.config.enforce_two_offs_per_week:
        #     for var in weekly_off_penalty_vars:
        #         objective_terms.append(-500 * var)  # 주간 휴무 부족 패널티
        
        # if hasattr(roster_system.config, 'even_nights') and roster_system.config.even_nights:
        #     for var in night_penalty_vars:
        #         objective_terms.append(-50 * var)  # 야간 근무 불균등 패널티

        # model.Maximize(sum(objective_terms))

        # # ============ 솔버 실행 ============
        
        # solver = cp_model.CpSolver()
        # solver.parameters.max_time_in_seconds = time_limit_seconds
        # solver.parameters.log_search_progress = True
        # solver.parameters.num_search_workers = 8
        
        # status = solver.Solve(model)

        # if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        #     print(f"{self.logger_prefix} 최적화 완료: {time.time() - start_time:.2f}초 소요")
        #     print(f"목적값: {solver.ObjectiveValue()}")
            
        #     # 결과를 roster_system에 저장
        #     roster_system.roster.fill(0)
        #     for n_idx in range(len(roster_system.nurses)):
        #         for day in range(roster_system.num_days):
        #             for s_idx in range(roster_system.config.num_shifts):
        #                 if solver.Value(x[n_idx, day, s_idx]) == 1:
        #                     roster_system.roster[n_idx, day, s_idx] = 1
            
        #     return True
        # else:
        #     print(f"{self.logger_prefix} 해를 찾지 못했습니다. 상태: {status}")
        #     return False
    
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
                    # OFF를 O로 변환
                    if shift_id == 'OFF':
                        shift_id = 'O'
                    nurse_schedule.append(shift_id)
                else:
                    nurse_schedule.append('-')  # 기본값
            
            result[nurse.db_id] = nurse_schedule
        
        return result
    
    def _print_optimization_results(self, roster_system: RosterSystem):
        """최적화 결과 출력"""
        print(f"\n{self.logger_prefix} 최적화 결과:")
        
        # 위반사항 확인
        violations = roster_system._find_violations()
        if violations:
            print(f"  - {len(violations)}개의 제약 위반 사항 발견")
            for v in violations[:5]:  # 처음 5개만 표시
                print(f"    • {v}")
            if len(violations) > 5:
                print(f"    ... 및 {len(violations) - 5}개 더")
        else:
            print("  - 모든 제약 조건 충족!")
        
        # 선호도 만족도 계산
        try:
            off_satisfaction = roster_system._calculate_off_preference_satisfaction()
            print(f"  - 선호 휴무일 만족도: {off_satisfaction:.2f}%")
            
            shift_satisfaction = roster_system._calculate_shift_preference_satisfaction()
            print(f"  - 근무 유형 선호도 만족도: {shift_satisfaction:.2f}%")
            
            if hasattr(roster_system, 'pair_matrix'):
                pair_satisfaction = roster_system._calculate_pair_preference_satisfaction()
                print(f"  - 페어링 선호도 만족도: {pair_satisfaction['overall']:.2f}%")
        except Exception as e:
            print(f"  - 만족도 계산 중 오류: {e}")


# 전역 엔진 인스턴스
cp_sat_engine = CPSATBasicEngine()


def generate_roster_cp_sat(nurses_data, prefs_data, config_data, year, month, time_limit_seconds=60):
    """
    기존 roster_engine.generate_roster 함수와 호환되는 인터페이스
    
    Args:
        nurses_data: DB에서 가져온 간호사 데이터 리스트  
        prefs_data: DB에서 가져온 선호도 데이터 리스트
        config_data: DB에서 가져온 설정 데이터
        year: 근무표 년도
        month: 근무표 월
        time_limit_seconds: CP-SAT 최적화 시간 제한
        
    Returns:
        Dict[nurse_id, List[shift]]: 간호사별 일일 근무 배정
    """
    return cp_sat_engine.generate_roster(
        nurses_data, prefs_data, config_data, year, month, time_limit_seconds
    ) 