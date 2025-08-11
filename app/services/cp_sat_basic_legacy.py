from datetime import date, datetime, timedelta
import time, os
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
    
    # ---------------- cp_sat_basic.py ----------------
  # =================================================================
    # 1.  _optimize_with_enhanced_constraints  (엔진 클래스 내부에 교체)
    # =================================================================
    def _optimize_with_enhanced_constraints(
        self,
        roster_system: 'RosterSystem',
        time_limit_seconds: int,
        nurses,
        grouped=None
    ) -> bool:
        """
        입사·퇴사일, 법규(하드), 병원 내규(소프트) 전부 반영한 CP-SAT 최적화.
        성공 시 roster_system.roster 갱신 후 True 반환.
        """
        from ortools.sat.python import cp_model
        from datetime import date
        import time

        start_t = time.time()
        cfg      = roster_system.config
        N, D, S  = len(roster_system.nurses), roster_system.num_days, cfg.num_shifts
        firstDay = roster_system.target_month            # 해당 월 1일

        # ───────────────────────────────────────────── join/leave index
        join_idx, leave_idx = [], []
        for n in roster_system.nurses:
            join_idx.append(max((n.joining_date  - firstDay).days, 0)
                            if n.joining_date else 0)
            leave_idx.append(min((n.resignation_date - firstDay).days, D-1)
                             if n.resignation_date else D-1)

        # ───────────────────────────────────────────── fixed cells
        shift_code_to_main = {c: r['main_code']
                              for r in (grouped or [])
                              for c in r.get('codes', [])}
        fixed  : Dict[Tuple[int, int], int] = {}
        fixed_cnt = [[0]*S for _ in range(D)]
        if getattr(roster_system, 'fixed_cells', None):
            for cell in roster_system.fixed_cells:
                n, d, code = cell['nurse_index'], cell['day_index'], cell['shift']
                main = shift_code_to_main.get(code, code)
                if main not in cfg.shift_types:              # 미등록 시 건너뛰기
                    continue
                s = cfg.shift_types.index(main)
                fixed[(n, d)]     = s
                fixed_cnt[d][s]  += 1

        # ───────────────────────────────────────────── CP-SAT Model
        m  = cp_model.CpModel()
        x  = {}                                             # (n,d,s) → BoolVar
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n]+1):
                for s in range(S):
                    x[n, d, s] = m.NewBoolVar(f'x_{n}_{d}_{s}')

        # helper
        def X(n, d, s): return x.get((n, d, s), 0)

        # 2-A) 고정 셀
        for (n, d), s_fix in fixed.items():
            m.Add(X(n, d, s_fix) == 1)
            for s in range(S):
                if s != s_fix:
                    m.Add(X(n, d, s) == 0)

        # 2-B) exactly-one
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n]+1):
                if (n, d) in fixed:   # 이미 지정됨
                    continue
                m.AddExactlyOne(X(n, d, s) for s in range(S))

        # 2-C) 일별 인원
        for d in range(D):
            for sh, req in cfg.daily_shift_requirements.items():
                s = cfg.shift_types.index(sh)
                need = req - fixed_cnt[d][s]
                if need <= 0:
                    continue
                m.Add(sum(X(n, d, s)
                          for n in range(N)
                          if join_idx[n] <= d <= leave_idx[n]
                          and (n, d) not in fixed) >= need)

        # 3) 법규 하드 제약
        night, day, eve, off = (cfg.shift_types.index(x)
                                for x in ('N', 'D', 'E', 'OFF'))

        # 최대 연속 근무 (K+1 창에 OFF ≥1)
        K = cfg.max_consecutive_work_days
        for n in range(N):
            for s_d in range(join_idx[n], leave_idx[n]-K+1):
                m.Add(sum(X(n, s_d+t, off)
                          for t in range(K+1)
                          if s_d+t <= leave_idx[n]) >= 1)

        # E→D, N→D 금지
        if cfg.banned_day_after_eve:
            for n in range(N):
                for d in range(join_idx[n]+1, leave_idx[n]+1):
                    m.Add(X(n, d, day) + X(n, d-1, eve) <= 1)
        for n in range(N):
            for d in range(join_idx[n]+1, leave_idx[n]+1):
                m.Add(X(n, d, day) + X(n, d-1, night) <= 1)

        # night only nurse
        for n, nurse in enumerate(roster_system.nurses):
            if nurse.is_night_nurse:
                for d in range(join_idx[n], leave_idx[n]+1):
                    m.Add(X(n, d, day) == 0)
                    m.Add(X(n, d, eve) == 0)

        # 최대 연속 야간
        L = cfg.max_consecutive_nights
        for n in range(N):
            for s_d in range(join_idx[n], leave_idx[n]-L):
                m.Add(sum(X(n, s_d+t, night)
                          for t in range(L+1)
                          if s_d+t <= leave_idx[n]) <= L)

        # 월 야간 총량
        for n in range(N):
            m.Add(sum(X(n, d, night)
                      for d in range(join_idx[n], leave_idx[n]+1))
                  <= cfg.max_night_shifts_per_month)

        # (N N N) 뒤 OFF×2, (N N) 뒤 OFF×2
        if cfg.two_offs_after_three_nig:
            for n in range(N):
                for d in range(join_idx[n]+2, leave_idx[n]-1):
                    threeN = X(n,d-2,night)+X(n,d-1,night)+X(n,d,night)
                    off2   = X(n,d+1,off)+X(n,d+2,off)
                    m.Add(off2 >= 2*(threeN-2))
        if cfg.two_offs_after_two_nig:
            for n in range(N):
                for d in range(join_idx[n]+1, leave_idx[n]-1):
                    twoN = X(n,d-1,night)+X(n,d,night)
                    off2 = X(n,d+1,off)+X(n,d+2,off)
                    m.Add(off2 >= 2*(twoN-1))

        # 4) 병원 내규 (soft → 패널티 변수)
        pen = []

        # 4-1 경력자 부족
        min_exp, need_exp = cfg.min_experience_per_shift, cfg.required_experienced_nurses
        for d in range(D):
            for sh in ('D','E','N'):
                s = cfg.shift_types.index(sh)
                exp_assigned = sum(
                    X(n,d,s) for n,p in enumerate(roster_system.nurses)
                    if p.experience_years >= min_exp and join_idx[n]<=d<=leave_idx[n])
                short = m.NewIntVar(0, need_exp, f'exp_short_{d}_{sh}')
                m.Add(short >= need_exp - exp_assigned)
                pen.append(100*short)

        # 4-2 주당 2OFF
        if cfg.enforce_two_offs_per_week:
            for n in range(N):
                for w in range(D//7):
                    w0, w1 = w*7, min(w*7+7, D)
                    if w1   <= join_idx[n] or w0 > leave_idx[n]:
                        continue
                    offs = sum(X(n,d,off) for d in range(max(w0,join_idx[n]),
                                                         min(w1,leave_idx[n]+1)))
                    lack = m.NewIntVar(0,2,f'week_off_{n}_{w}')
                    m.Add(lack >= 2 - offs)
                    pen.append(500*lack)

        # 4-3 N 균등
        if cfg.even_nights:
            non_night = [i for i,p in enumerate(roster_system.nurses) if not p.is_night_nurse]
            if len(non_night)>1:
                totalN = sum(cfg.daily_shift_requirements.get('N',2) for _ in range(D))
                target = totalN//len(non_night)
                for n in non_night:
                    tot = sum(X(n,d,night) for d in range(join_idx[n], leave_idx[n]+1))
                    pos = m.NewIntVar(0,D,f'posN_{n}')
                    neg = m.NewIntVar(0,D,f'negN_{n}')
                    m.Add(pos-neg == tot-target)
                    pen.extend([50*pos, 50*neg])

        # 4-4 N-O-D/E 패턴, 4-5 고립 OFF
        for n in range(N):
            for d in range(join_idx[n]+2, leave_idx[n]-1):
                nod = m.NewIntVar(0,1,f'nod_{n}_{d}')
                noe = m.NewIntVar(0,1,f'noe_{n}_{d}')
                m.Add(nod >= X(n,d-2,night)+X(n,d-1,off)+X(n,d,day)-2)
                m.Add(noe >= X(n,d-2,night)+X(n,d-1,off)+X(n,d,eve)-2)
                pen.extend([100*nod,100*noe])
            for d in range(join_idx[n], leave_idx[n]+1):
                iso = m.NewIntVar(0,1,f'iso_{n}_{d}')
                m.Add(iso >= X(n,d,off)-X(n,d-1,off)-X(n,d+1,off))
                m.Add(iso <= X(n,d,off))
                pen.append(100*iso)

        # 5) 목적함수 = 선호 점수 – 패널티
        obj = []
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n]+1):
                for s in range(S):
                    score = int(roster_system.preference_matrix[n,d,s]*100)
                    obj.append(score * X(n,d,s))
        obj.extend(-v for v in pen)
        m.Maximize(sum(obj))

        # 6) 힌트 주입 + Solver 실행
        greedy = _seed_schedule(roster_system.preference_matrix,
                                cfg.daily_shift_requirements,
                                cfg.shift_types, fixed)
        for n in range(N):
            for d in range(D):
                var = x.get((n, d, greedy[n, d]), None)
                if var is not None:
                    m.AddHint(var, 1)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers  = min(2, os.cpu_count())
        print('파라미터', solver.parameters.num_search_workers)
        solver.parameters.relative_gap_limit  = 0.05
        start = time.time()
        status = solver.Solve(m)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("❌   solve failed")
            return False
        print('소요시간:', time.time()-start)
        # 7) 결과 반영
        roster_system.roster.fill(0)
        for n in range(N):
            for d in range(join_idx[n], leave_idx[n]+1):
                for s in range(S):
                    if solver.Value(X(n,d,s)):
                        roster_system.roster[n,d,s] = 1

        print(f"✅  OK – {time.time()-start_t:.2f}s  obj={solver.ObjectiveValue():.0f}")
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

