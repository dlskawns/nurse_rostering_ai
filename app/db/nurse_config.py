from dataclasses import dataclass
from typing import List, Optional
from datetime import date, datetime, timedelta
import numpy as np
from functools import lru_cache
from services.holiday_pack import get_weekends   # ← 주말 헬퍼

# ────────────────────────────────────────────────────────────────
# 주말‑셋 캐시  (month 단위로 한 번만 계산)
@lru_cache(maxsize=None)
def _weekend_set(year: int, month: int) -> set[int]:
    """해당 월의 주말 날짜(1‑based)를 {0‑based day_idx} 로 반환."""
    return {d.day - 1 for d in get_weekends(year, month)}
# ────────────────────────────────────────────────────────────────
@dataclass
class Nurse:
    """간호사의 속성과 제약 조건을 나타내는 클래스."""
    id: int # RosterSystem 내부에서 사용하는 index
    name: str
    experience_years: float
    db_id: str # 데이터베이스의 원래 ID
    is_night_nurse: bool = False
    is_head_nurse: bool = False
    remaining_off_days: int = 0
    personal_off_adjustment: int = 0  # 이전 달에서 이월된 조정치(음수 또는 양수 가능)
    resignation_date: Optional[date] = None
    joining_date: Optional[date] = None
    head_nurse_off_pattern: Optional[str] = None  # 'weekend', 'mixed', 'normal'
    
    @classmethod
    def from_db_model(cls, db_nurse, index: int):
        return cls(
            id=index,
            db_id=db_nurse.nurse_id,
            name=db_nurse.name,
            experience_years=db_nurse.experience,
            is_night_nurse=db_nurse.is_night_nurse,
            is_head_nurse=db_nurse.is_head_nurse,
            personal_off_adjustment=db_nurse.personal_off_adjustment,
            resignation_date=db_nurse.resignation_date if db_nurse.resignation_date else None,
            joining_date=db_nurse.joining_date if db_nurse.joining_date else None
        )

    def __post_init__(self):
        if self.is_head_nurse and not self.head_nurse_off_pattern:
            self.head_nurse_off_pattern = 'weekend'  # 수간호사의 기본 패턴
            
    def calculate_available_off_days(self, config):
        """설정 및 개인 조정치를 기반으로 사용 가능한 총 휴무일을 계산합니다."""
        return config.calculate_total_off_days(self.personal_off_adjustment)
    
    def initialize_off_days(self, config):
        """설정을 기반으로 남은 휴무일을 초기화합니다."""
        self.remaining_off_days = self.calculate_available_off_days(config)
        return self.remaining_off_days
    
    def can_take_off(self, requested_days: int) -> bool:
        """간호사가 요청된 휴무일 수를 사용할 수 있는지 확인합니다."""
        return self.remaining_off_days >= requested_days
    
    def update_off_days(self, used_days: int):
        """사용 후 남은 휴무일을 업데이트합니다."""
        self.remaining_off_days -= used_days
        if self.remaining_off_days < 0:
            self.personal_off_adjustment = self.remaining_off_days  # 음수 잔액을 다음 달로 이월
            self.remaining_off_days = 0
        
    def get_shift_preferences(self, day_idx: int, month_days: int, config, weekend_days) -> np.ndarray:
        """주어진 날짜에 대한 교대 근무 선호도를 계산합니다.
        
        Returns:
            np.ndarray: 각 교대 유형에 대한 선호도 점수 [D, E, N, OFF]
        """
        preferences = np.ones(len(config.shift_types))
        
        # 설정에서 교대 배정 비율 적용

        d_idx = config.shift_types.index('D')
        evening_idx = config.shift_types.index('E')
        night_idx = config.shift_types.index('N')
        off_idx = config.shift_types.index('O')
        
        preferences[d_idx] *= config.day_shift_ratio
        preferences[evening_idx] *= config.evening_shift_ratio
        preferences[night_idx] *= config.night_shift_ratio
        preferences[off_idx] *= config.off_shift_ratio
        
        # 간호사 유형에 따른 기본 선호도
        if self.is_night_nurse:
            preferences[night_idx] *= config.night_nurse_weight
            preferences[evening_idx] *= config.night_nurse_weight * 0.2
            preferences[d_idx] *= 0.2  # 주간 근무 비선호
            
        # ── ★ 수간호사 weekend 선호 보정 (개선된 주말 판별) ──────
        if self.is_head_nurse:
           if self.head_nurse_off_pattern == 'weekend' and day_idx in weekend_days:
                preferences[:]     = 0.1
                preferences[off_idx] = 2.0
                
        return preferences
        
    def __str__(self) -> str:
        return f"Nurse(id={self.id}, name={self.name}, exp={self.experience_years}yrs, night={self.is_night_nurse})" 