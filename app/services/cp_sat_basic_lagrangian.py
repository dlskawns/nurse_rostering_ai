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
    
    def create_shift_manage_from_db(self, shift_manage_data: List[dict]):
        shift_manage = []
        for row in shift_manage_data:
            shift_dict = {
                'office_id': row['office_id'],
                'group_id': row['group_id'],
                'nurse_class': row['nurse_class'],
                'shift_slot': row['shift_slot'],
                'main_code': row['main_code'],
                'codes': row['codes'],
            }
            shift_manage.append(ShiftManage(**shift_dict))
        return shift_manage

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
        grouped: List[dict],
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
            base = ['D', 'E', 'N', 'OFF']
            cfg  = roster_system.config
            if any(s not in cfg.shift_types for s in base):
                cfg.shift_types = list(dict.fromkeys([*cfg.shift_types, *base]))
            # 고정된 셀 정보 처리
            fixed_cells = config_data.get('fixed_cells', [])
            if fixed_cells:
                print(f"{self.logger_prefix} 고정된 셀 {len(fixed_cells)}개 처리 중...")
                roster_system.fixed_cells = fixed_cells
                for fixed_cell in fixed_cells:
                    print(f"{self.logger_prefix} 고정 셀: 간호사 {fixed_cell['nurse_index']}, 날짜 {fixed_cell['day_index']+1}, 근무 {fixed_cell['shift']}")
        
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
            success = self._optimize_with_enhanced_constraints(roster_system, time_limit_seconds, nurses, grouped)
            
            if not success:
                print(f"{self.logger_prefix} 개선된 제약사항으로 실패, 기본 알고리즘으로 폴백...")
                roster_system.optimize_roster_with_cp_sat_v2(time_limit_seconds=time_limit_seconds)
        
        # 10. 결과 변환
        with Timer("결과 변환"):
            result = self._convert_result_to_db_format(roster_system, nurses)
        
        # 11. 최적화 결과 출력 및 만족도 데이터 수집
        satisfaction_data = self._print_optimization_results(roster_system)
        
        # 12. 대시보드 분석 데이터 저장 (스케줄 생성 후)
        try:
            from services.dashboard_service import save_roster_analytics
            # 스케줄 ID는 roster_create_service에서 생성된 후 전달받아야 함
            # 여기서는 임시로 None을 전달하고, 실제 저장은 roster_create_service에서 처리
            print(f"{self.logger_prefix} 대시보드 분석 데이터 저장 준비 완료")
        except ImportError:
            print(f"{self.logger_prefix} 대시보드 서비스를 찾을 수 없습니다.")
        
        print(f"{self.logger_prefix} 근무표 생성 완료")
        return {
            "roster": result,
            "satisfaction_data": satisfaction_data,
            "roster_system": roster_system
        }


    # ----------------- _optimize_with_enhanced_constraints -----------------

    def _optimize_with_enhanced_constraints(
            self,
            roster_system: RosterSystem,
            time_limit_seconds: int,
            nurses,
            grouped=None
    ) -> bool:
        """
        라그랑지안 분해 + 서브그래디언트 최적화.
        ▸ '일별 교대 인원 충족' 제약만 λ 로 이완해 Coupling 을 제거
        ▸ 간호사별 서브문제(전체 법규·내규 만족) → 병렬 CP-SAT
        ▸ λ를 갱신하며 1차 라그랑지 상계(Upper Bound)와 스케줄(Primal) 동시 개선
        """
        from ortools.sat.python import cp_model
        import time, math, itertools, multiprocessing as mp

        start = time.time()
        N, D = len(roster_system.nurses), roster_system.num_days
        S_types = roster_system.config.shift_types            # ['D','E','N','OFF']
        S = len(S_types)
        # req_vec = [roster_system.config.daily_shift_requirements.get(sh, 0)
        #     for sh in S_types]                   # ← 수정 ①
        # req = roster_system.config.daily_shift_requirements   # {'D':3, ...}

        # ── 0. 인덱스 준비 ─────────────────────────────────────
        idx = {s: S_types.index(s) for s in ('D','E','N','OFF')}
        # 입사/퇴사 idx, 고정 셀, 경력 여부 … 기존 코드 재사용
        join, leave, fixed_assign, fixed_cnt = _precompute_static_info(roster_system, grouped)

        # ── 1. 라그랑지 승수 초기화 ────────────────────────────
        λ = [[0.0]*S for _ in range(D)]        # λ[d][s]
        best_feasible = None                   # (obj, roster ndarray)
        UB = float('inf')                      # 최적 upper bound
        max_iter = 30
        α0 = 5.0                               # 초기 스텝
        req_map = roster_system.config.daily_shift_requirements      # 딱 한 줄

        req_vec = [req_map.get(sh, 0) for sh in S_types]             # ← 루프 밖

        for k in range(1, max_iter+1):
            # ── 2. 서브문제 병렬 풀기 ──────────────────────
            with mp.Pool(processes=min(8, mp.cpu_count())) as pool:
                args = [(n_idx, roster_system, λ, join, leave,
                        fixed_assign.get(n_idx, {}), time_limit_seconds//2)
                        for n_idx in range(N)]
                sub_results = pool.map(_solve_single_nurse, args)

            # sub_results → (obj_i, assign_i[np.array [D,S]])
            if any(r is None for r in sub_results):
                print("❌ sub-solver failure, fallback")
                return False

            # ── 3. 라그랑지 목적 / 서브그래디언트 계산 ─────
            total_obj = 0.0
            # 1) 교대별 요구를 list 로 먼저 만든 뒤

            # 2) day × shift 행렬 생성
            coverage = [[-req_vec[s] for s in range(S)] for _ in range(D)] # 요구-할당 (음수 == 부족)
            roster_system.roster.fill(0)
            for n_idx, (obj_i, mat_i) in enumerate(sub_results):
                total_obj += obj_i
                roster_system.roster[n_idx] = mat_i
                for d in range(D):
                    for s in range(S):
                        if mat_i[d, s]:
                            coverage[d][s] += 1

            # 라그랑지안 값 = Σ 서브 obj + Σ λ·(req-할당)
            lagrangian = total_obj + sum(
                λ[d][s] * (-coverage[d][s])           # req-할당 = -coverage
                for d in range(D) for s in range(S)
            )

            # ======= Primal-Feasibility 체크 =========
            shortages = (-v for row in coverage for v in row if v < 0)
            deficit   = max(shortages, default=0)   # 가장 큰 부족
            if deficit <= 0:                          # 모든 교대 요구 충족 ⇒ feasible
                primal_obj = _eval_full_objective(roster_system)         # 선호도-패널티 포함
                if primal_obj < UB:
                    UB, best_feasible = primal_obj, roster_system.roster.copy()
                if time.time() - start > time_limit_seconds*0.9:
                    break                             # 충분히 좋으면 조기 종료

            # ── 4. λ 업데이트 (서브그래디언트) ─────────────
            step = α0 / math.sqrt(k)
            for d in range(D):
                for s in range(S):
                    λ[d][s] += step * coverage[d][s]     # λ ← λ + α·(할당-요구)
                    λ[d][s] = max(0.0, λ[d][s])          # 양수 유지(dual feasibility)

            # 시간 한계 체크
            if time.time() - start > time_limit_seconds*0.8:
                break

        # ── 5. 결과 반영 or 폴백 ──────────────────────────
        if best_feasible is not None:
            roster_system.roster[:] = best_feasible
            print(f"✅ Lagrangian finished in {time.time()-start:.1f}s UB={UB:.1f}")
            return True
        else:
            print("⚠️ Lagrangian could not reach feasibility → fallback")
            return False


    
    # def _optimize_with_enhanced_constraints(self, roster_system: RosterSystem, time_limit_seconds: int, nurses, grouped = None) -> bool:
    #     """법규 제약사항과 병원 내규를 포함한 CP-SAT 최적화"""
    #     try:
    #         from ortools.sat.python import cp_model
    #     except ImportError:
    #         print("OR-Tools를 찾을 수 없습니다.")
    #         return False


    #     """입사일·법규·내규를 모두 반영한 CP‑SAT 최적화"""
    #     from datetime import date
    #     from ortools.sat.python import cp_model
    #     import time
    #     start_time = time.time()
    #     model = cp_model.CpModel()
    #     # ───── 0. 사전 계산 ─────────────────────────────────────────────
    #     N = len(roster_system.nurses)
    #     D = roster_system.num_days
    #     S = roster_system.config.num_shifts
    #     print('roster_system.config', roster_system.config)
    #     first_day: date = roster_system.target_month          # 해당 월 1일
    #     join_idx:  list[int] = []    # 입사일부터 근무
    #     leave_idx: list[int] = []    # 퇴사전날까지 근무
    #     for nurse in roster_system.nurses:
    #         if nurse.joining_date:
    #             idx = (nurse.joining_date - first_day).days
    #             join_idx.append(max(idx, 0))                  # 음수(기존 입사) → 0
    #         else:
    #             join_idx.append(0)
    #         # ─ leave ─
    #         if nurse.resignation_date:
    #             delta = (nurse.resignation_date - first_day).days
    #             # Δ < 0 👉 이미 퇴사 → 이번 달엔 근무 X
    #             leave_idx.append(min(delta, roster_system.num_days - 1))
    #         else:
    #             leave_idx.append(roster_system.num_days - 1)

    #         # print('\n\n\n\n\njoin_idx', join_idx, '\n\n\n\n\n')
    #     # print('\n\n\n\n\nshift_manage_', shift_manage_data  , '\n\n\n\n\n')

    #     # 0‑a. shift code → main_code 매핑 준비
    #     shift_code_to_main = {}
    #     if len(grouped) > 0:
    #         for row in grouped:
    #             main_code = row.get('main_code')
    #             for code in row.get('codes', []):
    #                 shift_code_to_main[code] = main_code
    #     print('shift_code_to_main', shift_code_to_main)
    #     # ───── 0‑b. 수간호사 고정 배정 ─────────────────────────────── 🔄
    #     fixed = {}                                     # (n,d) → s_idx or str
    #     fixed_cnt = [[0]*S for _ in range(D)]        # 일별‑교대별 사전배정 수
        
    #     if hasattr(roster_system, 'fixed_cells') and roster_system.fixed_cells:
    #         print('안재낌')
    #         for fixed_cell in roster_system.fixed_cells:
    #             n_id = fixed_cell['nurse_index']
    #             d_idx = fixed_cell['day_index']
    #             s_code = fixed_cell['shift']
    #             # main_code 환산
    #             main_code = shift_code_to_main.get(s_code, s_code)
    #             print('main_code', main_code)
    #             if main_code in roster_system.config.shift_types:
    #                 s_idx = roster_system.config.shift_types.index(main_code)
    #                 fixed[(n_id, d_idx)] = s_idx
    #                 fixed_cnt[d_idx][s_idx] += 1
    #                 print(f"고정 셀 추가: 간호사 {n_id}, 날짜 {d_idx+1}, 근무 {s_code}→{main_code}")
    #                 print('what')
    #             else:
    #                 print('이번엔 여기왔다, 마지막 확인이다')
    #                 s_idx = roster_system.config.shift_types.index(main_code)
    #                 # shift_types에 없는 근무는 그대로 schedule에 남기고, 알고리즘에서 제외
    #                 print('이번엔 여기왔다, 마지막 확인이다')
    #                 fixed[(n_id, d_idx)] = s_code
    #                 fixed_cnt[d_idx][s_idx] += 1
    #                 print(f"고정 셀(shift_types 미포함) 추가: 간호사 {n_id}, 날짜 {d_idx+1}, 근무 {s_code}")

    #     # ───── 1. 변수 정의  x[n,d,s] ∈ {0,1} ──────────────────────────
    #     x: dict[tuple[int, int, int], cp_model.IntVar] = {}
    #     for n in range(N):
    #         for d in range(join_idx[n], leave_idx[n] + 1):                   # 입사 전 날짜 skip
    #             for s in range(S):
    #                 x[n, d, s] = model.NewBoolVar(f'n{n}_d{d}_s{s}')
 
    #     def X(n: int, d: int, s: int):
    #         """존재하지 않는 인덱스 → 0 반환"""
    #         return x.get((n, d, s), 0)

    #     # ───── 2‑A. 고정 배정 반영 ───────────────────────────────── 🔄
    #     for (n, d), val in fixed.items():
    #         if isinstance(val, int):
    #             # shift_types에 있는 경우만 제약
    #             model.Add(X(n, d, val) == 1)
    #             for s in range(S):
    #                 if s != val:
    #                     model.Add(X(n, d, s) == 0)
    #         # else: shift_types에 없는 근무는 제약 없이 schedule에만 반영

    #     # ───── 2‑B. exactly‑one 제약 수정 ─────────────────────────── 🔄
    #     for n in range(N):
    #         for d in range(join_idx[n], leave_idx[n] + 1):
    #             if (n, d) in fixed:
    #                 continue
    #             model.AddExactlyOne(X(n, d, s) for s in range(S))

    #     # ───── 2‑C. 일별 인원 충족 제약 수정 ─────────────────────── 🔄
    #     for d in range(D):
    #         for shift_code, req in roster_system.config.daily_shift_requirements.items():
    #             main_code = shift_code
    #             s = roster_system.config.shift_types.index(main_code)
    #             still_needed = req - fixed_cnt[d][s]              # 고정분 제외한 잔여 인원
    #             if still_needed <= 0:                             # 이미 충족
    #                 continue
    #             model.Add(
    #                 sum(X(n, d, s)
    #                     for n in range(N)
    #                     if (join_idx[n] <= d <= leave_idx[n]) and (n, d) not in fixed)
    #                 >= still_needed
    #             )

    #     # ───── 3. 법규 하드 제약 ──────────────────────────────────────
    #     night = roster_system.config.shift_types.index('N')
    #     day   = roster_system.config.shift_types.index('D')
    #     eve   = roster_system.config.shift_types.index('E')
    #     off   = roster_system.config.shift_types.index('OFF')

    #     # (3‑1) 최대 연속 근무 K+1‑윈도우에 OFF ≥1
    #     K = roster_system.config.max_consecutive_work_days
    #     for n in range(N):
    #         for start_d in range(join_idx[n], leave_idx[n] - K + 1):
    #             model.Add(
    #                 sum(X(n, start_d + t, off)
    #                     for t in range(K + 1)
    #                     if start_d + t <= leave_idx[n]) >= 1
    #             )

    #     # (3‑2) E→D 금지
    #     if getattr(roster_system.config, 'banned_day_after_eve', False):
    #         for n in range(N):
    #             for d in range(max(1, join_idx[n]), leave_idx[n] + 1):
    #                 model.Add(X(n, d, day) + X(n, d - 1, eve) <= 1)

    #     # (3‑3) N→D 금지
    #     for n in range(N):
    #         for d in range(max(1, join_idx[n]), leave_idx[n] + 1):
    #             model.Add(X(n, d, day) + X(n, d - 1, night) <= 1)
                
    #     # (3‑7) Night 전담 간호사는 Day(D)‧Evening(E) 근무 금지
    #     for n, nurse in enumerate(roster_system.nurses):
    #         if nurse.is_night_nurse:                       # ★ night 전담 여부
    #             for d in range(join_idx[n], leave_idx[n] + 1):
    #                 # print(f'n: {n}, d: {d}, day: {X(n, d, day)}, eve: {X(n, d, eve)}')
    #                 model.Add(X(n, d, day) == 0)           # D 배정 불가
    #                 model.Add(X(n, d, eve) == 0)           # E 배정 불가

    #     # (3‑4) 최대 연속 야간
    #     if getattr(roster_system.config, 'three_seq_nig', False):
    #         L = roster_system.config.max_consecutive_nights
    #     else:
    #         L = roster_system.config.max_consecutive_nights+1
    #     for n in range(N):
    #         for start_d in range(join_idx[n], leave_idx[n] - L + 1):
    #             model.Add(
    #                 sum(X(n, start_d + t, night)
    #                     for t in range(L + 1)
    #                     if start_d + t <= leave_idx[n]) <= L
    #             )

    #     # (3‑5) 월 야간 근무 수
    #     max_N_month = roster_system.config.max_night_shifts_per_month
    #     for n in range(N):
    #         model.Add(
    #             sum(X(n, d, night) for d in range(join_idx[n], leave_idx[n] + 1))
    #             <= max_N_month
    #         )

    #     # (3‑6) N연속→OFF 법규
    #     if getattr(roster_system.config, 'two_offs_after_three_nig', False):
    #         for n in range(N):
    #             for d in range(join_idx[n] + 2, leave_idx[n] - 1):
    #                 threeN = X(n, d - 2, night) + X(n, d - 1, night) + X(n, d, night)
    #                 twoOff = X(n, d + 1, off)   + X(n, d + 2, off)
    #                 model.Add(twoOff >= 2 * (threeN - 2))

    #     if getattr(roster_system.config, 'two_offs_after_two_nig', False):
    #         for n in range(N):
    #             for d in range(join_idx[n] + 1, leave_idx[n] - 1):
    #                 twoN  = X(n, d - 1, night) + X(n, d, night)
    #                 twoOff = X(n, d + 1, off)  + X(n, d + 2, off)
    #                 model.Add(twoOff >= 2 * (twoN - 1))

    #     # ───── 4. 병원 내규 (Soft) ───────────────────────────────────
    #     penalty_vars = []

    #     # (4‑1) 경력자 부족 ────────────────────────────────────────
    #     exp_short_vars = []
    #     min_exp  = roster_system.config.min_experience_per_shift
    #     need_exp = roster_system.config.required_experienced_nurses

    #     for d in range(D):
    #         for shift_code in ('D', 'E', 'N'):
    #             s = roster_system.config.shift_types.index(shift_code)

    #             # d 가 각 간호사의 근무 기간 안에 있을 때만 카운트
    #             exp_assigned = sum(
    #                 X(n, d, s)
    #                 for n, nurse in enumerate(roster_system.nurses)
    #                 if (join_idx[n] <= d <= leave_idx[n])                # ★ NEW
    #                 and nurse.experience_years >= min_exp
    #             )

    #             shortage = model.NewIntVar(
    #                 0, need_exp, f'expShort_d{d}_s{shift_code}'
    #             )
    #             model.Add(shortage >= need_exp - exp_assigned)
    #             exp_short_vars.append(shortage)

    #     # (4‑2) 주 2OFF ───────────────────────────────────────────
    #     weekly_short = []
    #     if getattr(roster_system.config, 'enforce_two_offs_per_week', False):
    #         weeks = D // 7
    #         for n in range(N):
    #             for w in range(weeks):
    #                 w_start, w_end = w * 7, min(w * 7 + 7, D)

    #                 # 해당 주가 간호사의 근무 기간과 겹치지 않으면 skip
    #                 if w_end   <= join_idx[n] or w_start > leave_idx[n]:
    #                     continue

    #                 offs = sum(
    #                     X(n, d, off)
    #                     for d in range(max(w_start, join_idx[n]),
    #                                 min(w_end,   leave_idx[n] + 1))    # ★ NEW
    #                 )

    #                 short = model.NewIntVar(0, 2, f'weekOffShort_n{n}_w{w}')
    #                 model.Add(short >= 2 - offs)
    #                 weekly_short.append(short)

    #     # (4‑3) 야간 균등 ─────────────────────────────────────────
    #     night_dev = []
    #     if getattr(roster_system.config, 'even_nights', False):
    #         non_night = [
    #             i for i, nurse in enumerate(roster_system.nurses)
    #             if not nurse.is_night_nurse
    #         ]
    #         if len(non_night) > 1:
    #             total_N_req = sum(
    #                 roster_system.config.daily_shift_requirements.get('N', 2)
    #                 for d in range(D)
    #             )
    #             target = total_N_req // len(non_night)

    #             for n in non_night:
    #                 totN = sum(
    #                     X(n, d, night)
    #                     for d in range(join_idx[n], leave_idx[n] + 1)     # ★ NEW
    #                 )
    #                 pos = model.NewIntVar(0, D, f'Npos_n{n}')
    #                 neg = model.NewIntVar(0, D, f'Nneg_n{n}')
    #                 model.Add(pos - neg == totN - target)
    #                 night_dev.extend([pos, neg])
    #     # (4‑4) N → O → D/E 패턴 패널티  (‑100점)
    #     no_de_pattern = []            # 패널티 변수 모음

    #     for n in range(N):
    #         # 패턴 길이가 3일이므로 leave‑2 까지만 검사
    #         for d in range(join_idx[n], max(join_idx[n], leave_idx[n] - 1) - 1):
    #             # (i) N‑O‑D
    #             pat_NOD = model.NewIntVar(0, 1, f'NOD_n{n}_d{d}')
    #             model.Add(pat_NOD >=
    #                     X(n, d,     night) +     # N
    #                     X(n, d + 1, off)   +     # O
    #                     X(n, d + 2, day)   - 2)  # D
    #             no_de_pattern.append(pat_NOD)

    #             # (ii) N‑O‑E
    #             pat_NOE = model.NewIntVar(0, 1, f'NOE_n{n}_d{d}')
    #             model.Add(pat_NOE >=
    #                     X(n, d,     night) +     # N
    #                     X(n, d + 1, off)   +     # O
    #                     X(n, d + 2, eve)   - 2)  # E
    #             no_de_pattern.append(pat_NOE)
    #     # (4‑5) OFF 클러스터 – ‘O’가 양쪽 모두 근무(D/E/N)인 경우 패널티 100
    #     iso_off_vars = []

    #     for n in range(N):
    #         for d in range(join_idx[n], leave_idx[n] + 1):
    #             iso = model.NewIntVar(0, 1, f'isoOff_n{n}_d{d}')

    #             # iso == 1  ⇔  [d]가 OFF 이고 [d‑1], [d+1] 이 모두 OFF 가 아님
    #             model.Add(iso >= X(n, d, off) - X(n, d - 1, off) - X(n, d + 1, off))
    #             model.Add(iso <= X(n, d, off))           # OFF 가 아니면 iso = 0
    #             model.Add(iso <= 1 - X(n, d - 1, off))   # 앞날 OFF 면 iso = 0
    #             model.Add(iso <= 1 - X(n, d + 1, off))   # 뒷날 OFF 면 iso = 0


    #             iso_off_vars.append(iso)
    #     # ───── 5. 목적함수 ────────────────────────────────────────────
    #     obj = []

    #     # 선호도
    #     for n in range(N):
    #         for d in range(join_idx[n], leave_idx[n] + 1):
    #             for s in range(S):
    #                 score = int(roster_system.preference_matrix[n, d, s] * 100)
    #                 obj.append(score * X(n, d, s))

    #     # 패널티
    #     obj.extend(-100 * v for v in exp_short_vars)
    #     obj.extend(-500 * v for v in weekly_short)
    #     obj.extend( -50 * v for v in night_dev)
    #     obj.extend(-100 * v for v in no_de_pattern)   # ★ 추가
    #     obj.extend(-100 * v for v in iso_off_vars)   # ★ 추가
    #     model.Maximize(sum(obj))

    #     # ───── 6. Solve ──────────────────────────────────────────────
    #     solver = cp_model.CpSolver()
    #     solver.parameters.max_time_in_seconds = time_limit_seconds
    #     solver.parameters.num_search_workers  = 2
    #     solver.parameters.log_search_progress = True
    #     solver.parameters.relative_gap_limit = 0.2
    #     status = solver.Solve(model)
    #     if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    #         print("❌ 해를 찾지 못했습니다.")
    #         return False
    #     # ───── 7. 결과 반영 ──────────────────────────────────────────
    #     roster_system.roster.fill(0)
    #     for n in range(N):
    #         for d in range(join_idx[n], leave_idx[n] + 1):
    #             for s in range(S):
    #                 if solver.Value(X(n, d, s)):
    #                     roster_system.roster[n, d, s] = 1

    #     print(
    #         f"✅ 완료 – {time.time()-start_time:.1f}s, "
    #         f"obj {solver.ObjectiveValue():.0f}"
    #     )
    #     return True
    
    def _convert_result_to_db_format(self, roster_system: RosterSystem, nurses: List[Nurse]) -> Dict[str, List[str]]:
        """RosterSystem 결과를 DB 형식으로 변환 (고정된 셀은 원래 값으로 반환)"""
        result = {}
        shift_map = {i: s for i, s in enumerate(roster_system.config.shift_types)}
        fixed = getattr(roster_system, 'fixed_cells', None)
        fixed_lookup = {}
        if fixed:
            for cell in fixed:
                fixed_lookup[(cell['nurse_index'], cell['day_index'])] = cell['shift']
        for n_idx, nurse in enumerate(nurses):
            nurse_schedule = []
            for day_idx in range(roster_system.num_days):
                # 고정된 셀은 원래 값으로 반환
                if (n_idx, day_idx) in fixed_lookup:
                    nurse_schedule.append(fixed_lookup[(n_idx, day_idx)])
                    continue
                shift_vector = roster_system.roster[n_idx, day_idx]
                shift_idx = np.where(shift_vector == 1)[0]
                if len(shift_idx) > 0:
                    shift_id = shift_map[shift_idx[0]]
                    if shift_id == 'OFF':
                        shift_id = 'O'
                    nurse_schedule.append(shift_id)
                else:
                    nurse_schedule.append('-')
            result[nurse.db_id] = nurse_schedule
        return result
    
    def _print_optimization_results(self, roster_system: RosterSystem):
        """최적화 결과 출력 및 만족도 데이터 반환"""
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
        
        # 만족도 데이터 수집
        satisfaction_data = {
            "off_satisfaction": 0.0,
            "shift_satisfaction": 0.0,
            "pair_satisfaction": 0.0,
            "individual_satisfaction": {},
            "detailed_analysis": {}
        }
        
        # 선호도 만족도 계산
        try:
            off_satisfaction = roster_system._calculate_off_preference_satisfaction()
            satisfaction_data["off_satisfaction"] = off_satisfaction
            print(f"  - 선호 휴무일 만족도: {off_satisfaction:.2f}%")
            
            shift_satisfaction = roster_system._calculate_shift_preference_satisfaction()
            satisfaction_data["shift_satisfaction"] = shift_satisfaction
            print(f"  - 근무 유형 선호도 만족도: {shift_satisfaction:.2f}%")
            
            if hasattr(roster_system, 'pair_matrix'):
                pair_satisfaction = roster_system._calculate_pair_preference_satisfaction()
                satisfaction_data["pair_satisfaction"] = pair_satisfaction.get('overall', 0.0)
                print(f"  - 페어링 선호도 만족도: {pair_satisfaction.get('overall', 0.0):.2f}%")
            
            # 개인별 만족도 계산
            individual_satisfaction = roster_system.calculate_individual_satisfaction()
            satisfaction_data["individual_satisfaction"] = individual_satisfaction
            
            # 상세 요청 분석
            detailed_analysis = roster_system.calculate_detailed_request_analysis()
            satisfaction_data["detailed_analysis"] = detailed_analysis
            
        except Exception as e:
            print(f"  - 만족도 계산 중 오류: {e}")
        
        return satisfaction_data

# ================== Helper 함수 ==========================

def _precompute_static_info(roster_system, grouped):
    """
    • join / leave index
    • fixed cells per nurse
    • day×shift 선배정 카운트
    """
    N, D = len(roster_system.nurses), roster_system.num_days
    S = roster_system.config.num_shifts
    join, leave = [], []
    for nurse in roster_system.nurses:
        t0 = max(0, (nurse.joining_date - roster_system.target_month).days) if nurse.joining_date else 0
        t1 = min(D-1, (nurse.resignation_date - roster_system.target_month).days) if nurse.resignation_date else D-1
        join.append(t0);  leave.append(t1)

    fixed_assign = {n: {} for n in range(N)}   # {n_idx:{day:shift_idx}}
    fixed_cnt = [[0]*S for _ in range(D)]
    if roster_system.fixed_cells:
        code2main = {c: r['main_code'] for r in grouped for c in r['codes']} if grouped else {}
        for c in roster_system.fixed_cells:
            s_main = code2main.get(c['shift'], c['shift'])
            s_idx  = roster_system.config.shift_types.index(s_main)
            fixed_assign[c['nurse_index']][c['day_index']] = s_idx
            fixed_cnt[c['day_index']][s_idx] += 1
    return join, leave, fixed_assign, fixed_cnt


def _solve_single_nurse(args):
    """
    1 명의 간호사 서브문제 (Hard 제약 **전부** 포함).
    반환 → (dual_obj_i, mat_i[D,S](0/1))
    """
    (n_idx, roster_system, λ, join, leave, fixed_cells_n, tl) = args
    from ortools.sat.python import cp_model
    nurse = roster_system.nurses[n_idx]
    D, S = roster_system.num_days, roster_system.config.num_shifts
    T0, T1 = join[n_idx], leave[n_idx]

    m = cp_model.CpModel()
    X = {(d,s): m.NewBoolVar(f"x_{d}_{s}") for d in range(T0,T1+1) for s in range(S)}

    off = roster_system.config.shift_types.index('OFF')
    day, eve, night = (roster_system.config.shift_types.index(c) for c in ('D','E','N'))

    # ── ① 고정 배정 ──────────────────
    for d,s in fixed_cells_n.items():
        m.Add(X[d,s] == 1)
        for s2 in range(S):
            if s2!=s: m.Add(X[d,s2]==0)

    # ── ② 하루 1 shift (고정 제외) ────
    for d in range(T0,T1+1):
        if d in fixed_cells_n: continue
        m.AddExactlyOne(X[d,s] for s in range(S))

    # ── ③ 법규 하드 제약 (Night→Day, E→D, max-work, max-night …) ─
    _add_hard_constraints_one_nurse(m, X, roster_system, nurse, T0, T1, day, eve, night, off)

    # ── ④ 목적 (선호도 + 내규패널티 + λ 항) ─────────────────────
    obj = []
    P = roster_system.preference_matrix
    for d in range(T0,T1+1):
        for s in range(S):
            # 선호 점수
            obj.append(int(P[n_idx,d,s]*100) * X[d,s])
            # 라그랑지 λ 항 :  +λ[d][s] * X  (주의 λ는 day-shift coupling)
            obj.append(int(λ[d][s]*100) * X[d,s])

    # 내규 Soft 패널티 : 경력, 주2OFF … (전역-또는 간략 local 계수로 근사)
    _add_soft_penalties_one_nurse(m, X, roster_system, nurse, T0, T1, obj, off, night)

    m.Maximize(sum(obj))          # dual 최대화

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tl
    if nurse.is_night_nurse:       # 보통 night-전담 모델은 작아서 싱글스레드가 낫다
        solver.parameters.num_search_workers = 1
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    mat = np.zeros((D, roster_system.config.num_shifts), dtype=int)
    for d in range(T0,T1+1):
        for s in range(S):
            if solver.Value(X[d,s]): mat[d,s]=1
    return solver.ObjectiveValue(), mat


# === Hard / Soft 제약을 하나의 간호사 스코프로 추가하는 Helper ===
def _add_hard_constraints_one_nurse(m, X, rs, nurse, T0, T1, day, eve, night, off):
    """
    기존 엔진에서 간호사-레벨 Hard 제약을 **모두** 그대로 복사.
    """
    cfg = rs.config
    # Night→Day / E→D
    for d in range(T0+1, T1+1):
        m.Add(X[d, day] + X[d-1, night] <= 1)
        if cfg.banned_day_after_eve:
            m.Add(X[d, day] + X[d-1, eve] <= 1)
    # Night-전담
    if nurse.is_night_nurse:
        for d in range(T0,T1+1):
            m.Add(X[d, day]==0); m.Add(X[d, eve]==0)

    # 최대 연속 N, 최대 연속 근무
    L = cfg.max_consecutive_nights
    K = cfg.max_consecutive_work_days
    for d0 in range(T0, T1-L):
        m.Add(sum(X[d0+t, night] for t in range(L+1)) <= L)
    for d0 in range(T0, T1-K):
        m.Add(sum(1 - X[d0+t, off] for t in range(K+1)) <= K)  # OFF≥1 표현

    # 월 N 제한
    m.Add(sum(X[d, night] for d in range(T0,T1+1)) <= cfg.max_night_shifts_per_month)

    # N 3→2OFF, N 2→2OFF
    if cfg.two_offs_after_three_nig:
        for d in range(T0+2, T1-1):
            m.Add(sum(X[d-t,night] for t in (0,1,2)) - 2 <=
                X[d+1,off] + X[d+2,off])
    if cfg.two_offs_after_two_nig:
        for d in range(T0+1, T1-1):
            m.Add(sum(X[d-t,night] for t in (0,1)) - 1 <=
                X[d+1,off] + X[d+2,off])

def _add_soft_penalties_one_nurse(m, X, rs, nurse, T0, T1, obj, off, night):
    """Soft 내규를 1인당 근사 패널티로 추가 (경량)."""
    cfg = rs.config
    # 주 2OFF 위반 패널티
    if cfg.enforce_two_offs_per_week:
        weeks = (T1-T0+1)//7
        for w in range(weeks):
            d0, d1 = w*7, w*7+7
            offs = sum(X[d,off] for d in range(d0,d1) if T0<=d<=T1)
            slack = m.NewIntVar(0,7,f'slack_off_{nurse.id}_{w}')
            m.Add(slack >= 2 - offs)
            obj.append(-300 * slack)
    # Night 균등 : 개인편차는 전역 penalty로 쓰므로 생략 가능
    # N-O-D/E 패턴, OFF 클러스터는 전역 penalty → 생략 또는 근사 추가
    return

def _eval_full_objective(rs: RosterSystem)->float:
    """roster_system.preference_matrix × 할당 – 패널티 계산 (간단)."""
    P = rs.preference_matrix
    val = (P * rs.roster).sum()
    # 경력자 부족, 주2OFF, night dev 등은 1차 패널티 근사치(옵션)
    return -val   # 더 작은 것이 좋은 UB
# 전역 엔진 인스턴스
cp_sat_engine = CPSATBasicEngine()


def generate_roster_cp_sat(nurses_data, prefs_data, config_data, year, month,  shift_manage_data, time_limit_seconds=60):
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
        nurses_data, prefs_data, config_data, year, month, shift_manage_data, time_limit_seconds   
    ) 