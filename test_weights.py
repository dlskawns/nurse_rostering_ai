#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import numpy as np
import pandas as pd
from datetime import datetime

from roster_system import RosterSystem
from nurse import Nurse
from config import NurseRosterConfig

def load_data(filepath):
    """데이터 파일을 로드합니다."""
    print(f"\n데이터 로드 중: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def create_roster_system(data):
    """데이터에서 근무표 시스템을 생성합니다."""
    # 설정 로드
    config_data = data.get('config', {})
    config = NurseRosterConfig(**config_data)
    
    # 타겟 월 설정
    target_month_str = data.get('target_month', '2023-01-01')
    target_month = datetime.strptime(target_month_str, '%Y-%m-%d').date()
    
    # 간호사 생성
    nurses = []
    for nurse_data in data.get('nurses', []):
        nurses.append(Nurse(**nurse_data))
    
    # 근무표 시스템 생성
    roster_system = RosterSystem(nurses, target_month, config)
    
    # 휴무 요청 적용
    if 'off_requests' in data:
        roster_system.apply_off_requests(data['off_requests'])
    
    # 근무 유형 선호도 적용
    if 'shift_preferences' in data:
        roster_system.apply_shift_preferences(data['shift_preferences'])
    
    # 페어링 선호도 적용
    if 'nurse_pair_preferences' in data:
        roster_system.apply_pair_preferences(data['nurse_pair_preferences'])
    
    return roster_system

def analyze_requirements_satisfaction(roster_system):
    """일일 근무 요구사항 만족도를 분석합니다."""
    total_requirements = 0
    satisfied_requirements = 0
    
    for day in range(roster_system.num_days):
        for shift, required in roster_system.config.daily_shift_requirements.items():
            s_idx = roster_system.config.shift_types.index(shift)
            assigned = sum(roster_system.roster[n_idx, day, s_idx] for n_idx in range(len(roster_system.nurses)))
            
            total_requirements += 1
            if assigned == required:
                satisfied_requirements += 1
    
    if total_requirements == 0:
        return 100.0
    return (satisfied_requirements / total_requirements) * 100.0

def analyze_off_requests_satisfaction(roster_system, data):
    """휴무 요청 만족도를 분석합니다."""
    off_idx = roster_system.config.shift_types.index('OFF')
    total_requests = 0
    satisfied_requests = 0
    
    for nurse_id_str, days in data.get('off_requests', {}).items():
        nurse_id = int(nurse_id_str)
        nurse_idx = next((i for i, n in enumerate(roster_system.nurses) if n.id == nurse_id), None)
        
        if nurse_idx is None:
            continue
        
        for day_str in days:
            day = int(day_str)
            if 1 <= day <= roster_system.num_days:
                day_idx = day - 1
                total_requests += 1
                if roster_system.roster[nurse_idx, day_idx, off_idx] == 1:
                    satisfied_requests += 1
    
    if total_requests == 0:
        return 100.0
    return (satisfied_requests / total_requests) * 100.0

def analyze_shift_preferences_satisfaction(roster_system, data):
    """근무 유형 선호도 만족도를 분석합니다."""
    total_preferences = 0
    satisfied_preferences = 0
    
    for nurse_id_str, shifts in data.get('shift_preferences', {}).items():
        nurse_id = int(nurse_id_str)
        nurse_idx = next((i for i, n in enumerate(roster_system.nurses) if n.id == nurse_id), None)
        
        if nurse_idx is None:
            continue
        
        for shift_type, days in shifts.items():
            if shift_type not in roster_system.config.shift_types:
                continue
            
            shift_idx = roster_system.config.shift_types.index(shift_type)
            
            for day_str in days:
                day = int(day_str)
                if 1 <= day <= roster_system.num_days:
                    day_idx = day - 1
                    total_preferences += 1
                    if roster_system.roster[nurse_idx, day_idx, shift_idx] == 1:
                        satisfied_preferences += 1
    
    if total_preferences == 0:
        return 100.0
    return (satisfied_preferences / total_preferences) * 100.0

def run_test(filepath):
    """테스트를 실행하고 결과를 분석합니다."""
    data = load_data(filepath)
    roster_system = create_roster_system(data)
    
    # 최적화 실행
    time_limit = 60  # 60초 제한
    print(f"\n최적화 시작: {os.path.basename(filepath)}")
    print(f"shift_requirement_priority: {getattr(roster_system.config, 'shift_requirement_priority', 'not set')}")
    success = roster_system.optimize_roster_with_cp_sat(time_limit_seconds=time_limit)
    
    if not success:
        print(f"최적화 실패: {os.path.basename(filepath)}")
        return {
            'file': os.path.basename(filepath),
            'priority': getattr(roster_system.config, 'shift_requirement_priority', 'not set'),
            'requirements_satisfaction': 0.0,
            'off_requests_satisfaction': 0.0,
            'shift_preferences_satisfaction': 0.0,
            'success': False
        }
    
    # 결과 분석
    req_satisfaction = analyze_requirements_satisfaction(roster_system)
    off_satisfaction = analyze_off_requests_satisfaction(roster_system, data)
    shift_satisfaction = analyze_shift_preferences_satisfaction(roster_system, data)
    
    print(f"일일 근무 요구사항 만족도: {req_satisfaction:.2f}%")
    print(f"휴무 요청 만족도: {off_satisfaction:.2f}%")
    print(f"근무 유형 선호도 만족도: {shift_satisfaction:.2f}%")
    
    return {
        'file': os.path.basename(filepath),
        'priority': getattr(roster_system.config, 'shift_requirement_priority', 'not set'),
        'requirements_satisfaction': req_satisfaction,
        'off_requests_satisfaction': off_satisfaction,
        'shift_preferences_satisfaction': shift_satisfaction,
        'success': True
    }

def main():
    """모든 테스트 케이스에 대해 테스트를 실행합니다."""
    test_files = [
        'test_data_shift_small.json',  # Priority: 0.9 (High)
        'test_data_shift_medium.json', # Priority: 0.5 (Balanced)
        'test_data_shift_large.json',  # Priority: 0.2 (Low)
        'test_data_shift_conflict.json'  # Priority: 0.5 with conflicts
    ]
    
    results = []
    for filepath in test_files:
        result = run_test(filepath)
        results.append(result)
    
    # 결과 출력
    df = pd.DataFrame(results)
    print("\n\n결과 요약:")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 120)
    print(df)
    
    # 그래프로 시각화 (선택적)
    try:
        import matplotlib.pyplot as plt
        
        # 우선순위에 따른 만족도 플롯
        successful_results = [r for r in results if r['success']]
        if len(successful_results) > 0:
            priorities = [float(r['priority']) for r in successful_results]
            req_satisfaction = [r['requirements_satisfaction'] for r in successful_results]
            off_satisfaction = [r['off_requests_satisfaction'] for r in successful_results]
            shift_satisfaction = [r['shift_preferences_satisfaction'] for r in successful_results]
            
            plt.figure(figsize=(10, 6))
            plt.scatter(priorities, req_satisfaction, label='Requirements Satisfaction', marker='o', s=100)
            plt.scatter(priorities, off_satisfaction, label='OFF Requests Satisfaction', marker='s', s=100)
            plt.scatter(priorities, shift_satisfaction, label='Shift Preferences Satisfaction', marker='^', s=100)
            
            # 트렌드 라인 추가
            if len(priorities) > 1:
                z = np.polyfit(priorities, req_satisfaction, 1)
                p = np.poly1d(z)
                plt.plot(sorted(priorities), p(sorted(priorities)), "r--", alpha=0.5)
                
                z = np.polyfit(priorities, off_satisfaction, 1)
                p = np.poly1d(z)
                plt.plot(sorted(priorities), p(sorted(priorities)), "g--", alpha=0.5)
                
                z = np.polyfit(priorities, shift_satisfaction, 1)
                p = np.poly1d(z)
                plt.plot(sorted(priorities), p(sorted(priorities)), "b--", alpha=0.5)
            
            plt.xlabel('Shift Requirement Priority')
            plt.ylabel('Satisfaction Rate (%)')
            plt.title('Trade-off between Requirements and Preferences')
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.savefig('priority_vs_satisfaction.png')
            print("그래프가 'priority_vs_satisfaction.png'에 저장되었습니다.")
    except ImportError:
        print("matplotlib이 설치되어 있지 않아 그래프를 생성할 수 없습니다.")

if __name__ == "__main__":
    main() 