from datetime import date, datetime, timedelta
import time
import numpy as np
from typing import List, Dict, Optional, Tuple
from db.roster_config import NurseRosterConfig
from db.nurse_config import Nurse
from services.roster_system import RosterSystem
import numpy as np
from collections import defaultdict
import random
# ─────────────────────────────  RL Neighborhood  ─────────────────────────
class RLNeighborhoodPolicy:
    """아주 가벼운 ε-greedy 정책"""
    def __init__(self, N, D, eps0=0.3, eps_end=0.05, decay=0.995):
        self.N, self.D = N, D
        self.eps, self.eps_end, self.decay = eps0, eps_end, decay
        self.n_w, self.d_w = np.ones(N), np.ones(D)

    def select(self, k_n=4, k_d=7):
        if random.random() < self.eps:                          # explore
            n_sel = random.sample(range(self.N), k=min(k_n,self.N))
            d_sel = random.sample(range(self.D), k=min(k_d,self.D))
        else:                                                   # exploit
            n_sel = list(np.random.choice(self.N,k_n,replace=False,
                                           p=self.n_w/self.n_w.sum()))
            d_sel = list(np.random.choice(self.D,k_d,replace=False,
                                           p=self.d_w/self.d_w.sum()))
        self.eps = max(self.eps_end, self.eps*self.decay)
        return n_sel, d_sel

    def update(self, ok: bool, n_sel, d_sel):
        delta = 2.0 if ok else -1.0
        self.n_w[n_sel] += delta;  self.n_w = np.clip(self.n_w, .1, None)
        self.d_w[d_sel] += delta;  self.d_w = np.clip(self.d_w, .1, None)


# ───────────────────────────────  Timer  ────────────────────────────────
class Timer:
    def __init__(self, msg): self.msg = msg
    def __enter__(self): print(f"\n{self.msg} 시작…"); self.t0=time.time()
    def __exit__(self,*a): print(f"{self.msg} 완료: {time.time()-self.t0:.2f}s")



