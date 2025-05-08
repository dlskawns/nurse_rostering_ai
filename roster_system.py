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
            off_requests: Dict mapping nurse IDs to lists of requested off days (1-based)
        """
        for nurse_id, days in off_requests.items():
            nurse_idx = next(i for i, n in enumerate(self.nurses) if n.id == nurse_id)
            nurse = self.nurses[nurse_idx]
            
            # Filter days to only include those within the month
            valid_days = [d - 1 for d in days if 1 <= d <= self.num_days]  # Convert to 0-based indexing
            
            if not valid_days:
                continue
            
            if not nurse.can_take_off(len(valid_days)):
                print(f"Warning: Nurse {nurse.name} doesn't have enough off days "
                      f"(requested: {len(valid_days)}, available: {nurse.remaining_off_days})")
                continue
            
            off_idx = self.config.shift_types.index('OFF')
            for day in valid_days:
                if np.any(self.roster[nurse_idx, day]):
                    # Remove existing assignment
                    self.roster[nurse_idx, day] = 0
                self.roster[nurse_idx, day, off_idx] = 1
                
            nurse.update_off_days(len(valid_days))
            
    def _get_constraint_weights(self) -> Dict[str, float]:
        """Get weights for different types of constraints."""
        return {
            'experience': 1.0,  # Experience requirements
            'night': 0.9,      # Night shift constraints
            'consecutive': 0.8, # Consecutive work days
            'shift_requirement': 0.7,  # Daily shift requirements
            'off_pattern': 0.6  # Off day patterns
        }

    def _calculate_violation_score(self, violations: List[dict]) -> float:
        """Calculate weighted violation score."""
        weights = self._get_constraint_weights()
        score = 0.0
        
        for violation in violations:
            weight = weights.get(violation['type'], 0.5)
            if violation['type'] == 'shift_requirement':
                # Score based on how far from required number
                diff = abs(violation['required'] - violation['actual'])
                score += weight * diff
            else:
                score += weight
                
        return score

    def optimize_roster_weighted(self, max_iterations: int = 1000, improvement_threshold: float = 0.001):
        """Optimize roster using weighted constraint satisfaction."""
        print("\nStarting weighted roster optimization...")
        start_time = time.time()
        iteration = 0
        best_score = float('inf')
        best_roster = None
        
        while iteration < max_iterations:
            current_violations = self._find_violations()
            current_score = self._calculate_violation_score(current_violations)
            
            if current_score < best_score:
                if best_score - current_score < improvement_threshold:
                    print(f"Minimal improvement after {iteration} iterations")
                    break
                    
                best_score = current_score
                best_roster = self.roster.copy()
                
            if current_score == 0:
                print("Perfect solution found!")
                break
                
            # Sort violations by weight and fix highest priority first
            weights = self._get_constraint_weights()
            sorted_violations = sorted(
                current_violations,
                key=lambda v: weights.get(v['type'], 0.5),
                reverse=True
            )
            
            for violation in sorted_violations:
                self._fix_violation(violation)
                
            if iteration % 100 == 0:
                print(f"Iteration {iteration}: Score = {current_score:.4f}")
                
            iteration += 1
            
        if best_roster is not None and best_score < self._calculate_violation_score(self._find_violations()):
            self.roster = best_roster
            
        total_time = time.time() - start_time
        print(f"Optimization completed in {total_time:.4f} seconds")
        print(f"Final score: {best_score:.4f}")
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

    def calculate_metrics(self) -> Dict:
        """Calculate roster metrics and statistics.
        
        Returns:
            Dict containing various roster metrics
        """
        metrics = {}
        
        # Shift distribution metrics
        shift_counts = {shift: 0 for shift in self.config.shift_types}
        nurse_shift_counts = {nurse.name: {shift: 0 for shift in self.config.shift_types} 
                             for nurse in self.nurses}
        
        unassigned_slots = 0
        staffing_violations = 0
        experience_violations = 0
        
        for day in range(self.num_days):
            # Check staffing requirements
            for shift in ['D', 'E', 'N']:
                shift_idx = self.config.shift_types.index(shift)
                assigned = np.sum(self.roster[:, day, shift_idx])
                required = self.config.daily_shift_requirements[shift]
                
                if assigned < required:
                    staffing_violations += 1
                    
            # Check experience requirements
            exp_violations = 0
            for shift in ['D', 'E', 'N']:
                shift_idx = self.config.shift_types.index(shift)
                exp_nurses = sum(
                    1 for n_idx, nurse in enumerate(self.nurses)
                    if (nurse.experience_years >= self.config.min_experience_per_shift and
                        self.roster[n_idx, day, shift_idx] == 1)
                )
                if exp_nurses < self.config.required_experienced_nurses:
                    exp_violations += 1
            experience_violations += exp_violations
            
            # Count shifts per nurse
            for n_idx, nurse in enumerate(self.nurses):
                assigned = False
                for shift in self.config.shift_types:
                    shift_idx = self.config.shift_types.index(shift)
                    if self.roster[n_idx, day, shift_idx] == 1:
                        shift_counts[shift] += 1
                        nurse_shift_counts[nurse.name][shift] += 1
                        assigned = True
                if not assigned:
                    unassigned_slots += 1
                    
        # Calculate weekend distribution
        weekend_shifts = {nurse.name: 0 for nurse in self.nurses}
        for day in range(self.num_days):
            if self._is_weekend(day):
                for n_idx, nurse in enumerate(self.nurses):
                    if np.any(self.roster[n_idx, day, :-1]):  # Exclude OFF shifts
                        weekend_shifts[nurse.name] += 1
                        
        # Calculate consecutive work days violations
        consecutive_violations = 0
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                if not self._check_consecutive_work_days(n_idx, day):
                    consecutive_violations += 1
                    
        # Calculate night shift violations
        night_violations = 0
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                if not self._check_night_constraints(n_idx, day):
                    night_violations += 1
                    
        # Compile metrics
        metrics['shift_distribution'] = shift_counts
        metrics['nurse_shift_counts'] = nurse_shift_counts
        metrics['unassigned_slots'] = unassigned_slots
        metrics['staffing_violations'] = staffing_violations
        metrics['experience_violations'] = experience_violations
        metrics['consecutive_violations'] = consecutive_violations
        metrics['night_violations'] = night_violations
        metrics['weekend_distribution'] = weekend_shifts
        
        return metrics

    def _is_weekend(self, day):
        """Check if given day is weekend."""
        return day % 7 >= 5

    def _initialize_roster(self):
        """Initialize roster with zeros."""
        self.roster = np.zeros((len(self.nurses), self.num_days, self.config.num_shifts))

    def _assign_shift(self, nurse_idx: int, day: int, shift: str):
        """Assign a shift to a nurse, clearing any existing assignments."""
        # Clear all shifts for this day first
        self.roster[nurse_idx, day] = 0
        # Then assign the new shift
        shift_idx = self.config.shift_types.index(shift)
        self.roster[nurse_idx, day, shift_idx] = 1 

    def calculate_detailed_metrics(self) -> Dict:
        """Calculate detailed metrics for roster evaluation."""
        metrics = {
            'constraint_violations': self._count_constraint_violations(),
            'workload_distribution': self._analyze_workload_distribution(),
            'shift_patterns': self._analyze_shift_patterns(),
            'nurse_satisfaction': self._estimate_nurse_satisfaction(),
            'coverage_metrics': self._analyze_coverage(),
            'fairness_metrics': self._analyze_fairness()
        }
        return metrics
        
    def _count_constraint_violations(self) -> Dict:
        """Count different types of constraint violations."""
        violations = self._find_violations()
        counts = {}
        for v in violations:
            v_type = v['type']
            counts[v_type] = counts.get(v_type, 0) + 1
        return counts
        
    def _analyze_workload_distribution(self) -> Dict:
        """Analyze the distribution of workload among nurses."""
        workloads = {}
        for n_idx, nurse in enumerate(self.nurses):
            shifts = {
                'total': np.sum(self.roster[n_idx, :, :-1]),  # Exclude OFF
                'day': np.sum(self.roster[n_idx, :, self.config.shift_types.index('D')]),
                'evening': np.sum(self.roster[n_idx, :, self.config.shift_types.index('E')]),
                'night': np.sum(self.roster[n_idx, :, self.config.shift_types.index('N')]),
                'off': np.sum(self.roster[n_idx, :, self.config.shift_types.index('OFF')])
            }
            workloads[nurse.name] = shifts
            
        return {
            'per_nurse': workloads,
            'statistics': {
                'mean_shifts': np.mean([w['total'] for w in workloads.values()]),
                'std_shifts': np.std([w['total'] for w in workloads.values()]),
                'min_shifts': min(w['total'] for w in workloads.values()),
                'max_shifts': max(w['total'] for w in workloads.values())
            }
        }
        
    def _analyze_shift_patterns(self) -> Dict:
        """Analyze patterns in shift assignments."""
        patterns = {
            'consecutive_shifts': self._analyze_consecutive_shifts(),
            'weekend_distribution': self._analyze_weekend_distribution(),
            'shift_transitions': self._analyze_shift_transitions()
        }
        return patterns
        
    def _analyze_consecutive_shifts(self) -> Dict:
        """Analyze consecutive shift patterns."""
        consecutive_counts = {
            'day': [],     # For 'D' shift
            'evening': [], # For 'E' shift
            'night': [],   # For 'N' shift
            'off': []      # For 'OFF' shift
        }
        
        # Map shift types to dictionary keys
        shift_map = {
            'D': 'day',
            'E': 'evening',
            'N': 'night',
            'OFF': 'off'
        }
        
        for n_idx in range(len(self.nurses)):
            for shift in self.config.shift_types:
                shift_idx = self.config.shift_types.index(shift)
                assignments = self.roster[n_idx, :, shift_idx]
                
                # Count consecutive assignments
                count = 0
                max_consecutive = 0
                for day in range(self.num_days):
                    if assignments[day]:
                        count += 1
                        max_consecutive = max(max_consecutive, count)
                    else:
                        count = 0
                
                # Use the mapping to get the correct key
                key = shift_map.get(shift, 'other')
                consecutive_counts[key].append(max_consecutive)
                
        return {
            shift: {
                'max': max(counts) if counts else 0,
                'avg': np.mean(counts) if counts else 0,
                'std': np.std(counts) if counts else 0
            }
            for shift, counts in consecutive_counts.items()
        }
        
    def _analyze_weekend_distribution(self) -> Dict:
        """Analyze the distribution of weekend shifts."""
        weekend_stats = {
            'per_nurse': {},
            'overall': {'total_weekends': 0, 'nurses_per_weekend': []}
        }
        
        try:
            for n_idx, nurse in enumerate(self.nurses):
                weekend_count = 0
                for day in range(self.num_days):
                    if self._is_weekend(day) and np.any(self.roster[n_idx, day, :-1]):
                        weekend_count += 1
                weekend_stats['per_nurse'][nurse.name] = weekend_count
                
            # Calculate nurses per weekend
            for day in range(self.num_days):
                if self._is_weekend(day):
                    weekend_stats['overall']['total_weekends'] += 1
                    nurses_working = sum(
                        1 for n_idx in range(len(self.nurses))
                        if np.any(self.roster[n_idx, day, :-1])
                    )
                    weekend_stats['overall']['nurses_per_weekend'].append(nurses_working)
        except Exception as e:
            print(f"Warning: Error calculating weekend distribution: {e}")
            # Return empty stats if there's an error
            return {
                'per_nurse': {},
                'overall': {'total_weekends': 0, 'nurses_per_weekend': []}
            }
                
        return weekend_stats
        
    def _analyze_shift_transitions(self) -> Dict:
        """Analyze transitions between different shifts."""
        transitions = {
            f"{s1}->{s2}": 0
            for s1 in self.config.shift_types
            for s2 in self.config.shift_types
        }
        
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - 1):
                try:
                    # Find which shift is assigned for current day
                    current_shifts = np.where(self.roster[n_idx, day] == 1)[0]
                    next_shifts = np.where(self.roster[n_idx, day + 1] == 1)[0]
                    
                    if len(current_shifts) > 0 and len(next_shifts) > 0:
                        current = current_shifts[0]
                        next_day = next_shifts[0]
                        
                        transition = f"{self.config.shift_types[current]}->{self.config.shift_types[next_day]}"
                        transitions[transition] += 1
                except IndexError:
                    # Skip if there's any missing assignment
                    continue
                    
        return transitions
        
    def _estimate_nurse_satisfaction(self) -> Dict:
        """Estimate nurse satisfaction based on preferences and assignments."""
        satisfaction = {}
        
        for n_idx, nurse in enumerate(self.nurses):
            matches = 0
            total = 0
            
            for day in range(self.num_days):
                assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                pref_score = self.preference_matrix[n_idx, day, assigned_shift]
                matches += pref_score
                total += 1
                
            satisfaction[nurse.name] = {
                'score': matches / total if total > 0 else 0,
                'preferred_shifts_ratio': matches / total if total > 0 else 0
            }
            
        return {
            'per_nurse': satisfaction,
            'average': np.mean([s['score'] for s in satisfaction.values()])
        }
        
    def _analyze_coverage(self) -> Dict:
        """Analyze shift coverage and staffing levels."""
        coverage = {
            'daily': {},
            'overall': {}
        }
        
        for day in range(self.num_days):
            coverage['daily'][day] = {}
            for shift in self.config.shift_types[:-1]:  # Exclude OFF
                shift_idx = self.config.shift_types.index(shift)
                required = self.config.daily_shift_requirements[shift]
                actual = np.sum(self.roster[:, day, shift_idx])
                coverage['daily'][day][shift] = {
                    'required': required,
                    'actual': actual,
                    'difference': actual - required
                }
                
        # Calculate overall statistics
        for shift in self.config.shift_types[:-1]:
            shift_idx = self.config.shift_types.index(shift)
            required_total = self.config.daily_shift_requirements[shift] * self.num_days
            actual_total = np.sum(self.roster[:, :, shift_idx])
            coverage['overall'][shift] = {
                'required_total': required_total,
                'actual_total': actual_total,
                'coverage_ratio': actual_total / required_total if required_total > 0 else 1.0
            }
            
        return coverage
        
    def _analyze_fairness(self) -> Dict:
        """Analyze fairness in shift distribution."""
        fairness = {
            'shift_distribution': {},
            'weekend_fairness': {},
            'workload_balance': {}
        }
        
        # Analyze shift type distribution
        for shift in self.config.shift_types[:-1]:
            shift_idx = self.config.shift_types.index(shift)
            assignments = [
                np.sum(self.roster[n_idx, :, shift_idx])
                for n_idx in range(len(self.nurses))
            ]
            fairness['shift_distribution'][shift] = {
                'gini_coefficient': self._calculate_gini(assignments),
                'coefficient_of_variation': np.std(assignments) / np.mean(assignments) if np.mean(assignments) > 0 else 0
            }
            
        return fairness
        
    def _calculate_gini(self, array: List[float]) -> float:
        """Calculate Gini coefficient as a measure of inequality."""
        array = np.array(array)
        if np.all(array == 0):
            return 0
        array = array.flatten()
        if np.amin(array) < 0:
            array -= np.amin(array)
        array += 0.0000001
        array = np.sort(array)
        index = np.arange(1, array.shape[0] + 1)
        n = array.shape[0]
        return ((np.sum((2 * index - n - 1) * array)) / (n * np.sum(array)))

    def optimize_roster_with_cp_sat(self, time_limit_seconds=30):
        """Optimize the roster using CP-SAT global constraint solver.
        
        This approach models all constraints simultaneously and finds a globally optimal solution.
        """
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("Error: OR-Tools is not installed. Please install it with: pip install ortools")
            return False
            
        print("\nStarting global optimization with CP-SAT solver...")
        start_time = time.time()
        
        # Create the model
        model = cp_model.CpModel()
        
        # 1. Define variables
        # x[nurse, day, shift] = 1 if nurse is assigned to shift on day
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{shift}')
        
        # Generate a solution hint from current roster
        # Note: Instead of using SetHint which might not be available in all versions,
        # we'll use the hint parameter when creating variables
        solution_hint = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                try:
                    assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                    for s_idx in range(len(self.config.shift_types)):
                        if s_idx == assigned_shift:
                            model.AddHint(x[n_idx, day, s_idx], 1)
                        else:
                            model.AddHint(x[n_idx, day, s_idx], 0)
                except:
                    # If no assignment is found, skip hint
                    pass

        # 2. Add exactly-one constraint: each nurse must be assigned exactly one shift per day
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(len(self.config.shift_types)))
        
        # 3. Add staffing requirements
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                # Sum of nurses assigned to this shift must equal required number
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses))) == required)
        
        # 4. Add experience requirements
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                # Sum of experienced nurses assigned to this shift
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                # Must have at least the required number of experienced nurses
                model.Add(exp_nurses_assigned >= self.config.required_experienced_nurses)
        
        # 5. Night nurse constraints - night nurses CANNOT work day shifts (HARD constraint)
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    # Force day shift assignment to be 0 for night nurses
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 6. Add consecutive work days constraint
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_work_days + 1):
                # If nurse works max_consecutive_work_days days in a row, must have a day off
                consecutive_work = []
                for d in range(day, day + self.config.max_consecutive_work_days):
                    # Working = any shift except OFF
                    off_idx = self.config.shift_types.index('OFF') 
                    work_vars = [x[n_idx, d, s_idx] for s_idx in range(len(self.config.shift_types)) if s_idx != off_idx]
                    is_working = model.NewBoolVar(f'n{n_idx}_d{d}_working')
                    model.AddMaxEquality(is_working, work_vars)
                    consecutive_work.append(is_working)
                
                # Can't have all consecutive_work days be true
                model.Add(sum(consecutive_work) < len(consecutive_work))
        
        # 7. Add night shift constraints
        night_idx = self.config.shift_types.index('N')
        day_idx = self.config.shift_types.index('D')
        
        # 7.1 Max consecutive nights
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days - self.config.max_consecutive_nights):
                # Can't have more than max_consecutive_nights in a row
                consecutive_nights = [x[n_idx, d, night_idx] for d in range(day, day + self.config.max_consecutive_nights + 1)]
                model.Add(sum(consecutive_nights) <= self.config.max_consecutive_nights)
        
        # 7.2 No day shift after night shift
        for n_idx in range(len(self.nurses)):
            for day in range(1, self.num_days):
                # If worked night shift yesterday, can't work day shift today
                model.Add(x[n_idx, day, day_idx] <= 1 - x[n_idx, day-1, night_idx])
        
        # 7.3 Monthly night shift limit
        for n_idx in range(len(self.nurses)):
            total_nights = sum(x[n_idx, day, night_idx] for day in range(self.num_days))
            model.Add(total_nights <= self.config.max_night_shifts_per_month)
        
        # 8. Head nurse weekend pattern
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_head_nurse:
                off_idx = self.config.shift_types.index('OFF')
                
                if nurse.head_nurse_off_pattern == 'weekend':
                    # Weekend days must be OFF
                    for day in range(self.num_days):
                        if self._is_weekend(day):
                            model.Add(x[n_idx, day, off_idx] == 1)
                            
                elif nurse.head_nurse_off_pattern == 'mixed':
                    # Every other weekend must be OFF
                    for day in range(self.num_days):
                        if self._is_weekend(day) and day % 14 >= 7:
                            model.Add(x[n_idx, day, off_idx] == 1)
        
        # 9. Handle resignation dates
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.resignation_date:
                resignation_day = (nurse.resignation_date - self.target_month).days
                if 0 <= resignation_day < self.num_days:
                    off_idx = self.config.shift_types.index('OFF')
                    for day in range(resignation_day, self.num_days):
                        model.Add(x[n_idx, day, off_idx] == 1)
        
        # 10. Objective function: maximize preference satisfaction
        objective_terms = []
        
        # 10.1 Preference satisfaction
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    # Scale preference to integer (CP-SAT needs integer coefficients)
                    pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 100)
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # 10.2 Night nurse specialization bonus
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                # Bonus for night nurses working night shifts
                night_bonus = sum(200 * x[n_idx, day, night_idx] for day in range(self.num_days))
                objective_terms.append(night_bonus)
        
        # 10.3 Workload balance penalty - Simplified to avoid non-affine expressions
        # Calculate total work days for each nurse directly
        off_idx = self.config.shift_types.index('OFF')
        
        # Create workday count variables for each nurse
        work_days = {}
        for n_idx in range(len(self.nurses)):
            # Count non-OFF shifts for each nurse
            work_shifts = [
                x[n_idx, day, s_idx] 
                for day in range(self.num_days) 
                for s_idx in range(len(self.config.shift_types)) 
                if s_idx != off_idx
            ]
            work_days[n_idx] = model.NewIntVar(0, self.num_days, f'work_days_n{n_idx}')
            model.Add(work_days[n_idx] == sum(work_shifts))
        
        # Add fairness constraints - target at least min_work_days per nurse
        min_work_days = (self.num_days * sum(self.config.daily_shift_requirements.values())) // (len(self.nurses) * 2)
        for n_idx in range(len(self.nurses)):
            # Encourage at least minimum workdays
            objective_terms.append(50 * work_days[n_idx])
            # But penalize excessive workdays
            excess_var = model.NewIntVar(0, self.num_days, f'excess_n{n_idx}')
            model.Add(excess_var >= work_days[n_idx] - (self.num_days - min_work_days))
            objective_terms.append(-100 * excess_var)  # Penalize excess
        
        # Set the objective
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.log_search_progress = True
        
        # Solve the model
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract the solution
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Clear current assignments
                    self.roster[n_idx, day] = 0
                    # Set new assignment
                    for s_idx in range(len(self.config.shift_types)):
                        if solver.Value(x[n_idx, day, s_idx]) == 1:
                            self.roster[n_idx, day, s_idx] = 1
                            break
            
            print(f"Optimization completed in {time.time() - start_time:.2f} seconds")
            print(f"Objective value: {solver.ObjectiveValue()}")
            
            if status == cp_model.OPTIMAL:
                print("Found optimal solution!")
            else:
                print("Found feasible solution (may not be optimal)")
                
            return True
        else:
            print("No solution found.")
            return False
        
    def optimize_with_lns(self, max_iterations=10, time_limit_per_iteration=10):
        """Optimize roster using Large Neighborhood Search.
        
        This approach keeps part of the roster fixed and re-optimizes
        a selected part using CP-SAT, gradually improving the solution.
        """
        print("\nStarting optimization with Large Neighborhood Search...")
        start_time = time.time()
        
        best_roster = self.roster.copy()
        best_violations = len(self._find_violations())
        
        for iteration in range(max_iterations):
            print(f"\nLNS Iteration {iteration+1}/{max_iterations}")
            
            # Keep a copy of the current roster
            current_roster = self.roster.copy()
            
            # Randomly select a subset of days and nurses to re-optimize
            days_to_optimize = np.random.choice(range(self.num_days), 
                                              size=min(7, self.num_days), 
                                              replace=False)
            nurses_to_optimize = np.random.choice(range(len(self.nurses)), 
                                               size=min(5, len(self.nurses)), 
                                               replace=False)
            
            print(f"Re-optimizing days {sorted(days_to_optimize)} for {len(nurses_to_optimize)} nurses...")
            
            # Fix assignments for non-selected days and nurses
            fixed_assignments = []
            for n_idx in range(len(self.nurses)):
                if n_idx not in nurses_to_optimize:
                    for day in range(self.num_days):
                        shift_idx = np.where(self.roster[n_idx, day] == 1)[0][0]
                        fixed_assignments.append((n_idx, day, shift_idx))
                else:
                    for day in range(self.num_days):
                        if day not in days_to_optimize:
                            shift_idx = np.where(self.roster[n_idx, day] == 1)[0][0]
                            fixed_assignments.append((n_idx, day, shift_idx))
            
            # Run CP-SAT on this neighborhood
            success = self._optimize_neighborhood(fixed_assignments, time_limit_per_iteration)
            
            if success:
                # Count violations after optimization
                new_violations = len(self._find_violations())
                print(f"Violations: {best_violations} -> {new_violations}")
                
                if new_violations < best_violations:
                    best_violations = new_violations
                    best_roster = self.roster.copy()
                    print("Solution improved!")
                else:
                    # Rollback if no improvement
                    self.roster = current_roster
                    print("No improvement, rolling back changes")
            else:
                # Rollback if optimization failed
                self.roster = current_roster
                print("Optimization failed, rolling back changes")
        
        # Always use the best roster found
        self.roster = best_roster
        
        print(f"LNS completed in {time.time() - start_time:.2f} seconds")
        print(f"Final violations: {best_violations}")
        return best_violations == 0
        
    def _optimize_neighborhood(self, fixed_assignments, time_limit_seconds):
        """Optimize a neighborhood of the roster with some assignments fixed."""
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("Error: OR-Tools is not installed")
            return False
            
        # Create the model
        model = cp_model.CpModel()
        
        # Define variables
        x = {}
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx, shift in enumerate(self.config.shift_types):
                    x[n_idx, day, s_idx] = model.NewBoolVar(f'n{n_idx}_d{day}_s{shift}')
        
        # Fix the specified assignments
        for n_idx, day, s_idx in fixed_assignments:
            model.Add(x[n_idx, day, s_idx] == 1)
        
        # Generate hints from current roster for non-fixed assignments
        try:
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Skip if this is a fixed assignment
                    is_fixed = any((n_idx, day, _) in fixed_assignments for _ in range(len(self.config.shift_types)))
                    if not is_fixed:
                        assigned_shift = np.where(self.roster[n_idx, day] == 1)[0][0]
                        for s_idx in range(len(self.config.shift_types)):
                            if s_idx == assigned_shift:
                                model.AddHint(x[n_idx, day, s_idx], 1)
                            else:
                                model.AddHint(x[n_idx, day, s_idx], 0)
        except:
            # If there's any error with hints, just proceed without them
            pass
            
        # Add constraints
        
        # 1. Add exactly-one constraint
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                model.AddExactlyOne(x[n_idx, day, s_idx] for s_idx in range(len(self.config.shift_types)))
        
        # 2. Add staffing requirements
        for day in range(self.num_days):
            for shift, required in self.config.daily_shift_requirements.items():
                s_idx = self.config.shift_types.index(shift)
                model.Add(sum(x[n_idx, day, s_idx] for n_idx in range(len(self.nurses))) == required)
        
        # 3. Add experience requirements
        for day in range(self.num_days):
            for shift in ['D', 'E', 'N']:
                s_idx = self.config.shift_types.index(shift)
                # Sum of experienced nurses assigned to this shift
                exp_nurses_assigned = sum(
                    x[n_idx, day, s_idx] 
                    for n_idx, nurse in enumerate(self.nurses) 
                    if nurse.experience_years >= self.config.min_experience_per_shift
                )
                model.Add(exp_nurses_assigned >= self.config.required_experienced_nurses)
                
        # 4. Night nurse constraints - CANNOT work day shifts
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                d_idx = self.config.shift_types.index('D')
                for day in range(self.num_days):
                    model.Add(x[n_idx, day, d_idx] == 0)
        
        # 5. Add other necessary constraints (simplified)
        
        # Set the objective (simplified from the full version)
        objective_terms = []
        
        # Preference satisfaction
        for n_idx in range(len(self.nurses)):
            for day in range(self.num_days):
                for s_idx in range(len(self.config.shift_types)):
                    pref_score = int(self.preference_matrix[n_idx, day, s_idx] * 100)
                    objective_terms.append(pref_score * x[n_idx, day, s_idx])
        
        # Night nurse specialization bonus
        night_idx = self.config.shift_types.index('N')
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_night_nurse:
                night_bonus = sum(200 * x[n_idx, day, night_idx] for day in range(self.num_days))
                objective_terms.append(night_bonus)
        
        # Workload balance (simplified)
        off_idx = self.config.shift_types.index('OFF')
        for n_idx in range(len(self.nurses)):
            # Encourage working
            work_shifts = [
                x[n_idx, day, s_idx] 
                for day in range(self.num_days) 
                for s_idx in range(len(self.config.shift_types)) 
                if s_idx != off_idx
            ]
            objective_terms.append(25 * sum(work_shifts))
        
        model.Maximize(sum(objective_terms))
        
        # Create a solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        
        # Solve the model
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract the solution
            for n_idx in range(len(self.nurses)):
                for day in range(self.num_days):
                    # Clear current assignments
                    self.roster[n_idx, day] = 0
                    # Set new assignment
                    for s_idx in range(len(self.config.shift_types)):
                        if solver.Value(x[n_idx, day, s_idx]) == 1:
                            self.roster[n_idx, day, s_idx] = 1
                            break
            return True
        else:
            return False 