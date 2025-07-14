"""
개선된 CP-SAT 알고리즘 테스트 스크립트

법규 제약사항과 병원 내규가 적용된 알고리즘들의 성능을 테스트합니다.
"""

import time
import json
from datetime import date
from typing import Dict, List

# CP-SAT 알고리즘들 import
try:
    from cp_sat_basic import generate_roster_cp_sat
    from cp_sat_main_v3 import generate_roster_cp_sat_main_v3
    from cp_sat_main_v2 import generate_roster_cp_sat_main_v2
    from cp_sat_adaptive import generate_roster_cp_sat_adaptive
    ALGORITHMS_AVAILABLE = True
except ImportError as e:
    print(f"알고리즘 import 실패: {e}")
    ALGORITHMS_AVAILABLE = False

def create_test_nurses():
    """테스트용 간호사 데이터 생성"""
    return [
        {
            'nurse_id': 'N001',
            'name': '김수간호사',
            'experience': 10,
            'is_head_nurse': True,
            'is_night_nurse': False,
            'personal_off_adjustment': 0
        },
        {
            'nurse_id': 'N002',
            'name': '이야간간호사',
            'experience': 8,
            'is_head_nurse': False,
            'is_night_nurse': True,
            'personal_off_adjustment': 0
        },
        {
            'nurse_id': 'N003',
            'name': '박경력간호사',
            'experience': 6,
            'is_head_nurse': False,
            'is_night_nurse': False,
            'personal_off_adjustment': 0
        },
        {
            'nurse_id': 'N004',
            'name': '최신입간호사',
            'experience': 1,
            'is_head_nurse': False,
            'is_night_nurse': False,
            'personal_off_adjustment': 0
        },
        {
            'nurse_id': 'N005',
            'name': '정중견간호사',
            'experience': 4,
            'is_head_nurse': False,
            'is_night_nurse': False,
            'personal_off_adjustment': 0
        }
    ]

def create_test_config():
    """테스트용 설정 데이터 생성"""
    return {
        # 일일 인원 요구사항
        'daily_shift_requirements': {
            'D': 2,
            'E': 2, 
            'N': 1
        },
        
        # 법규 제약사항 (Hard Constraints)
        'max_conseq_work': 5,  # 최대 연속 근무일 수
        'banned_day_after_eve': True,  # E → D 근무 금지
        'three_seq_nig': True,  # N 연속 3회 허용
        'two_offs_after_three_nig': True,  # N 3회 후 OFF 2회
        'two_offs_after_two_nig': False,  # N 2회 후 OFF 2회
        'max_nig_per_month': 12,  # 월 최대 N 근무 수
        
        # 병원 내규 (Soft Constraints)
        'min_exp_per_shift': 3,  # shift 내 책임 최소 경력
        'req_exp_nurses': 1,  # 책임 간호 인원
        'two_offs_per_week': True,  # 주 2회 이상 OFF
        'sequential_offs': True,  # OFF 연속 배정
        'even_nights': True,  # N 개수 균등 배정
        
        # 기타 설정
        'off_days': 8,
        'shift_priority': 0.7
    }

def create_test_preferences():
    """테스트용 선호도 데이터 생성"""
    return [
        {
            'nurse_id': 'N001',
            'data': {
                'shift': {
                    'D': {'1': 8.0, '15': 8.0},  # 특정 날짜에 Day 선호
                },
                'off': ['5', '6', '12', '13', '19', '20', '26', '27']  # 주말 휴무 선호
            }
        },
        {
            'nurse_id': 'N002',
            'data': {
                'shift': {
                    'N': {'3': 9.0, '10': 9.0, '17': 9.0, '24': 9.0}  # Night 선호
                },
                'off': ['7', '14', '21', '28']
            }
        },
        {
            'nurse_id': 'N003',
            'data': {
                'shift': {
                    'E': {'2': 7.0, '9': 7.0, '16': 7.0, '23': 7.0}  # Evening 선호
                },
                'off': ['8', '15', '22', '29']
            }
        }
    ]

def test_algorithm(algorithm_name: str, algorithm_func, nurses_data: List[dict], 
                  prefs_data: List[dict], config_data: dict, year: int, month: int):
    """개별 알고리즘 테스트"""
    print(f"\n{'='*60}")
    print(f"🧪 {algorithm_name} 테스트 시작")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = algorithm_func(
            nurses_data=nurses_data,
            prefs_data=prefs_data,
            config_data=config_data,
            year=year,
            month=month,
            time_limit_seconds=60
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"✅ {algorithm_name} 성공!")
        print(f"⏱️  실행 시간: {duration:.2f}초")
        print(f"👥 생성된 근무표 간호사 수: {len(result)}")
        
        # 결과 품질 간단 분석
        analyze_result_quality(result, algorithm_name)
        
        return {
            'success': True,
            'duration': duration,
            'result': result
        }
        
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"❌ {algorithm_name} 실패!")
        print(f"⏱️  실행 시간: {duration:.2f}초")
        print(f"🚨 에러: {str(e)}")
        
        return {
            'success': False,
            'duration': duration,
            'error': str(e)
        }

