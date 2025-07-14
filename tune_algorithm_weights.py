"""
CP-SAT 알고리즘 가중치 튜닝 스크립트

다양한 가중치 조합으로 알고리즘의 성능을 최적화합니다.
"""

import time
import json
from typing import Dict, List, Tuple
from test_enhanced_algorithms import create_test_nurses, create_test_preferences, check_basic_constraints

# CP-SAT 알고리즘들 import
try:
    from cp_sat_basic import generate_roster_cp_sat
    ALGORITHMS_AVAILABLE = True
except ImportError as e:
    print(f"알고리즘 import 실패: {e}")
    ALGORITHMS_AVAILABLE = False

def create_tuning_config(shift_weights: Dict[str, float], penalty_weights: Dict[str, int]):
    """튜닝용 설정 생성"""
    config = {
        # 일일 인원 요구사항
        'daily_shift_requirements': {
            'D': 2,
            'E': 2, 
            'N': 1
        },
        
        # 법규 제약사항 (Hard Constraints)
        'max_conseq_work': 5,
        'banned_day_after_eve': True,
        'three_seq_nig': True,
        'two_offs_after_three_nig': True,
        'two_offs_after_two_nig': False,
        'max_nig_per_month': 12,
        
        # 병원 내규 (Soft Constraints)
        'min_exp_per_shift': 3,
        'req_exp_nurses': 1,
        'two_offs_per_week': True,
        'sequential_offs': True,
        'even_nights': True,
        
        # 기타 설정
        'off_days': 8,
        'shift_priority': 0.7,
        
        # 튜닝 파라미터
        'shift_weights': shift_weights,
        'penalty_weights': penalty_weights
    }
    
    return config

def evaluate_result_quality(result: Dict[str, List[str]]) -> Dict[str, float]:
    """근무표 결과 품질 평가"""
    if not result:
        return {'score': 0.0, 'violations': 100, 'balance': 0.0, 'preferences': 0.0}
    
    metrics = {}
    
    # 1. 제약 위반 점수 (낮을수록 좋음)
    violations = check_basic_constraints(result)
    metrics['violations'] = len(violations)
    
    # 2. 근무 균형 점수 (높을수록 좋음)
    shift_counts = {}
    for nurse_id, schedule in result.items():
        shift_counts[nurse_id] = {
            'D': schedule.count('D'),
            'E': schedule.count('E'),
            'N': schedule.count('N'),
            'O': schedule.count('O')
        }
    
    # 각 시프트별 표준편차 계산 (낮을수록 균등)
    import statistics
    d_counts = [counts['D'] for counts in shift_counts.values()]
    e_counts = [counts['E'] for counts in shift_counts.values()]
    n_counts = [counts['N'] for counts in shift_counts.values()]
    
    balance_score = 0.0
    if len(d_counts) > 1:
        d_std = statistics.stdev(d_counts) if statistics.stdev(d_counts) > 0 else 0.1
        e_std = statistics.stdev(e_counts) if statistics.stdev(e_counts) > 0 else 0.1
        n_std = statistics.stdev(n_counts) if statistics.stdev(n_counts) > 0 else 0.1
        balance_score = 100 / (1 + d_std + e_std + n_std)  # 표준편차가 낮을수록 높은 점수
    
    metrics['balance'] = balance_score
    
    # 3. 선호도 만족 점수 (단순화된 버전)
    # OFF 요청이 얼마나 만족되었는지 계산
    preference_score = 0.0
    total_requests = 0
    satisfied_requests = 0
    
    # 간단한 주말 휴무 선호도 체크 (토일: 5,6,12,13,19,20,26,27번째 날)
    weekend_days = [4, 5, 11, 12, 18, 19, 25, 26]  # 0-based index
    
    for nurse_id, schedule in result.items():
        for weekend_day in weekend_days:
            if weekend_day < len(schedule):
                total_requests += 1
                if schedule[weekend_day] == 'O':
                    satisfied_requests += 1
    
    if total_requests > 0:
        preference_score = (satisfied_requests / total_requests) * 100
    
    metrics['preferences'] = preference_score
    
    # 4. 종합 점수 계산
    violation_penalty = metrics['violations'] * 20  # 위반당 20점 감점
    total_score = metrics['balance'] + metrics['preferences'] - violation_penalty
    metrics['score'] = max(0.0, total_score)  # 음수 방지
    
    return metrics

def test_weight_combination(shift_weights: Dict[str, float], penalty_weights: Dict[str, int],
                          nurses_data: List[dict], prefs_data: List[dict]) -> Tuple[bool, Dict]:
    """특정 가중치 조합 테스트"""
    config = create_tuning_config(shift_weights, penalty_weights)
    
    try:
        result = generate_roster_cp_sat(
            nurses_data=nurses_data,
            prefs_data=prefs_data,
            config_data=config,
            year=2024,
            month=1,
            time_limit_seconds=30  # 빠른 테스트를 위해 짧게
        )
        
        metrics = evaluate_result_quality(result)
        
        return True, {
            'result': result,
            'metrics': metrics,
            'shift_weights': shift_weights,
            'penalty_weights': penalty_weights
        }
        
    except Exception as e:
        return False, {
            'error': str(e),
            'shift_weights': shift_weights,
            'penalty_weights': penalty_weights
        }

