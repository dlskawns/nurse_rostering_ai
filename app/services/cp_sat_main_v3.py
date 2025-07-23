"""
main_v3.py와 동일한 품질의 CP-SAT 근무표 생성 엔진

이 엔진은 다음을 포함합니다:
- CP-SAT + LNS 2단계 최적화
- 선호 근무 유형 처리 (shift_preferences)
- 페어링 선호도 처리 (nurse_pair_preferences)
- 상세 메트릭 계산
- 풍부한 로깅 및 분석

main_v3.py의 모든 기능을 DB 호환 방식으로 구현
"""

import time
import json
from datetime import date, datetime
from typing import List, Dict, Any, Tuple
import numpy as np

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


class CPSATMainV3Engine:
    """main_v3.py와 동일한 품질의 완전한 CP-SAT 근무표 생성 엔진"""
    
    def __init__(self):
        self.logger_prefix = "[CP-SAT-Main-V3]"
    
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
            global_monthly_off_days=config_data.get('global_monthly_off_days', 3),
            standard_personal_off_days=config_data.get('off_days', 8) - config_data.get('global_monthly_off_days', 3) if config_data.get('off_days', 8) > config_data.get('global_monthly_off_days', 3) else 0,
            day_shift_ratio=config_data.get('day_shift_ratio', 1.0),
            evening_shift_ratio=config_data.get('evening_shift_ratio', 1.0),
            night_shift_ratio=config_data.get('night_shift_ratio', 1.0),
            off_shift_ratio=config_data.get('off_shift_ratio', 1.2),
            shift_preference_weights=shift_weights,
            pair_preference_weight=3.0,
            shift_requirement_priority=config_data.get('shift_priority', 0.7)
        )
    
    def create_nurses_from_db(self, nurses_data: List[dict]) -> List[Nurse]:
        """DB에서 가져온 간호사 데이터를 Nurse 객체로 변환"""
        nurses = []
        for nurse_data in nurses_data:
            # resignation_date가 있으면 datetime으로 변환
            if 'resignation_date' in nurse_data and nurse_data['resignation_date']:
                if isinstance(nurse_data['resignation_date'], str):
                    nurse_data['resignation_date'] = datetime.strptime(
                        nurse_data['resignation_date'], '%Y-%m-%d'
                    ).date()
            
            # DB 필드명을 Nurse 클래스 필드명으로 매핑
            nurse_obj = Nurse(
                id=len(nurses),  # 내부 인덱스 ID
                db_id=nurse_data.get('nurse_id', nurse_data.get('id', '')),  # DB ID
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
        """
        DB에서 가져온 선호도 데이터를 main_v3.py 형식으로 변환
        
        Returns:
            Tuple[shift_preferences, off_requests, pair_preferences]
        """
        shift_preferences = {}
        off_requests = {}
        pair_preferences = {"work_together": [], "work_apart": []}
        
        print(f"{self.logger_prefix} 선호도 데이터 파싱 중... ({len(prefs_data)}개 레코드)")
        
        for pref in prefs_data:
            nurse_id = pref['nurse_id']
            data = pref.get('data', {})
            
            if not data:
                continue
            
            # 근무 유형 선호도 파싱 (main_v3.py 형식으로)
            if 'shift' in data:
                shift_prefs = {}
                for shift_type, dates in data['shift'].items():
                    if shift_type.upper() in ['D', 'E', 'N']:
                        # main_v3.py 형식: {"D": {"4": 1.0, "5": 3.2}, ...}
                        shift_prefs[shift_type.upper()] = {}
                        for date_str, weight in dates.items():
                            # 가중치를 기본값에서 델타로 변환 (main_v3 형식)
                            delta_weight = float(weight) - 5.0  # 기본 가중치 5.0에서 차이값
                            shift_prefs[shift_type.upper()][str(date_str)] = delta_weight
                            
                if shift_prefs:
                    shift_preferences[nurse_id] = shift_prefs
            
            # 휴무 요청 파싱
            if 'off' in data and data['off']:
                off_dict = {}
                for date_str in data['off']:
                    try:
                        day = int(date_str)
                        # 기본 휴무 요청 가중치 설정
                        off_dict[str(day)] = 5.0  
                    except (ValueError, TypeError):
                        continue
                if off_dict:
                    off_requests[nurse_id] = off_dict
            
            # preference 배열에서 OFF 요청과 페어링 선호도 파싱
            if 'preference' in data and data['preference']:
                for pref_item in data['preference']:
                    if isinstance(pref_item, dict):
                        # OFF 요청 처리
                        if pref_item.get('shift') == 'OFF':
                            date = pref_item.get('date')
                            weight = pref_item.get('weight', 5.0)
                            if date:
                                if nurse_id not in off_requests:
                                    off_requests[nurse_id] = {}
                                off_requests[nurse_id][str(date)] = float(weight)
                        
                        # 페어링 선호도 처리
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
        
        print(f"{self.logger_prefix} 파싱 완료: shift_preferences={len(shift_preferences)}, off_requests={len(off_requests)}, pair_preferences={len(pair_preferences['work_together']) + len(pair_preferences['work_apart'])}")
        
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
        main_v3.py와 동일한 품질의 CP-SAT 근무표 생성
        
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
        
        print(f"\n{'='*60}")
        print(f"{self.logger_prefix} main_v3.py 품질 근무표 생성 시작")
        print(f"대상: {year}년 {month}월")
        print(f"간호사 수: {len(nurses_data)}, 선호도 수: {len(prefs_data)}")
        print(f"{'='*60}")
        
        # 1. 설정 객체 생성
        with Timer("설정 생성"):
            config = self.create_config_from_db(config_data)
            print(f"  - 인원 요구사항: {config.daily_shift_requirements}")
            print(f"  - 제약사항 우선순위: {config.shift_requirement_priority:.2f}")
        
        # 2. 대상 월 설정
        target_month = date(year, month, 1)
        
        # 3. 간호사 객체 생성
        with Timer("간호사 객체 생성"):
            nurses = self.create_nurses_from_db(nurses_data)
            for nurse in nurses:
                nurse.initialize_off_days(config)
            
            print(f"  - 간호사 {len(nurses)}명 생성 완료")
            print(f"  - 야간 전담: {sum(1 for n in nurses if n.is_night_nurse)}명")
            print(f"  - 수간호사: {sum(1 for n in nurses if n.is_head_nurse)}명")
        
        # 4. 근무표 시스템 생성
        with Timer("근무표 시스템 초기화"):
            roster_system = RosterSystem(nurses, target_month, config)
            print(f"  - 근무표 시스템 초기화 완료 ({roster_system.num_days}일)")
        
        # 5. 선호도 데이터 파싱 및 적용
        with Timer("선호도 데이터 파싱"):
            shift_preferences, off_requests, pair_preferences = self.parse_preferences_from_db(prefs_data)
        
        # 6. 휴무 요청 적용
        if off_requests:
            with Timer("휴무 요청 적용"):
                print(f"{self.logger_prefix} 휴무 요청 적용 중... ({len(off_requests)}명)")
                roster_system.apply_off_requests(off_requests)
                
                # 적용 결과 요약
                total_requests = sum(len(requests) for requests in off_requests.values())
                print(f"  - 총 {total_requests}개 휴무 요청 적용")
        else:
            print(f"{self.logger_prefix} 휴무 요청 없음")
        
        # 7. 선호 근무 유형 적용 (main_v3.py 핵심 기능)
        if shift_preferences:
            with Timer("선호 근무 유형 적용"):
                print(f"{self.logger_prefix} 선호 근무 유형 적용 중... ({len(shift_preferences)}명)")
                roster_system.apply_shift_preferences(shift_preferences)
                
                # 적용 결과 요약
                total_shift_prefs = sum(
                    len(shifts) for nurse_shifts in shift_preferences.values() 
                    for shifts in nurse_shifts.values()
                )
                print(f"  - 총 {total_shift_prefs}개 근무 유형 선호도 적용")
        else:
            print(f"{self.logger_prefix} 근무 유형 선호도 없음")
        
        # 8. 페어링 선호도 적용 (main_v3.py 핵심 기능)
        with Timer("페어링 선호도 적용"):
            print(f"{self.logger_prefix} 페어링 선호도 적용 중...")
            print(f"  - 함께 일하기: {len(pair_preferences['work_together'])}쌍")
            print(f"  - 따로 일하기: {len(pair_preferences['work_apart'])}쌍")
            roster_system.apply_pair_preferences(pair_preferences)
        
        # 9. CP-SAT으로 1차 최적화 (main_v3.py와 동일)
        with Timer("CP-SAT 1차 최적화"):
            print(f"{self.logger_prefix} CP-SAT 최적화 시작 (시간 제한: {time_limit_seconds}초)...")
            success = roster_system.optimize_roster_with_cp_sat_v2(time_limit_seconds=time_limit_seconds)
            
            if not success:
                print(f"{self.logger_prefix} CP-SAT 최적화 실패!")
                return {}
        
        # 10. LNS로 2차 최적화 (main_v3.py 핵심 기능)
        use_lns = True
        if use_lns:
            with Timer("LNS 2차 최적화"):
                print(f"{self.logger_prefix} LNS 추가 최적화 시작...")
                lns_iterations = min(5, max(2, time_limit_seconds // 20))  # 시간에 따른 동적 반복 수
                roster_system.optimize_with_lns(
                    max_iterations=lns_iterations, 
                    time_limit_per_iteration=min(15, time_limit_seconds // 3)
                )
        
        # 11. 최적화 결과 분석 및 출력 (main_v3.py 수준의 상세 분석)
        with Timer("최적화 결과 분석"):
            self._analyze_optimization_results(roster_system)
        
        # 12. 상세 메트릭 계산 (main_v3.py 기능)
        with Timer("상세 메트릭 계산"):
            try:
                metrics = roster_system.calculate_detailed_metrics()
                self._print_detailed_metrics_summary(metrics)
            except Exception as e:
                print(f"{self.logger_prefix} 상세 메트릭 계산 중 오류: {e}")
        
        # 13. 결과 변환
        with Timer("결과 변환"):
            result = self._convert_result_to_db_format(roster_system, nurses)
        
        print(f"\n{self.logger_prefix} main_v3.py 품질 근무표 생성 완료!")
        print(f"{'='*60}")
        
        return result
    
    def _analyze_optimization_results(self, roster_system: RosterSystem):
        """최적화 결과를 main_v3.py 수준으로 상세 분석"""
        print(f"\n{self.logger_prefix} 최적화 결과 분석:")
        
        # 1. 제약 위반사항 확인
        violations = roster_system._find_violations()
        if violations:
            print(f"  - 제약 위반: {len(violations)}건 발견")
            
            # 위반 유형별 분류
            violation_types = {}
            for v in violations:
                v_type = v.get('type', 'unknown')
                violation_types[v_type] = violation_types.get(v_type, 0) + 1
            
            for v_type, count in violation_types.items():
                print(f"    • {v_type}: {count}건")
        else:
            print("  - 모든 제약 조건 충족! ✓")
        
        # 2. 선호도 만족도 계산 (main_v3.py 기능)
        try:
            off_satisfaction = roster_system._calculate_off_preference_satisfaction()
            print(f"  - 선호 휴무일 만족도: {off_satisfaction:.2f}%")
            
            shift_satisfaction = roster_system._calculate_shift_preference_satisfaction()
            print(f"  - 근무 유형 선호도 만족도: {shift_satisfaction:.2f}%")
            
            if hasattr(roster_system, 'pair_matrix'):
                pair_satisfaction = roster_system._calculate_pair_preference_satisfaction()
                print(f"  - 페어링 선호도 만족도:")
                print(f"    • 함께 일하기: {pair_satisfaction['together']:.2f}%")
                print(f"    • 따로 일하기: {pair_satisfaction['apart']:.2f}%")
                print(f"    • 종합: {pair_satisfaction['overall']:.2f}%")
        except Exception as e:
            print(f"  - 선호도 만족도 계산 중 오류: {e}")
        
        # 3. 인원 배정 현황 확인
        print(f"  - 일일 인원 배정 현황:")
        for day in range(min(7, roster_system.num_days)):  # 첫 7일만 표시
            day_summary = []
            for shift in ['D', 'E', 'N']:
                shift_idx = roster_system.config.shift_types.index(shift)
                required = roster_system.config.daily_shift_requirements[shift]
                assigned = sum(roster_system.roster[n_idx, day, shift_idx] for n_idx in range(len(roster_system.nurses)))
                status = "✓" if assigned == required else f"({assigned}≠{required})"
                day_summary.append(f"{shift}:{assigned}{status}")
            print(f"    • Day {day+1}: {', '.join(day_summary)}")
        
        if roster_system.num_days > 7:
            print(f"    • ... (총 {roster_system.num_days}일)")

    def _print_detailed_metrics_summary(self, metrics: Dict):
        """상세 메트릭 요약 출력 (main_v3.py 수준)"""
        print(f"\n{self.logger_prefix} 상세 메트릭 요약:")
        
        # 업무량 분포
        if 'workload_distribution' in metrics:
            workload = metrics['workload_distribution'].get('statistics', {})
            print(f"  - 업무량 분포:")
            print(f"    • 평균 근무일: {workload.get('mean_shifts', 0):.2f}")
            print(f"    • 표준편차: {workload.get('std_shifts', 0):.2f}")
            print(f"    • 최소-최대: {workload.get('min_shifts', 0):.0f}-{workload.get('max_shifts', 0):.0f}")
        
        # 간호사 만족도
        if 'nurse_satisfaction' in metrics:
            satisfaction = metrics['nurse_satisfaction'].get('average', 0)
            print(f"  - 평균 간호사 만족도: {satisfaction:.2f}")
        
        # 커버리지 메트릭
        if 'coverage_metrics' in metrics:
            coverage = metrics['coverage_metrics'].get('overall', {})
            for shift, data in coverage.items():
                ratio = data.get('coverage_ratio', 1.0)
                status = "✓" if 0.95 <= ratio <= 1.05 else f"({ratio:.2f})"
                print(f"  - {shift} 커버리지: {status}")
        
        # 공정성 메트릭
        if 'fairness_metrics' in metrics:
            fairness = metrics['fairness_metrics'].get('shift_distribution', {})
            for shift, data in fairness.items():
                gini = data.get('gini_coefficient', 0)
                print(f"  - {shift} 공정성 (Gini): {gini:.3f}")

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
                    nurse_schedule.append('O')  # 기본값
            
            result[nurse.db_id] = nurse_schedule
        
        return result


# 전역 엔진 인스턴스
cp_sat_main_v3_engine = CPSATMainV3Engine()


def generate_roster_cp_sat_main_v3(nurses_data, prefs_data, config_data, year, month, time_limit_seconds=60):
    """
    main_v3.py와 동일한 품질의 CP-SAT 근무표 생성 (기존 인터페이스 호환)
    
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
    return cp_sat_main_v3_engine.generate_roster(
        nurses_data, prefs_data, config_data, year, month, time_limit_seconds
    ) 