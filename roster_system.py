from typing import List, Dict, Tuple, Optional
import numpy as np
from datetime import date, datetime, timedelta
import calendar
import time
from config import NurseRosterConfig, DEFAULT_CONFIG
from nurse import Nurse

class RosterSystem:
    """Main class for nurse roster generation and management."""
    
    def __init__(
        self,
        nurses: List[Nurse],
        target_month: date,
        config: NurseRosterConfig = DEFAULT_CONFIG
    ):
        print("\nInitializing RosterSystem...")
        start_time = time.time()
        
        self.nurses = nurses
        self.target_month = target_month
        self.config = config
        self.num_days = calendar.monthrange(target_month.year, target_month.month)[1]
        
        # Initialize roster matrix: [nurses × days × shifts]
        self.roster = np.zeros((len(nurses), self.num_days, config.num_shifts))
        self.preference_matrix = np.zeros_like(self.roster)
        
        # Initialize preference matrix
        self._initialize_preferences()
        
        print(f"Initialization completed in {time.time() - start_time:.4f} seconds")
        
    def _initialize_preferences(self):
        """Initialize the preference matrix for all nurses and days."""
        print("Calculating preference matrix...")
        start_time = time.time()
        
        for n_idx, nurse in enumerate(self.nurses):
            for day in range(self.num_days):
                self.preference_matrix[n_idx, day] = nurse.get_shift_preferences(
                    day, self.num_days, self.config
                )
                
        print(f"Preference matrix calculation completed in {time.time() - start_time:.4f} seconds")
        
    def _check_night_constraints(self, nurse_idx: int, day: int) -> bool:
        """Check night shift related constraints for a nurse."""
        if day < 2:  # Not enough history to check
            return True
            
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        
        # Check consecutive nights
        if day >= self.config.max_consecutive_nights:
            consecutive_nights = np.all(
                self.roster[nurse_idx, day-self.config.max_consecutive_nights:day, night_idx] == 1
            )
            if consecutive_nights:
                return False
                
        # Check N followed by D
        if day > 0 and self.roster[nurse_idx, day-1, night_idx] == 1:
            if self.roster[nurse_idx, day, day_idx] == 1:
                return False
                
        # Check monthly night shift limit
        total_nights = np.sum(self.roster[nurse_idx, :day+1, night_idx])
        if total_nights >= self.config.max_night_shifts_per_month:
            return False
            
        return True
        
    def _check_consecutive_work_days(self, nurse_idx: int, day: int) -> bool:
        """Check if adding a shift would violate consecutive work days constraint."""
        if day < self.config.max_consecutive_work_days:
            return True
            
        off_idx = self.config.shift_types.index('OFF')
        work_days = np.sum(
            self.roster[nurse_idx, day-self.config.max_consecutive_work_days:day, :off_idx], 
            axis=1
        )
        return not np.all(work_days > 0)
        
    def _check_experience_requirements(self, day: int) -> bool:
        """Check if experience requirements are met for each shift."""
        experienced_nurses = [n for n in self.nurses if n.experience_years >= self.config.min_experience_per_shift]
        
        for shift in ['D', 'E', 'N']:
            shift_idx = self.config.shift_types.index(shift)
            exp_count = sum(
                1 for n_idx, nurse in enumerate(experienced_nurses)
                if self.roster[n_idx, day, shift_idx] == 1
            )
            if exp_count < self.config.required_experienced_nurses:
                return False
        return True
        
    def _apply_softmax_sampling(self, preferences: np.ndarray) -> int:
        """Apply softmax sampling to get shift assignment."""
        exp_prefs = np.exp(preferences * self.config.sampling_temperature)
        probs = exp_prefs / np.sum(exp_prefs)
        return np.random.choice(len(preferences), p=probs)
        
    def generate_initial_roster(self):
        """Generate initial roster using softmax sampling of preferences."""
        print("\nGenerating initial roster...")
        print(f"Target month: {self.target_month.strftime('%B %Y')}")
        print(f"Number of nurses: {len(self.nurses)}")
        print(f"Number of days: {self.num_days}")
        print(f"Shift requirements: {self.config.daily_shift_requirements}")
        
        start_time = time.time()
        assignments = 0
        
        for day in range(self.num_days):
            for shift in self.config.daily_shift_requirements:
                shift_idx = self.config.shift_types.index(shift)
                required = self.config.daily_shift_requirements[shift]
                
                # Get available nurses for this shift
                available_nurses = [
                    (n_idx, nurse) for n_idx, nurse in enumerate(self.nurses)
                    if not np.any(self.roster[n_idx, day]) and  # Not already assigned
                    self._check_night_constraints(n_idx, day) and
                    self._check_consecutive_work_days(n_idx, day)
                ]
                
                # Assign shifts using softmax sampling
                for _ in range(required):
                    if not available_nurses:
                        print(f"Warning: Not enough available nurses for {shift} shift on day {day + 1}")
                        break
                        
                    # Calculate assignment probabilities
                    probs = np.array([
                        self.preference_matrix[n_idx, day, shift_idx]
                        for n_idx, _ in available_nurses
                    ])
                    
                    # Sample nurse
                    selected_idx = self._apply_softmax_sampling(probs)
                    nurse_idx, _ = available_nurses.pop(selected_idx)
                    
                    # Assign shift
                    self.roster[nurse_idx, day, shift_idx] = 1
                    assignments += 1
                    
        print(f"Initial roster generation completed in {time.time() - start_time:.4f} seconds")
        print(f"Total assignments made: {assignments}")
        
    def apply_off_requests(self, off_requests: Dict[int, List[int]]):
        """Apply off day requests from nurses.
        
        Args:
            off_requests: Dict mapping nurse IDs to lists of requested off days
        """
        for nurse_id, days in off_requests.items():
            nurse_idx = next(i for i, n in enumerate(self.nurses) if n.id == nurse_id)
            nurse = self.nurses[nurse_idx]
            
            if not nurse.can_take_off(len(days)):
                raise ValueError(f"Nurse {nurse.name} doesn't have enough off days")
                
            off_idx = self.config.shift_types.index('OFF')
            for day in days:
                if np.any(self.roster[nurse_idx, day]):
                    # Remove existing assignment
                    self.roster[nurse_idx, day] = 0
                self.roster[nurse_idx, day, off_idx] = 1
                
            nurse.update_off_days(len(days))
            
    def optimize_roster(self, max_iterations: int = 1000):
        """Optimize roster by fixing constraint violations."""
        print("\nStarting roster optimization...")
        start_time = time.time()
        iteration = 0
        
        while iteration < max_iterations:
            violations = self._find_violations()
            if not violations:
                print(f"No violations found after {iteration} iterations")
                break
                
            if iteration % 100 == 0:
                print(f"Iteration {iteration}: Found {len(violations)} violations")
                
            for violation in violations:
                self._fix_violation(violation)
                
            iteration += 1
            
        total_time = time.time() - start_time
        print(f"Optimization completed in {total_time:.4f} seconds")
        print(f"Total iterations: {iteration}")
        
    def _find_violations(self) -> List[dict]:
        """Find all constraint violations in current roster."""
        violations = []
        
        # Check each type of violation
        for day in range(self.num_days):
            # Check shift requirements
            for shift, required in self.config.daily_shift_requirements.items():
                shift_idx = self.config.shift_types.index(shift)
                actual = np.sum(self.roster[:, day, shift_idx])
                if actual != required:
                    violations.append({
                        'type': 'shift_requirement',
                        'day': day,
                        'shift': shift,
                        'required': required,
                        'actual': actual
                    })
                    
            # Check experience requirements
            if not self._check_experience_requirements(day):
                violations.append({
                    'type': 'experience',
                    'day': day
                })
                
        # Check nurse-specific constraints
        for n_idx, nurse in enumerate(self.nurses):
            for day in range(self.num_days):
                if not self._check_night_constraints(n_idx, day):
                    violations.append({
                        'type': 'night',
                        'nurse_idx': n_idx,
                        'day': day
                    })
                if not self._check_consecutive_work_days(n_idx, day):
                    violations.append({
                        'type': 'consecutive',
                        'nurse_idx': n_idx,
                        'day': day
                    })
                    
        return violations
        
    def _fix_violation(self, violation: dict):
        """Fix a specific constraint violation."""
        if violation['type'] == 'shift_requirement':
            self._fix_shift_requirement(violation)
        elif violation['type'] == 'experience':
            self._fix_experience_requirement(violation)
        elif violation['type'] == 'night':
            self._fix_night_constraint(violation)
        elif violation['type'] == 'consecutive':
            self._fix_consecutive_constraint(violation)
            
    def _fix_shift_requirement(self, violation: dict):
        """Fix shift requirement violation by swapping assignments."""
        day = violation['day']
        shift = violation['shift']
        shift_idx = self.config.shift_types.index(shift)
        
        if violation['actual'] < violation['required']:
            # Need more nurses for this shift
            available_nurses = [
                n_idx for n_idx, nurse in enumerate(self.nurses)
                if not np.any(self.roster[n_idx, day]) and
                self._check_night_constraints(n_idx, day) and
                self._check_consecutive_work_days(n_idx, day)
            ]
            
            if available_nurses:
                # Assign available nurse with highest preference
                prefs = [self.preference_matrix[n_idx, day, shift_idx] for n_idx in available_nurses]
                best_nurse = available_nurses[np.argmax(prefs)]
                self.roster[best_nurse, day, shift_idx] = 1
        else:
            # Too many nurses for this shift
            assigned_nurses = np.where(self.roster[:, day, shift_idx] == 1)[0]
            # Remove nurse with lowest preference
            prefs = [self.preference_matrix[n_idx, day, shift_idx] for n_idx in assigned_nurses]
            worst_nurse = assigned_nurses[np.argmin(prefs)]
            self.roster[worst_nurse, day, shift_idx] = 0
            
    def _fix_experience_requirement(self, violation: dict):
        """Fix experience requirement violation by swapping nurses."""
        day = violation['day']
        
        # Find experienced and inexperienced nurses working this day
        experienced_nurses = [
            (n_idx, nurse) for n_idx, nurse in enumerate(self.nurses)
            if nurse.experience_years >= self.config.min_experience_per_shift
        ]
        
        # Check each shift type
        for shift in ['D', 'E', 'N']:
            shift_idx = self.config.shift_types.index(shift)
            
            # Count experienced nurses in this shift
            exp_count = sum(
                1 for n_idx, _ in experienced_nurses
                if self.roster[n_idx, day, shift_idx] == 1
            )
            
            # If we need more experienced nurses
            while exp_count < self.config.required_experienced_nurses:
                # Find available experienced nurse
                available_exp = [
                    n_idx for n_idx, _ in experienced_nurses
                    if not np.any(self.roster[n_idx, day]) and
                    self._check_night_constraints(n_idx, day) and
                    self._check_consecutive_work_days(n_idx, day)
                ]
                
                if not available_exp:
                    # Try to swap with inexperienced nurse
                    working_inexperienced = [
                        n_idx for n_idx, nurse in enumerate(self.nurses)
                        if nurse.experience_years < self.config.min_experience_per_shift and
                        self.roster[n_idx, day, shift_idx] == 1
                    ]
                    
                    if working_inexperienced and available_exp:
                        # Swap an inexperienced nurse with an experienced one
                        inexp_idx = working_inexperienced[0]
                        exp_idx = available_exp[0]
                        
                        # Remove inexperienced nurse
                        self.roster[inexp_idx, day, shift_idx] = 0
                        # Add experienced nurse
                        self.roster[exp_idx, day, shift_idx] = 1
                        exp_count += 1
                    else:
                        break
                else:
                    # Add available experienced nurse
                    exp_idx = available_exp[0]
                    self.roster[exp_idx, day, shift_idx] = 1
                    exp_count += 1
                    
    def _fix_night_constraint(self, violation: dict):
        """Fix night shift constraint violation."""
        nurse_idx = violation['nurse_idx']
        day = violation['day']
        night_idx = self.config.shift_types.index('N')
        
        # If this creates consecutive nights or exceeds monthly limit
        if not self._check_night_constraints(nurse_idx, day):
            # Remove the night shift
            self.roster[nurse_idx, day, night_idx] = 0
            
            # Try to assign to another nurse
            available_nurses = [
                n_idx for n_idx, nurse in enumerate(self.nurses)
                if n_idx != nurse_idx and
                not np.any(self.roster[n_idx, day]) and
                self._check_night_constraints(n_idx, day) and
                self._check_consecutive_work_days(n_idx, day)
            ]
            
            if available_nurses:
                # Choose nurse with highest night shift preference
                prefs = [self.preference_matrix[n_idx, day, night_idx] for n_idx in available_nurses]
                best_nurse = available_nurses[np.argmax(prefs)]
                self.roster[best_nurse, day, night_idx] = 1
                
    def _fix_consecutive_constraint(self, violation: dict):
        """Fix consecutive work days constraint violation."""
        nurse_idx = violation['nurse_idx']
        day = violation['day']
        off_idx = self.config.shift_types.index('OFF')
        
        # Find the day in the consecutive sequence to make OFF
        if day >= self.config.max_consecutive_work_days:
            # Look at the previous max_consecutive_work_days days
            window = self.roster[nurse_idx, 
                               day-self.config.max_consecutive_work_days:day+1, 
                               :off_idx]
            
            # Find the day with lowest preference sum
            day_prefs = np.sum(window * self.preference_matrix[nurse_idx, 
                                                             day-self.config.max_consecutive_work_days:day+1, 
                                                             :off_idx], 
                             axis=1)
            worst_day_rel = np.argmin(day_prefs)
            worst_day = day - self.config.max_consecutive_work_days + worst_day_rel
            
            # Clear all assignments for that day
            self.roster[nurse_idx, worst_day] = 0
            # Set as OFF day
            self.roster[nurse_idx, worst_day, off_idx] = 1

    def get_roster_matrix(self) -> np.ndarray:
        """Return the current roster matrix."""
        return self.roster
        
    def print_roster(self):
        """Print current roster in readable format."""
        shift_map = {i: s for i, s in enumerate(self.config.shift_types)}
        
        print(f"\nRoster for {self.target_month.strftime('%B %Y')}:")
        print("=" * 50)
        print("Nurse".ljust(20), end="")
        for day in range(self.num_days):
            print(f"{day+1:2}", end=" ")
        print("\n" + "-" * 50)
        
        for n_idx, nurse in enumerate(self.nurses):
            print(f"{nurse.name[:19].ljust(20)}", end="")
            for day in range(self.num_days):
                shift_idx = np.where(self.roster[n_idx, day] == 1)[0]
                if len(shift_idx) == 0:
                    print(" - ", end="")
                else:
                    print(f" {shift_map[shift_idx[0]]} ", end="")
            print() 