def analyze_result_quality(result: Dict[str, List[str]], algorithm_name: str):
    """근무표 결과 품질 분석"""
    print(f"\n📊 {algorithm_name} 결과 분석:")
    
    total_days = len(next(iter(result.values())))
    nurses_count = len(result)
    
    # 각 간호사별 근무 통계
    for nurse_id, schedule in result.items():
        d_count = schedule.count('D')
        e_count = schedule.count('E')
        n_count = schedule.count('N')
        o_count = schedule.count('O')
        
        print(f"  👨‍⚕️ {nurse_id}: D={d_count}, E={e_count}, N={n_count}, OFF={o_count}")
    
    # 일일 인원 체크
    daily_staff = []
    for day in range(total_days):
        day_d = sum(1 for nurse_schedule in result.values() if nurse_schedule[day] == 'D')
        day_e = sum(1 for nurse_schedule in result.values() if nurse_schedule[day] == 'E')
        day_n = sum(1 for nurse_schedule in result.values() if nurse_schedule[day] == 'N')
        daily_staff.append((day_d, day_e, day_n))
    
    print(f"  📅 일일 인원 현황 (D/E/N): {daily_staff[:7]}..." if len(daily_staff) > 7 else f"  📅 일일 인원 현황 (D/E/N): {daily_staff}")
    
    # 제약 위반 간단 체크
    violations = check_basic_constraints(result)
    if violations:
        print(f"  ⚠️  제약 위반: {len(violations)}건")
        for violation in violations[:3]:  # 처음 3개만 표시
            print(f"    - {violation}")
    else:
        print(f"  ✅ 기본 제약사항 준수")

def check_basic_constraints(result: Dict[str, List[str]]) -> List[str]:
    """기본 제약사항 위반 체크"""
    violations = []
    
    for nurse_id, schedule in result.items():
        # 연속 근무일 체크 (최대 5일)
        consecutive_work = 0
        for day_shift in schedule:
            if day_shift != 'O':
                consecutive_work += 1
                if consecutive_work > 5:
                    violations.append(f"{nurse_id}: 6일 이상 연속 근무")
                    break
            else:
                consecutive_work = 0
        
        # N → D 금지 체크
        for i in range(len(schedule) - 1):
            if schedule[i] == 'N' and schedule[i + 1] == 'D':
                violations.append(f"{nurse_id}: N 다음 D 근무 (일 {i+1}-{i+2})")
        
        # E → D 금지 체크
        for i in range(len(schedule) - 1):
            if schedule[i] == 'E' and schedule[i + 1] == 'D':
                violations.append(f"{nurse_id}: E 다음 D 근무 (일 {i+1}-{i+2})")
    
    return violations

def main():
    """메인 테스트 함수"""
    if not ALGORITHMS_AVAILABLE:
        print("❌ 알고리즘을 import할 수 없습니다.")
        return
    
    print("🚀 개선된 CP-SAT 알고리즘 테스트 시작")
    print("=" * 80)
    
    # 테스트 데이터 생성
    nurses_data = create_test_nurses()
    prefs_data = create_test_preferences()
    config_data = create_test_config()
    
    # 테스트 대상 월: 2024년 1월
    year, month = 2024, 1
    
    print(f"📋 테스트 설정:")
    print(f"  🗓️  대상 월: {year}년 {month}월")
    print(f"  👥 간호사 수: {len(nurses_data)}")
    print(f"  🎯 일일 인원 요구: D={config_data['daily_shift_requirements']['D']}, "
          f"E={config_data['daily_shift_requirements']['E']}, N={config_data['daily_shift_requirements']['N']}")
    
    # 테스트할 알고리즘들
    algorithms = [
        ("CP-SAT Basic (Enhanced)", generate_roster_cp_sat),
        ("CP-SAT Main V3 (Enhanced)", generate_roster_cp_sat_main_v3),
        ("CP-SAT Main V2 (Enhanced)", generate_roster_cp_sat_main_v2),
        ("CP-SAT Adaptive (Enhanced)", generate_roster_cp_sat_adaptive),
    ]
    
    results = {}
    
    # 각 알고리즘 테스트
    for algorithm_name, algorithm_func in algorithms:
        result = test_algorithm(
            algorithm_name, algorithm_func, nurses_data, prefs_data, config_data, year, month
        )
        results[algorithm_name] = result
        
        # 알고리즘 간 잠시 대기
        time.sleep(1)
    
    # 종합 결과 요약
    print(f"\n{'='*80}")
    print("📊 종합 테스트 결과")
    print(f"{'='*80}")
    
    for algorithm_name, result in results.items():
        status = "✅ 성공" if result['success'] else "❌ 실패"
        duration = result['duration']
        print(f"{algorithm_name:30} | {status} | {duration:6.2f}초")
    
    # 성공한 알고리즘 중 가장 빠른 것
    successful_results = {name: res for name, res in results.items() if res['success']}
    if successful_results:
        fastest = min(successful_results.items(), key=lambda x: x[1]['duration'])
        print(f"\n🏆 가장 빠른 알고리즘: {fastest[0]} ({fastest[1]['duration']:.2f}초)")
    
    print(f"\n🎉 테스트 완료!")

if __name__ == "__main__":
    main() 