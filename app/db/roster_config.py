from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np

@dataclass
class NurseRosterConfig:
    """간호사 근무표 시스템 설정."""
    # 교대 근무 요구사항
    daily_shift_requirements: Dict[str, int] = None  # {'D': 3, 'E': 3, 'N': 2}
    
    # 경력 제약 조건
    min_experience_per_shift: int = 3  # 교대당 필요한 최소 경력 연수
    required_experienced_nurses: int = 1  # 교대당 필요한 경력 간호사 수
    
    # 야간 근무 제약 조건
    max_night_shifts_per_month: int = 15  # 월별 최대 야간 근무 수
    max_consecutive_nights: int = 3  # 최대 연속 야간 근무 수
    two_offs_after_three_nig: bool = False  # N 3회 후 OFF 2회 연속 필수
    two_offs_after_two_nig: bool = False  # N 2회 후 OFF 2회 연속 필수
    
    # 근무 패턴 제약 조건
    max_consecutive_work_days: int = 6  # 최대 연속 근무일 수
    enforce_two_offs_per_week: bool = False  # 주당 2일 휴무 적용 여부
    banned_day_after_eve: bool = True  # E → D 근무 금지 (법규)
    
    # 병원 내규 (소프트 제약)
    sequential_offs: bool = True  # OFF 연속 배정
    even_nights: bool = True  # N 개수 균등 배정
    nod_noe: bool = True  # N-O-D/E 패턴 최소화 적용 여부
    
    # 휴무일 관리
    global_monthly_off_days: int = 3  # 모든 간호사에게 적용되는 전체 휴무일(공휴일, 특별 휴무일)
    standard_personal_off_days: int = 8  # 간호사별 표준 개인 휴무일 수
    
    # 교대 배정 비율 - 각 교대 유형에 대한 선호도 가중치 제어
    day_shift_ratio: float = 1.0  # 주간 근무 비율
    evening_shift_ratio: float = 1.0  # 저녁 근무 비율
    night_shift_ratio: float = 1.0  # 야간 근무 비율
    off_shift_ratio: float = 1.2  # 휴무일 비율 (높을수록 휴무일 선호도 증가)
    
    # 선호도 행렬 가중치
    night_nurse_weight: float = 2.0  # 야간 간호사의 야간 근무 가중치
    experience_weight: float = 1.5  # 경력 간호사 가중치
    consecutive_shift_penalty: float = -1.0  # 원치 않는 연속 근무에 대한 패널티
    
    # 선호도 가중치
    shift_preference_weights: Dict[str, float] = field(default_factory=lambda: {
        'D': 5.0,  # 주간 근무 선호도 가중치
        'E': 5.0,  # 저녁 근무 선호도 가중치
        'N': 5.0,  # 야간 근무 선호도 가중치
        'OFF': 10.0  # 휴무 선호도 가중치
    })
    
    # 페어링 가중치
    pair_preference_weight: float = 3.0  # 페어링 선호도 반영 가중치
    # ── 프리셉터(페어) 보너스 항 제어 파라미터 ──
    preceptor_enable: bool = True                   # 프리셉터 보너스 항 사용 여부
    preceptor_strength_multiplier: float = 1.5      # 보너스 항 강도 배수
    preceptor_top_days: int = 30                    # 쌍별 상위 일수 K
    preceptor_min_pair_weight: float = 5.0          # 쌍 가중치 하한 필터
    preceptor_focus_shifts: Optional[List[str]] = None  # 특정 교대만 고려(e.g., ['N','E'])
    
    # --- 신규 Hard Constraint 제어 파라미터 ---
    enforce_seniority_pairing: bool = True # 시니어-주니어 동반 근무 규칙 강제 여부
    junior_pairing_max_experience: int = 2 # 주니어로 간주할 최대 연차
    senior_pairing_min_experience: int = 6 # 시니어로 간주할 최소 연차
    enforce_E_after_D_constraint: bool = True # E -> D 근무 금지 규칙 강제 여부
    
    # 소프트맥스 샘플링 온도
    sampling_temperature: float = 2.0
    
    # 근무 요구사항 우선순위 (0~1) - 1에 가까울수록 더 강하게 근무 요구사항 강제
    shift_requirement_priority: float = 0.8  # 근무 요구사항 우선순위
    
    def __post_init__(self):
        if self.daily_shift_requirements is None:
            self.daily_shift_requirements = {'D': 3, 'E': 3, 'N': 2}
            
    @property
    def shift_types(self) -> List[str]:
        """휴무일을 포함한 교대 유형 목록을 반환합니다."""
        return list(self.daily_shift_requirements.keys()) + ['O']
        
    @property
    def num_shifts(self) -> int:
        """휴무일을 포함한 교대 유형 수를 반환합니다."""
        return len(self.shift_types)
        
    def calculate_total_off_days(self, personal_off_adjustment: int = 0) -> int:
        """전체 및 개인 할당량을 기반으로 간호사의 총 휴무일을 계산합니다.
        
        Args:
            personal_off_adjustment: 표준 개인 휴무일에 대한 조정(양수 또는 음수 가능)
            
        Returns:
            월별 할당된 총 휴무일 수
        """
        return self.global_monthly_off_days + self.standard_personal_off_days + personal_off_adjustment

# 기본 설정
DEFAULT_CONFIG = NurseRosterConfig() 