class CPSATBasicEngine:
    """CP-SAT 기반 근무표 생성 엔진"""
    
    def __init__(self):
        self.logger_prefix = "[CP-SAT-Basic]"
    
    def create_config_from_db(self, config_data: dict) -> NurseRosterConfig:
        """DB에서 가져온 설정 데이터를 NurseRosterConfig 객체로 변환"""
        print('config_data', config_data.get('shift_priority'))
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
        shift_weights = config_data.get('shift_preference_weights', {
            'D': 5.0, 
            'E': 5.0, 
            'N': 7.0,  # Night Keep은 더 높은 가중치
            'O': 10.0
        })
        
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
            nod_noe=config_data.get('nod_noe', True),
            global_monthly_off_days=2,
            standard_personal_off_days=config_data.get('off_days', 8) - 2 if config_data.get('off_days', 8) > 2 else 0,
            # 수정
            shift_requirement_priority = max(0.05, config_data.get('shift_priority', 0.7)),
            shift_preference_weights=shift_weights,
            pair_preference_weight=config_data.get('pair_preference_weight', 3.0),
            # 프리셉터 관련 오버라이드 반영
            preceptor_enable=config_data.get('preceptor_enable', True),
            preceptor_strength_multiplier=config_data.get('preceptor_strength_multiplier', 1.0),
            preceptor_top_days=config_data.get('preceptor_top_days', 12),
            preceptor_min_pair_weight=config_data.get('preceptor_min_pair_weight', 5.0),
            preceptor_focus_shifts=config_data.get('preceptor_focus_shifts', None)
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
        # sequence 기준 정렬(없으면 0) → 알고리즘 입력 순서 일관화
        sorted_rows = sorted(nurses_data, key=lambda r: (r.get('sequence', 0), -int(r.get('experience', 0) or 0), str(r.get('nurse_id'))))
        nurses = []
        for i, nurse_data in enumerate(sorted_rows):
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
                off_requests[nurse_id] = data['shift']['O']
            
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
        time_limit_seconds: int = 60,
        randomize: bool = True,           # ← 추가
        seed: int | None = None           # ← 추가 (재현 원하면 지정)
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
            # 고정된 셀 정보 처리
            fixed_cells = list(config_data.get('fixed_cells', []) or [])
            # ── 경계 제약(강제 OFF/금지) 병합 ──
            initial_constraints = config_data.get('initial_constraints') or {}
            allow_override_by_law = bool(config_data.get('allow_override_by_law', False))
            rs_dbid_to_idx = {n.db_id: n.id for n in nurses}
            # forced_off: { nurse_db_id: [day_idx,...] }
            forced_off = initial_constraints.get('forced_off') or {}
            if forced_off:
                for dbid, day_list in forced_off.items():
                    n_idx = rs_dbid_to_idx.get(dbid)
                    if n_idx is None:
                        continue
                    for d in day_list:
                        # 기존 고정과 충돌 검출
                        conflict = next((c for c in fixed_cells if c.get('nurse_index')==n_idx and c.get('day_index')==d and c.get('shift')!='O'), None)
                        if conflict:
                            msg = f"법규-유저 고정 충돌: nurse={dbid}, day={d+1}, user={conflict.get('shift')}, law=O"
                            print(f"{self.logger_prefix} {msg}")
                            if not allow_override_by_law:
                                raise ValueError(msg)
                            # override: 기존 고정 무시
                            fixed_cells = [c for c in fixed_cells if not (c.get('nurse_index')==n_idx and c.get('day_index')==d)]
                        fixed_cells.append({'nurse_index': n_idx, 'day_index': d, 'shift': 'O'})
            if fixed_cells:
                print(f"{self.logger_prefix} 고정된 셀 {len(fixed_cells)}개 처리 중...")
                roster_system.fixed_cells = fixed_cells
                for fixed_cell in fixed_cells:
                    print(f"{self.logger_prefix} 고정 셀: 간호사 {fixed_cell['nurse_index']}, 날짜 {fixed_cell['day_index']+1}, 근무 {fixed_cell['shift']}")
            # forbidden: { nurse_db_id: { day_idx: [codes...] } }
            forbidden = initial_constraints.get('forbidden') or {}
            if forbidden:
                # 내부 인덱스 매핑 구조로 저장
                init_forb = {}
                for dbid, day_map in forbidden.items():
                    n_idx = rs_dbid_to_idx.get(dbid)
                    if n_idx is None:
                        continue
                    for d_str, codes in day_map.items():
                        # 키는 정수 day_idx가 이미 주어졌다고 가정하지만, 혹시 str이면 변환
                        try:
                            d = int(d_str)
                        except Exception:
                            d = d_str
                        init_forb.setdefault((n_idx, d), set()).update(codes)
                roster_system.initial_forbidden = init_forb
        
        # 5. 선호도 데이터 파싱 및 적용
        with Timer("선호도 데이터 파싱"):
            shift_preferences, off_requests, pair_preferences = self.parse_preferences_from_db(prefs_data)
        
        # ────────────────────────────── 프리셉터 페어링 반영 ──────────────────────────────
        # nurses_data 내 preceptor_id 를 사용해 자동으로 함께 근무 선호를 추가한다.
        try:
            valid_ids = {row.get('nurse_id') for row in nurses_data}
            seen_pairs = set()  # 중복 방지 (무방향)
            added_cnt = 0
            # 프리셉터-멘티 함께 근무 가중치: 기본 페어링 대비 강화
            preceptor_pair_weight = float(getattr(config, 'pair_preference_weight', 3.0)) * 2.5
            for row in nurses_data:
                mentee_id = row.get('nurse_id')
                preceptor_id = row.get('preceptor_id')
                if not mentee_id or not preceptor_id:
                    continue
                if preceptor_id not in valid_ids or preceptor_id == mentee_id:
                    continue
                key = frozenset((mentee_id, preceptor_id))
                if key in seen_pairs:
                    continue
                pair_preferences.setdefault('work_together', [])
                pair_preferences['work_together'].append({
                    'nurse_1': mentee_id,
                    'nurse_2': preceptor_id,
                    'weight': preceptor_pair_weight,
                    'source': 'preceptor'
                })
                seen_pairs.add(key)
                added_cnt += 1
            if added_cnt:
                print(f"[CP-SAT-Basic] 프리셉터 페어링 {added_cnt}건 추가 적용")
        except Exception as e:
            print(f"[CP-SAT-Basic] 프리셉터 페어링 반영 중 오류: {e}")
        # ────────────────────────────────────────────────────────────────────────
        
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
            success = self._optimize_with_enhanced_constraints(roster_system, time_limit_seconds, nurses, grouped, randomize=randomize, seed=seed)
            
            if not success:
                print(f"{self.logger_prefix} 개선된 제약사항으로 실패, 기본 알고리즘으로 폴백...")
                roster_system.optimize_roster_with_cp_sat_v2(time_limit_seconds=time_limit_seconds)
        
        # 10. 결과 변환
        with Timer("결과 변환"):
            result = self._convert_result_to_db_format(roster_system, nurses)
        
        # 11. 최적화 결과 출력 및 만족도 데이터 수집
        # 프리셉터 쌍 수집 (DB id 기준)
        preceptor_pairs = []
        try:
            valid_ids = {row.get('nurse_id') for row in nurses_data}
            seen = set()
            for row in nurses_data:
                mentee_id = row.get('nurse_id')
                preceptor_id = row.get('preceptor_id')
                if not mentee_id or not preceptor_id:
                    continue
                if mentee_id not in valid_ids or preceptor_id not in valid_ids or mentee_id == preceptor_id:
                    continue
                k = frozenset((mentee_id, preceptor_id))
                if k in seen:
                    continue
                preceptor_pairs.append((mentee_id, preceptor_id))
                seen.add(k)
        except Exception:
            pass
        satisfaction_data = self._print_optimization_results(roster_system, preceptor_pairs)
        
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


    def _optimize_with_enhanced_constraints(    # <- generate_roster 에서 호출
        self, roster_system: RosterSystem,
        time_limit_seconds: int,
        nurses_data, grouped=None,
        randomize: bool = True,
        seed: int | None = None
    )->bool:
        from ortools.sat.python import cp_model
        if randomize:
            run_seed = seed if seed is not None else ((int(time.time()*1000) ^ random.getrandbits(31)) & 0x7fffffff)

        # ① 0.3× time_limit 으로 “전체 모델” 한번 돌려 feasible 확보
        base_tl = max(5, int(time_limit_seconds*0.3))
        feasible = self._quick_initial_solve(
            roster_system, base_tl, grouped, run_seed)

        # hard 위반 수 세는 헬퍼
        HARD_TYPES = {
            'shift_requirement', 'max_consecutive_night',
            'max_consecutive_work', 'night_after_limit',
            'day_after_evening', 'night_monthly_limit'
        }
        def hard_violation_cnt():
            return sum(1 for v in roster_system._find_violations()
                       if v['type'] in HARD_TYPES)

        best_viol = hard_violation_cnt()
        best_roster = roster_system.roster.copy()

        # ② RL 정책
        policy = RLNeighborhoodPolicy(len(roster_system.nurses),
                                      roster_system.num_days)
        remaining = time_limit_seconds - base_tl
        per_iter  = 8          # neighbourhood solve 8 초
        max_iter  = max(1, remaining // per_iter)

        if max_iter==0:
            print("⚠️  남은 시간이 없어 LNS 패스")
            return best_viol==0

        for it in range(max_iter):
            n_sel, d_sel = policy.select()
            ok = _solve_neighbourhood(roster_system, n_sel, d_sel,
                                      per_iter, grouped, run_seed, it = it)
            if not ok: policy.update(False, n_sel, d_sel); continue

            curr_viol = hard_violation_cnt()
            improved  = curr_viol < best_viol
            if improved:
                best_viol = curr_viol;  best_roster = roster_system.roster.copy()
            else:  # rollback
                roster_system.roster = best_roster.copy()
            policy.update(improved, n_sel, d_sel)
            if best_viol==0: break

        roster_system.roster = best_roster
        return best_viol==0


    # ────────────────────────────────────────────────────────────────────
    #                    ※ 아래는 helper 들 – 모두 완전판               │
    # ────────────────────────────────────────────────────────────────────
    def _quick_initial_solve(self, rs: RosterSystem,
                             tl:int, grouped, run_seed: int | None = None):
        from ortools.sat.python import cp_model
        model,X,j,l,fixed = _build_full_model(rs,grouped)
        solver=cp_model.CpSolver()
        # ▼▼ 랜덤화 추가 ▼▼
        # seed = getattr(rs.config, 'random_seed', None)
        # if seed is None:
        #     # 매 실행마다 다르게: 시간+랜덤믹스
        #     seed = (int(time.time()*1000) ^ random.getrandbits(31)) & 0x7fffffff
        solver.parameters.randomize_search = True
        solver.parameters.random_seed = (run_seed ^ 0x9E3779B1) & 0x7fffffff
        solver.parameters.solution_pool_size = 10
        # ▲▲ 랜덤화 추가 ▲▲

        solver.parameters.max_time_in_seconds=tl
        solver.parameters.num_search_workers=2
        solver.parameters.relative_gap_limit = 0.1
        stat=solver.Solve(model)
        if stat not in (cp_model.OPTIMAL,cp_model.FEASIBLE): return False
        rs.roster.fill(0)
        N,D,S=len(rs.nurses),rs.num_days,rs.config.num_shifts
        for n in range(N):
            for d in range(j[n],l[n]+1):
                for s in range(S):
                    if solver.Value(X(n,d,s)): rs.roster[n,d,s]=1
        return True
    
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
                    # if shift_id == 'OFF':
                    #     shift_id = 'O'
                    nurse_schedule.append(shift_id)
                else:
                    nurse_schedule.append('-')
            result[nurse.db_id] = nurse_schedule
        return result
    
    def _print_optimization_results(self, roster_system: RosterSystem, preceptor_pairs=None):
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
            # 개인별 페어링 만족도 출력
            if hasattr(roster_system, 'pair_matrix'):
                print("  - 개인별 페어링 만족도:")
                for nurse_id, info in individual_satisfaction.items():
                    pair_req_cnt = info.get('pair_request_count', 0)
                    if pair_req_cnt == 0:
                        print(f"    • {info['name']}({info['nurse_id']}): -")
                    else:
                        print(f"    • {info['name']}({info['nurse_id']}): {info['pair_satisfaction']:.2f}%")

            # 개인별 선호 휴무일/근무 유형 만족도 출력
            print("  - 개인별 선호 휴무일 만족도:")
            for nurse_id, info in individual_satisfaction.items():
                off_req_cnt = info.get('off_request_count', 0)
                if off_req_cnt == 0:
                    print(f"    • {info['name']}({info['nurse_id']}): -")
                else:
                    print(f"    • {info['name']}({info['nurse_id']}): {info['off_satisfaction']:.2f}%")
            
            print("  - 개인별 근무 유형 선호도 만족도:")
            for nurse_id, info in individual_satisfaction.items():
                shift_req_cnt = info.get('shift_request_count', 0)
                if shift_req_cnt == 0:
                    print(f"    • {info['name']}({info['nurse_id']}): -")
                else:
                    print(f"    • {info['name']}({info['nurse_id']}): {info['shift_satisfaction']:.2f}%")
            
            # 상세 요청 분석
            detailed_analysis = roster_system.calculate_detailed_request_analysis()
            satisfaction_data["detailed_analysis"] = detailed_analysis
            
        except Exception as e:
            print(f"  - 만족도 계산 중 오류: {e}")
        
        # ───────────────── 프리셉터 겹침률 출력 ─────────────────
        try:
            if preceptor_pairs:
                print("\n  - 프리셉터 페어링 반영률:")
                off_idx = roster_system.config.shift_types.index('O')
                # 근무 코드 중 실제 근무(D/E/N) 인덱스
                work_shift_idxs = [roster_system.config.shift_types.index(code) for code in roster_system.config.daily_shift_requirements.keys()]
                dbid_to_idx = {n.db_id: n.id for n in roster_system.nurses}
                for mentee_dbid, preceptor_dbid in preceptor_pairs:
                    n1 = dbid_to_idx.get(mentee_dbid)
                    n2 = dbid_to_idx.get(preceptor_dbid)
                    if n1 is None or n2 is None:
                        continue
                    same_shift_days = 0
                    both_worked_days = 0
                    for d in range(roster_system.num_days):
                        s1 = int(np.argmax(roster_system.roster[n1, d]))
                        s2 = int(np.argmax(roster_system.roster[n2, d]))
                        if s1 != off_idx and s2 != off_idx:
                            both_worked_days += 1
                            if s1 == s2 and s1 in work_shift_idxs:
                                same_shift_days += 1
                    rate = (same_shift_days / both_worked_days * 100.0) if both_worked_days > 0 else 0.0
                    mentee_name = next((n.name for n in roster_system.nurses if n.id == n1), str(mentee_dbid))
                    preceptor_name = next((n.name for n in roster_system.nurses if n.id == n2), str(preceptor_dbid))
                    print(f"    • {mentee_name}({mentee_dbid}) - {preceptor_name}({preceptor_dbid}): 같은 근무 {same_shift_days}일 / 동시근무 {both_worked_days}일 ({rate:.2f}%)")
                # 만족도 데이터에 요약 저장
                satisfaction_data.setdefault("preceptor_overlap", {})
                satisfaction_data["preceptor_overlap"]["note"] = "같은 교대 배정일수 / 두 사람 모두 근무한 일수 기준"
        except Exception as e:
            print(f"  - 프리셉터 반영률 계산 중 오류: {e}")
        
        return satisfaction_data

# ================== Helper 함수 ==========================

def _build_full_model(rs: RosterSystem, grouped, include_pair_objective: bool = True):
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    N,D,S = len(rs.nurses), rs.num_days, rs.config.num_shifts

    # join / leave index
    join, leave = [],[]
    first_day = rs.target_month
    for nu in rs.nurses:
        j = (nu.joining_date-first_day).days if nu.joining_date else 0
        l = (nu.resignation_date-first_day).days if nu.resignation_date else D-1
        join.append(max(j,0)); leave.append(min(l,D-1))
    # 고정 셀 (수간호사 등)
    code2main = {c:r['main_code']
                 for r in (grouped or []) for c in r['codes']}
    fixed, fixed_cnt = {}, [[0]*S for _ in range(D)]
    for c in getattr(rs,'fixed_cells',[]) or []:
        n,d = c['nurse_index'], c['day_index']
        s_main = code2main.get(c['shift'], c['shift'])
        s_idx  = rs.config.shift_types.index(s_main)
        fixed[(n,d)] = s_idx; fixed_cnt[d][s_idx]+=1


    # 변수
    Xv={}
    for n in range(N):
        for d in range(join[n], leave[n]+1):
            for s in range(S):
                Xv[n,d,s]=m.NewBoolVar(f'x_{n}_{d}_{s}')
    def X(n,d,s):  return Xv.get((n,d,s),0)
    
    # ───────────── 2-A. 고정 셀  ─────────────
    for (n,d),s_idx in fixed.items():
        m.Add(X(n,d,s_idx)==1)
        for s in range(S):
            if s!=s_idx: m.Add(X(n,d,s)==0)
    # ───────────── 2-A2. 초기 금지 셀(경계 제약) ─────────────
    try:
        if hasattr(rs, 'initial_forbidden') and isinstance(rs.initial_forbidden, dict):
            for (n, d), code_list in rs.initial_forbidden.items():
                for code in (code_list or []):
                    if code not in rs.config.shift_types:
                        continue
                    s_idx = rs.config.shift_types.index(code)
                    if (n,d) in fixed and fixed[(n,d)] == s_idx:
                        print(f"[CP-SAT-Basic] 경고: 초기 금지와 고정 충돌 (n={n}, d={d+1}, code={code})")
                    m.Add(X(n,d,s_idx)==0)
    except Exception as e:
        print(f"[CP-SAT-Basic] 초기 금지 셀 적용 중 오류: {e}")

    # ───────────── 2-B. Exactly-one ──────────
    for n in range(N):
        for d in range(join[n], leave[n]+1):
            if (n,d) in fixed: continue
            m.AddExactlyOne(X(n,d,s) for s in range(S))

    # ───────────── 2-C. Shift requirements ───
    for d in range(D):
        for code,req in rs.config.daily_shift_requirements.items():
            s = rs.config.shift_types.index(code)
            need = req - fixed_cnt[d][s]
            if need<=0: continue
            m.Add(sum(X(n,d,s)
                      for n in range(N)
                      if join[n]<=d<=leave[n] and (n,d) not in fixed)
                  >= need)

    # shorthand indices
    idx = {c:rs.config.shift_types.index(c) for c in ('D','E','N','O')}
    day,eve,night,off = idx['D'],idx['E'],idx['N'],idx['O']

    # ───────────── 3. Hard 법규 ───────────────
    cfg = rs.config
    K   = cfg.max_consecutive_work_days
    L   = cfg.max_consecutive_nights

    for n,nu in enumerate(rs.nurses):
        T0,T1 = join[n], leave[n]
        # 연속 근무 K+1 중 OFF ≥1
        for d0 in range(T0, T1-K+1):
            m.Add(sum(X(n,d0+t,off) for t in range(K+1)) >= 1)

        # E→D, N→D
        for d in range(T0+1, T1+1):
            m.Add(X(n,d,day)+X(n,d-1,night)<=1)
            if cfg.banned_day_after_eve:
                m.Add(X(n,d,day)+X(n,d-1,eve )<=1)

        # Night-전담
        if nu.is_night_nurse:
            for d in range(T0,T1+1):
                m.Add(X(n,d,day)==0); m.Add(X(n,d,eve)==0)

        # 연속 Night
        for d0 in range(T0, T1-L):
            m.Add(sum(X(n,d0+t,night) for t in range(L+1)) <= L)

        # 월 Night 상한
        m.Add(sum(X(n,d,night) for d in range(T0,T1+1))
              <= cfg.max_night_shifts_per_month)

        # 월 최소 OFF 일수 하드 제약 (프론트 전달 off_days를 최소값으로 해석)
        try:
            base_min_off = int(getattr(cfg, 'global_monthly_off_days', 0) + getattr(cfg, 'standard_personal_off_days', 0))
            # 근무 가능 일수보다 클 수 있으므로 클램프
            min_off_required = min(base_min_off, T1 - T0 + 1)
            if min_off_required > 0:
                m.Add(sum(X(n,d,off) for d in range(T0, T1+1)) >= min_off_required)
        except Exception:
            pass

        # N2/3→2OFF
        if cfg.two_offs_after_three_nig:
            for d in range(T0+2,T1-1):
                m.Add(sum(X(n,d-t,night) for t in (0,1,2))-2
                      <= X(n,d+1,off)+X(n,d+2,off))
        if cfg.two_offs_after_two_nig:
            for d in range(T0+1,T1-1):
                m.Add(sum(X(n,d-t,night) for t in (0,1))-1
                      <= X(n,d+1,off)+X(n,d+2,off))

    # ───────────── 4. Soft (패널티 변수) ───────
    obj=[]
    P = rs.preference_matrix
    for n in range(N):
        for d in range(join[n], leave[n]+1):
            for s in range(S):
                obj.append(int(P[n,d,s]*100)*X(n,d,s))

    # (4-1) 경력자 부족
    for d in range(D):
        for code in ('D','E','N'):
            s=rs.config.shift_types.index(code)
            exp_assigned = sum(X(n,d,s)
                               for n,nu in enumerate(rs.nurses)
                               if join[n]<=d<=leave[n] and
                               nu.experience_years>=cfg.min_experience_per_shift)
            shortage = m.NewIntVar(0, cfg.required_experienced_nurses,
                                   f'expShort_{d}_{code}')
            m.Add(shortage >= cfg.required_experienced_nurses - exp_assigned)
            obj.append(-200*shortage)

    # (4-2) 주 2 OFF
    if cfg.enforce_two_offs_per_week:
        weeks=D//7
        for n in range(N):
            for w in range(weeks):
                d0,d1=w*7,min(w*7+7,D)
                offs=sum(X(n,d,off) for d in range(d0,d1)
                         if join[n]<=d<=leave[n])
                slack = m.NewIntVar(0,2,f'weekSlack_{n}_{w}')
                m.Add(slack >= 2-offs); obj.append(-300*slack)

    # (4-3) 야간 균등 (편차에 선형 패널티)
    if cfg.even_nights:
        normals=[i for i,nu in enumerate(rs.nurses) if not nu.is_night_nurse]
        if normals:
            total_req=sum(cfg.daily_shift_requirements['N'] for _ in range(D))
            target=total_req//len(normals)
            for n in normals:
                totN=sum(X(n,d,night) for d in range(join[n],leave[n]+1))
                devP=m.NewIntVar(0,D,f'devP_{n}')
                devN=m.NewIntVar(0,D,f'devN_{n}')
                m.Add(devP-devN==totN-target)
                obj.extend([-50*devP,-50*devN])

    # (4-4) N-O-D/E 패터
    if getattr(cfg, 'nod_noe', True):
        for n in range(N):
            for d in range(join[n], leave[n]-2):
                pat=m.NewIntVar(0,1,f'NOD_{n}_{d}')
                m.Add(pat >= X(n,d,night)+X(n,d+1,off)+X(n,d+2,day)-2)
                obj.append(-100*pat)
                pat2=m.NewIntVar(0,1,f'NOE_{n}_{d}')
                m.Add(pat2 >= X(n,d,night)+X(n,d+1,off)+X(n,d+2,eve)-2)
                obj.append(-100*pat2)

    # (4-5) 고립 OFF
    for n in range(N):
        for d in range(join[n], leave[n]+1):
            iso=m.NewIntVar(0,1,f'iso_{n}_{d}')
            m.Add(iso >= X(n,d,off)-X(n,d-1,off)-X(n,d+1,off))
            m.Add(iso <= X(n,d,off))
            m.Add(iso <= 1-X(n,d-1,off))
            m.Add(iso <= 1-X(n,d+1,off))
            obj.append(-100*iso)
 
    # (4-6) 프리셉터 보너스 항 모듈화
    if include_pair_objective:
        obj.extend(_add_preceptor_objective_terms(m, rs, X, join, leave))

    m.Maximize(sum(obj))
    return m,X,join,leave,fixed


# ─────────────────────────────────────────────────────────────
#           Neighbourhood solver  (전역 변수·제약 그대로)     │
# ─────────────────────────────────────────────────────────────
def _solve_neighbourhood(rs, n_set, d_set, tl, grouped, run_seed: int | None = None, it:int=0):
    from ortools.sat.python import cp_model
    model,X,j,l,fixed=_build_full_model(rs,grouped, include_pair_objective=False)

    # neighbourhood 외 셀은 현재 값 고정
    N,D,S=len(rs.nurses),rs.num_days,rs.config.num_shifts
    for n in range(N):
        for d in range(D):
            if (n in n_set) and (d in d_set): continue
            assigned=np.where(rs.roster[n,d]==1)[0]
            if len(assigned):
                s0=assigned[0]
                model.Add(X(n,d,s0)==1)
                for s in range(S):
                    if s!=s0: model.Add(X(n,d,s)==0)

    # 옵션: 프리셉터-포커스 이웃일 때만 해당 셀에 한정하여 보너스 항 주입
    try:
        focus_preceptor = bool(getattr(rs.config, 'preceptor_enable', True))
        if focus_preceptor and hasattr(rs, 'pair_matrix') and isinstance(rs.pair_matrix, dict):
            # 선택된 n_set,d_set의 셀만 대상으로 제한된 항 생성
            def X_sub(n,d,s):
                if (n in n_set) and (d in d_set):
                    return X(n,d,s)
                # neighbourhood 밖은 고정되어 있으므로 항의 영향 없음 처리(0 반환)
                return 0
            # join/leave를 그대로 써도 되지만 날짜 필터를 d_set로 제한
            # 간단하게 전역 헬퍼 재사용은 어려우므로, 최소한의 제한형 항만 주입
            together = rs.pair_matrix.get('together')
            if together is not None:
                cfg = rs.config
                strength = float(getattr(cfg, 'preceptor_strength_multiplier', 1.0))
                base_min = float(getattr(cfg, 'preceptor_min_pair_weight', 5.0))
                if getattr(cfg, 'preceptor_focus_shifts', None):
                    focus_codes = [c for c in cfg.preceptor_focus_shifts if c in cfg.daily_shift_requirements.keys()]
                else:
                    focus_codes = list(cfg.daily_shift_requirements.keys())
                shift_indices = [cfg.shift_types.index(c) for c in focus_codes]
                pref = rs.preference_matrix
                pref_sum_threshold = 1.2
                for n1 in n_set:
                    for n2 in n_set:
                        if n1>=n2: continue
                        base = together[n1,n2]
                        if base < base_min: continue
                        w = int(base * 100 * strength)
                        for d in d_set:
                            # 해당 날짜에서 최선의 교대만 선택
                            best=None; best_s=None
                            for s in shift_indices:
                                sc = pref[n1,d,s] + pref[n2,d,s]
                                if sc < pref_sum_threshold: continue
                                if best is None or sc>best:
                                    best,best_s=sc,s
                            if best is None: continue
                            z = model.NewBoolVar(f'pc_lns_{n1}_{n2}_{d}_{best_s}')
                            model.Add(z <= X_sub(n1,d,best_s))
                            model.Add(z <= X_sub(n2,d,best_s))
                            # 목적함수에 추가
                            # CP-SAT Python API에서는 Maximize가 호출 이전이면 terms 누적 가능
                            # 여기서는 model에 저장된 선형식이 없으므로 CpSolver쪽에서 자동 합산되도록 유지
                            # 간단하게: 목적은 build 단계의 obj에만 존재. 여기서는 AddMaxEquality 대신
                            # 리니어식으로 보정: solver Maximize 전에 선호 obj는 이미 존재하므로, 이 항을 모델의
                            # 계수화가 필요. OR-Tools는 명시 obj 합산 인터페이스 없음 → trick: 저장 후 아래에서 사용 안함
                            # 안전하게는 풀빌드에서만 목적에 넣고, LNS에서는 제약만으로 유도 불가 → 여기선 생략
                            # 대신 neighbourhood 풀빌드 자체가 include_pair_objective=False 이므로 성능 우선.
                            # 필요시 풀빌드 쪽 강도 상향으로 보정.
                            pass
    except Exception:
        pass

    solver=cp_model.CpSolver()
    if run_seed is not None:
        # 이웃/반복에 따라 seed 살짝 변조 → 다양성
        tweak = (hash(tuple(sorted(n_set))) ^ hash(tuple(sorted(d_set))) ^ (it * 0x9E3779B1)) & 0x7fffffff
        solver.parameters.randomize_search = True
        solver.parameters.random_seed = (run_seed ^ tweak) & 0x7fffffff
        solver.parameters.solution_pool_size = 10
    solver.parameters.max_time_in_seconds=tl
    solver.parameters.num_search_workers=10
    solver.parameters.relative_gap_limit = 0.1
    st=solver.Solve(model)
    if st not in (cp_model.OPTIMAL,cp_model.FEASIBLE): return False

    # 반영
    for n in n_set:
        for d in d_set:
            for s in range(S):
                rs.roster[n,d,s]=1 if solver.Value(X(n,d,s)) else 0
    return True


def _add_preceptor_objective_terms(m, rs: RosterSystem, X, join, leave):
    """프리셉터(페어 together) 보너스 항을 생성하여 obj 리스트로 반환.
    - 하드 제약은 건드리지 않음. 소프트 보너스만 추가.
    - 설정 파라미터로 강도/탑-K/교대/하한값을 제어.
    - LNS에서는 호출자가 생략하거나 별도 이웃 주입으로 사용 가능.
    """
    obj_terms = []
    cfg = rs.config
    if not getattr(cfg, 'preceptor_enable', True):
        return obj_terms
    if not hasattr(rs, 'pair_matrix') or not isinstance(rs.pair_matrix, dict):
        return obj_terms
    together = rs.pair_matrix.get('together')
    if together is None:
        return obj_terms

    N, D = len(rs.nurses), rs.num_days
    # 유효 쌍 필터
    base_min = float(getattr(cfg, 'preceptor_min_pair_weight', 5.0))
    pairs = [(i, j2, together[i, j2]) for i in range(N) for j2 in range(i+1, N) if together[i, j2] >= base_min]
    if not pairs:
        return obj_terms

    # 교대 필터
    if getattr(cfg, 'preceptor_focus_shifts', None):
        focus_codes = [c for c in cfg.preceptor_focus_shifts if c in cfg.daily_shift_requirements.keys()]
    else:
        focus_codes = list(cfg.daily_shift_requirements.keys())
    shift_indices = [cfg.shift_types.index(c) for c in focus_codes]

    pref = rs.preference_matrix
    pref_sum_threshold = 1.2
    K_default = int(getattr(cfg, 'preceptor_top_days', 12))
    strength = float(getattr(cfg, 'preceptor_strength_multiplier', 1.0))

    import time as _t
    _t0 = _t.time(); _added=0
    for n1, n2, base in pairs:
        w = int(base * 100 * strength)
        d0, d1 = max(join[n1], join[n2]), min(leave[n1], leave[n2])
        scored = []
        for d in range(d0, d1+1):
            best=None; best_s=None
            for s in shift_indices:
                sc = pref[n1,d,s] + pref[n2,d,s]
                if sc < pref_sum_threshold:
                    continue
                if best is None or sc>best:
                    best, best_s = sc, s
            if best is not None:
                scored.append((best,d,best_s))
        K = min(K_default, len(scored))
        for _, d, s in sorted(scored, reverse=True)[:K]:
            z = m.NewBoolVar(f'pc_{n1}_{n2}_{d}_{s}')
            m.Add(z <= X(n1,d,s))
            m.Add(z <= X(n2,d,s))
            obj_terms.append(w * z)
            _added += 1
    _dt = _t.time()-_t0
    print(f"[CP-SAT-Basic] 프리셉터 항: 쌍 {len(pairs)}개, 변수 {_added}개, {_dt:.2f}s, 강도 {strength}x, K={K_default}, shifts={focus_codes}")
    return obj_terms


cp_sat_engine = CPSATBasicEngine()

def generate_roster_cp_sat(nurses_data, prefs_data, config_data, year, month,  shift_manage_data, time_limit_seconds=60, randomize=True, seed=None):
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
        nurses_data, prefs_data, config_data, year, month, shift_manage_data, time_limit_seconds, randomize=randomize, seed=seed
    ) 