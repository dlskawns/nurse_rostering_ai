from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np

@dataclass
class NurseRosterConfig:
    """Configuration for nurse rostering system."""
    # Shift requirements
    daily_shift_requirements: Dict[str, int] = None  # {'D': 3, 'E': 3, 'N': 2}
    
    # Career constraints
    min_experience_per_shift: int = 3  # Minimum years of experience required per shift
    required_experienced_nurses: int = 1  # Number of experienced nurses required per shift
    
    # Night shift constraints
    max_night_shifts_per_month: int = 15
    max_consecutive_nights: int = 2
    
    # Work pattern constraints
    max_consecutive_work_days: int = 6
    enforce_two_offs_per_week: bool = False
    
    # Weights for preference matrix
    night_nurse_weight: float = 2.0  # Higher weight for night nurses for night shifts
    experience_weight: float = 1.5  # Weight for experienced nurses
    consecutive_shift_penalty: float = -1.0  # Penalty for undesired consecutive shifts
    
    # Softmax temperature for sampling
    sampling_temperature: float = 2.0
    
    def __post_init__(self):
        if self.daily_shift_requirements is None:
            self.daily_shift_requirements = {'D': 3, 'E': 3, 'N': 2}
            
    @property
    def shift_types(self) -> List[str]:
        """Return list of shift types including OFF."""
        return list(self.daily_shift_requirements.keys()) + ['OFF']
        
    @property
    def num_shifts(self) -> int:
        """Return number of shift types including OFF."""
        return len(self.shift_types)

# Default configuration
DEFAULT_CONFIG = NurseRosterConfig() 