from dataclasses import dataclass
from typing import List, Optional
from datetime import date, datetime, timedelta
import numpy as np

@dataclass
class Nurse:
    """Class representing a nurse with their properties and constraints."""
    id: int
    name: str
    experience_years: float
    is_night_nurse: bool = False
    is_head_nurse: bool = False
    remaining_off_days: int = 0
    carried_off_days: int = 0  # Can be negative or positive
    resignation_date: Optional[date] = None
    head_nurse_off_pattern: Optional[str] = None  # 'weekend', 'mixed', 'normal'
    
    def __post_init__(self):
        if self.is_head_nurse and not self.head_nurse_off_pattern:
            self.head_nurse_off_pattern = 'weekend'  # Default pattern for head nurse
            
    def can_take_off(self, requested_days: int) -> bool:
        """Check if nurse can take requested number of off days."""
        return self.remaining_off_days >= requested_days
    
    def update_off_days(self, used_days: int):
        """Update remaining off days after usage."""
        self.remaining_off_days -= used_days
        if self.remaining_off_days < 0:
            self.carried_off_days = self.remaining_off_days
            self.remaining_off_days = 0
        
    def get_shift_preferences(self, day_idx: int, month_days: int, config) -> np.ndarray:
        """Calculate shift preferences for a given day.
        
        Returns:
            np.ndarray: Preference scores for each shift type [D, E, N, OFF]
        """
        preferences = np.ones(len(config.shift_types))
        
        # Basic preferences based on nurse type
        if self.is_night_nurse:
            preferences[config.shift_types.index('N')] *= config.night_nurse_weight
            preferences[config.shift_types.index('E')] *= config.night_nurse_weight * 0.8
            preferences[config.shift_types.index('D')] *= 0.2  # Discourage day shifts
            
        # Head nurse preferences
        if self.is_head_nurse:
            is_weekend = day_idx % 7 >= 5  # Saturday or Sunday
            if self.head_nurse_off_pattern == 'weekend' and is_weekend:
                preferences[:] = 0.1  # Discourage all shifts
                preferences[config.shift_types.index('OFF')] = 2.0
            elif self.head_nurse_off_pattern == 'mixed':
                if is_weekend and day_idx % 14 >= 7:  # Every other weekend
                    preferences[:] = 0.1
                    preferences[config.shift_types.index('OFF')] = 2.0
                    
        # Handle resignation date
        if self.resignation_date:
            current_date = date(2024, 1, 1) + timedelta(days=day_idx)  # Example base date
            if current_date >= self.resignation_date:
                preferences[:] = 0.0
                preferences[config.shift_types.index('OFF')] = 1.0
                
        return preferences
        
    def __str__(self) -> str:
        return f"Nurse(id={self.id}, name={self.name}, exp={self.experience_years}yrs, night={self.is_night_nurse})" 