# ──────────────────────────────────────────────────────────────
# 0. 보조 헬퍼 ― 안전한 shift_types + greedy 시드
#    (cp_sat_basic.py 최상단 import 아래 아무 곳 넣기)
# ──────────────────────────────────────────────────────────────
from db.roster_config import NurseRosterConfig
import numpy as np
from typing import Dict, List, Tuple

# (0-a) shift_types 보호 – 기본 교대 누락 방지
_orig_shift_types = NurseRosterConfig.shift_types.fget
def _safe_shift_types(self):
    lst = list(_orig_shift_types(self))
    for s in ('D', 'E', 'N'):
        if s not in lst:
            lst.insert(0, s)
    if 'OFF' not in lst:
        lst.append('OFF')
    return lst
NurseRosterConfig.shift_types = property(_safe_shift_types)

# (0-b) 아주 단순한 feasible 시드 생성
def _seed_schedule(pref: np.ndarray,
                   daily_need: Dict[str, int],
                   shift_types: List[str],
                   fixed: Dict[Tuple[int, int], int]) -> np.ndarray:
    N, D, S  = pref.shape
    OFF      = S - 1                         # shift_types[-1] == 'OFF' 라고 가정
    quota    = np.zeros((D, S), dtype=int)
    for d in range(D):
        for s, sh in enumerate(shift_types[:-1]):        # OFF 제외
            quota[d, s] = daily_need.get(sh, 0)
    for (_, d), s in fixed.items():                      # 고정 셀 차감
        if s != OFF:
            quota[d, s] -= 1

    sched = np.full((N, D), OFF, dtype=int)
    for (n, d), s in fixed.items():
        sched[n, d] = s

    order = np.dstack(np.unravel_index(
        np.argsort(-pref.max(axis=2), axis=None), (N, D)))[0]
    for n, d in order:
        if (n, d) in fixed:
            continue
        best_s = int(np.argmax(pref[n, d, :-1]))         # OFF 제외
        if quota[d, best_s] > 0:
            sched[n, d]  = best_s
            quota[d, best_s] -= 1
    return sched
# ──────────────────────────────────────────────────────────────


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