def generate_weight_combinations():
    """가중치 조합 생성"""
    combinations = []
    
    # Night 가중치 변화 테스트 (E는 5.0 고정)
    night_weights = [6.0, 7.0, 8.0, 9.0, 10.0]
    off_weights = [10.0, 12.0, 15.0]
    
    # 경력 간호사 부족 패널티 변화
    exp_penalties = [300, 500, 700, 1000]
    
    # 연속 근무 위반 패널티 변화
    consecutive_penalties = [400, 600, 800, 1000]
    
    base_shift_weights = {'D': 5.0, 'E': 5.0, 'N': 7.0, 'OFF': 10.0}
    base_penalty_weights = {'exp_penalty': 500, 'consecutive_penalty': 600}
    
    # Night 가중치 튜닝
    for n_weight in night_weights:
        for off_weight in off_weights:
            shift_weights = base_shift_weights.copy()
            shift_weights['N'] = n_weight
            shift_weights['OFF'] = off_weight
            
            combinations.append((shift_weights, base_penalty_weights.copy()))
    
    # 패널티 가중치 튜닝
    for exp_penalty in exp_penalties:
        for cons_penalty in consecutive_penalties:
            penalty_weights = {
                'exp_penalty': exp_penalty,
                'consecutive_penalty': cons_penalty
            }
            
            combinations.append((base_shift_weights.copy(), penalty_weights))
    
    return combinations

def main():
    """메인 튜닝 함수"""
    if not ALGORITHMS_AVAILABLE:
        print("❌ 알고리즘을 import할 수 없습니다.")
        return
    
    print("🎯 CP-SAT 알고리즘 가중치 튜닝 시작")
    print("=" * 80)
    
    # 테스트 데이터 생성
    nurses_data = create_test_nurses()
    prefs_data = create_test_preferences()
    
    print(f"📋 튜닝 설정:")
    print(f"  👥 간호사 수: {len(nurses_data)}")
    print(f"  🎯 목표: 제약 위반 최소화 + 근무 균형 + 선호도 만족")
    
    # 가중치 조합 생성
    combinations = generate_weight_combinations()
    print(f"  🔢 테스트할 조합 수: {len(combinations)}")
    
    results = []
    best_score = -1
    best_combination = None
    
    print(f"\n🧪 가중치 조합 테스트 시작...")
    
    for i, (shift_weights, penalty_weights) in enumerate(combinations):
        print(f"\n진행률: {i+1}/{len(combinations)} ", end="")
        print(f"(N={shift_weights['N']:.1f}, OFF={shift_weights['OFF']:.1f}, " +
              f"ExpP={penalty_weights['exp_penalty']}, ConsP={penalty_weights['consecutive_penalty']})")
        
        success, result_data = test_weight_combination(
            shift_weights, penalty_weights, nurses_data, prefs_data
        )
        
        if success:
            score = result_data['metrics']['score']
            violations = result_data['metrics']['violations']
            balance = result_data['metrics']['balance']
            preferences = result_data['metrics']['preferences']
            
            print(f"  ✅ 점수: {score:.1f} (위반: {violations}, 균형: {balance:.1f}, 선호도: {preferences:.1f})")
            
            results.append(result_data)
            
            if score > best_score:
                best_score = score
                best_combination = result_data
                print(f"  🏆 새로운 최고 점수!")
        else:
            print(f"  ❌ 실패: {result_data['error']}")
    
    # 결과 분석
    print(f"\n{'='*80}")
    print("📊 튜닝 결과 분석")
    print(f"{'='*80}")
    
    if results:
        # 성공한 결과들 정렬
        successful_results = [r for r in results if 'metrics' in r]
        successful_results.sort(key=lambda x: x['metrics']['score'], reverse=True)
        
        print(f"✅ 성공한 조합: {len(successful_results)}/{len(combinations)}")
        
        # 상위 5개 결과 표시
        print(f"\n🏆 상위 5개 조합:")
        for i, result in enumerate(successful_results[:5]):
            metrics = result['metrics']
            shift_w = result['shift_weights']
            penalty_w = result['penalty_weights']
            
            print(f"{i+1:2d}. 점수: {metrics['score']:6.1f} | " +
                  f"N: {shift_w['N']:4.1f} | OFF: {shift_w['OFF']:5.1f} | " +
                  f"ExpP: {penalty_w['exp_penalty']:4d} | ConsP: {penalty_w['consecutive_penalty']:4d} | " +
                  f"위반: {metrics['violations']:2d} | 균형: {metrics['balance']:5.1f}")
        
        # 최적 조합 상세 정보
        if best_combination:
            print(f"\n🎯 최적 조합 상세:")
            print(f"  🎊 총점: {best_combination['metrics']['score']:.2f}")
            print(f"  ⚠️  제약 위반: {best_combination['metrics']['violations']}건")
            print(f"  ⚖️  근무 균형: {best_combination['metrics']['balance']:.2f}")
            print(f"  😊 선호도 만족: {best_combination['metrics']['preferences']:.2f}%")
            print(f"  🎛️  시프트 가중치: {best_combination['shift_weights']}")
            print(f"  ⚡ 패널티 가중치: {best_combination['penalty_weights']}")
        
        # 결과 저장
        tuning_results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'best_combination': best_combination,
            'top_5_results': successful_results[:5],
            'total_combinations': len(combinations),
            'successful_combinations': len(successful_results)
        }
        
        with open('tuning_results.json', 'w', encoding='utf-8') as f:
            json.dump(tuning_results, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 결과가 'tuning_results.json'에 저장되었습니다.")
    
    else:
        print(f"❌ 성공한 조합이 없습니다.")
    
    print(f"\n🎉 튜닝 완료!")

if __name__ == "__main__":
    main() 