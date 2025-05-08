from datetime import date, datetime, timedelta
import json
import time
import pandas as pd
import numpy as np
from config import NurseRosterConfig
from nurse import Nurse
from roster_system import RosterSystem
from typing import List, Optional

class Timer:
    """Context manager for timing code blocks."""
    def __init__(self, description):
        self.description = description
        
    def __enter__(self):
        self.start = time.time()
        print(f"\n{self.description}...")
        return self
        
    def __exit__(self, *args):
        self.end = time.time()
        self.duration = self.end - self.start
        print(f"{self.description} completed in {self.duration:.2f} seconds")

def load_test_data(filename):
    """Load test data from JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)

def create_nurses_from_data(nurses_data):
    """Create nurse objects from JSON data."""
    nurses = []
    for nurse_data in nurses_data:
        # Convert resignation_date to datetime if present
        if 'resignation_date' in nurse_data:
            nurse_data['resignation_date'] = datetime.strptime(
                nurse_data['resignation_date'], '%Y-%m-%d'
            ).date()
        nurses.append(Nurse(**nurse_data))
    return nurses

def export_roster_to_excel(roster_system, filename):
    """Export roster to Excel with metrics."""
    # Create shift assignment DataFrame
    days = pd.date_range(
        start=roster_system.target_month,
        periods=roster_system.num_days,
        freq='D'
    )
    
    # Initialize empty DataFrame
    df = pd.DataFrame(index=days, columns=[n.name for n in roster_system.nurses])
    
    # Fill in shift assignments
    for day in range(roster_system.num_days):
        date = days[day]
        for n_idx, nurse in enumerate(roster_system.nurses):
            shift_idx = np.where(roster_system.roster[n_idx, day] == 1)[0]
            if len(shift_idx) > 0:
                df.iloc[day, n_idx] = roster_system.config.shift_types[shift_idx[0]]
            else:
                df.iloc[day, n_idx] = '-'
                
    # Add day of week
    df.insert(0, 'Day', df.index.strftime('%a'))
    
    # Save to Excel
    df.to_excel(filename, sheet_name='Roster', index=True)
    print(f"\nRoster exported to {filename}")
    
    # Add metrics sheet
    with pd.ExcelWriter(filename, mode='a', engine='openpyxl') as writer:
        metrics = roster_system.calculate_metrics()
        metrics_df = pd.DataFrame(metrics).T
        metrics_df.to_excel(writer, sheet_name='Metrics')

class RosterGenerator:
    def __init__(self, roster_system):
        self.roster_system = roster_system
        self.nurses = roster_system.nurses
        self.config = roster_system.config
        self.num_days = roster_system.num_days
        # Initialize all days as OFF
        self.roster_system._initialize_roster()
        
    def _is_weekend(self, day):
        """Check if given day is weekend."""
        return day % 7 >= 5
        
    def _get_available_nurses(self, day, exclude_nurses=None):
        """Get nurses available for work on given day."""
        exclude_nurses = exclude_nurses or set()
        available = []
        
        for n_idx, nurse in enumerate(self.nurses):
            if n_idx in exclude_nurses:
                continue
                
            # Check if nurse already has assignment
            if np.any(self.roster_system.roster[n_idx, day]):
                continue
                
            # Check consecutive work days
            if not self.roster_system._check_consecutive_work_days(n_idx, day):
                continue
                
            # Check night shift constraints
            if not self.roster_system._check_night_constraints(n_idx, day):
                continue
                
            available.append(n_idx)
            
        return available
        
    def _assign_shift(self, nurse_idx, day, shift):
        """Assign a shift to a nurse."""
        # Clear any existing assignments for this day (including OFF)
        self.roster_system.roster[nurse_idx, day] = 0
        # Assign the new shift
        shift_idx = self.config.shift_types.index(shift)
        self.roster_system.roster[nurse_idx, day, shift_idx] = 1
        
    def _get_shift_preference(self, nurse_idx, day, shift):
        """Get nurse's preference for a shift."""
        shift_idx = self.config.shift_types.index(shift)
        return self.roster_system.preference_matrix[nurse_idx, day, shift_idx]
        
    def generate_roster(self):
        """Generate roster with improved constraints handling."""
        print("\nGenerating roster with prioritized constraints...")
        
        # Step 1: Pre-assign OFF days
        self._assign_off_days()
        
        # Step 2: Pre-assign night shifts to night nurses
        self._assign_night_shifts()
        
        # Step 3: Assign remaining shifts (D and E) with better balancing
        for week in range((self.num_days + 6) // 7):
            start_day = week * 7
            end_day = min(start_day + 7, self.num_days)
            self._assign_day_evening_shifts_for_week(start_day, end_day)
        
        # Step 4: Fill any remaining gaps
        self._fill_gaps()
        
    def _assign_off_days(self):
        """Pre-assign OFF days based on patterns and requests."""
        print("Assigning OFF days...")
        off_idx = self.config.shift_types.index('OFF')
        
        for n_idx, nurse in enumerate(self.nurses):
            # Handle head nurse weekend pattern
            if nurse.is_head_nurse:
                for day in range(self.num_days):
                    if self._is_weekend(day):
                        if nurse.head_nurse_off_pattern == 'weekend':
                            self.roster_system.roster[n_idx, day, off_idx] = 1
                        elif nurse.head_nurse_off_pattern == 'mixed' and day % 14 >= 7:
                            self.roster_system.roster[n_idx, day, off_idx] = 1
                            
            # Handle resignation dates
            if nurse.resignation_date:
                resignation_day = (nurse.resignation_date - self.roster_system.target_month).days
                if 0 <= resignation_day < self.num_days:
                    for day in range(resignation_day, self.num_days):
                        self.roster_system.roster[n_idx, day, off_idx] = 1
                        
    def _assign_night_shifts(self):
        """Assign night shifts prioritizing night nurses."""
        print("Assigning night shifts...")
        
        # Sort nurses by night shift preference
        night_nurses = [(n_idx, nurse) for n_idx, nurse in enumerate(self.nurses) 
                       if nurse.is_night_nurse]
        other_nurses = [(n_idx, nurse) for n_idx, nurse in enumerate(self.nurses) 
                       if not nurse.is_night_nurse]
        
        for day in range(self.num_days):
            required = self.config.daily_shift_requirements['N']
            assigned = 0
            
            # First try to assign night nurses
            for n_idx, nurse in night_nurses:
                if assigned >= required:
                    break
                    
                if self._can_assign_shift(n_idx, day, 'N'):
                    self._assign_shift(n_idx, day, 'N')
                    assigned += 1
                    
            # If still need more, use other nurses
            if assigned < required:
                available = [
                    n_idx for n_idx, _ in other_nurses
                    if self._can_assign_shift(n_idx, day, 'N')
                ]
                
                for n_idx in available:
                    if assigned >= required:
                        break
                    self._assign_shift(n_idx, day, 'N')
                    assigned += 1

    def _check_staffing_requirements(self, day):
        """Check if staffing requirements are met for a given day."""
        requirements_met = True
        messages = []
        
        for shift in ['D', 'E', 'N']:
            shift_idx = self.config.shift_types.index(shift)
            required = self.config.daily_shift_requirements[shift]
            assigned = np.sum(self.roster_system.roster[:, day, shift_idx])
            
            if assigned < required:
                requirements_met = False
                messages.append(f"Need {required - assigned} more nurses for {shift} shift")
                
            # Check experienced nurse requirement
            exp_nurses = sum(
                1 for n_idx, nurse in enumerate(self.nurses)
                if (nurse.experience_years >= self.config.min_experience_per_shift and
                    self.roster_system.roster[n_idx, day, shift_idx] == 1)
            )
            
            if exp_nurses < self.config.required_experienced_nurses:
                requirements_met = False
                messages.append(
                    f"Need {self.config.required_experienced_nurses - exp_nurses} "
                    f"more experienced nurses for {shift} shift"
                )
                
        return requirements_met, messages

    def _get_shift_priority(self, nurse, shift, day):
        """Calculate priority score for assigning a nurse to a shift.
        
        Args:
            nurse: Nurse object
            shift: Shift type ('D', 'E', 'N')
            day: Day index
            
        Returns:
            float: Priority score (higher means more suitable)
        """
        priority = 1.0
        
        # Base priority by nurse type and shift
        if nurse.is_night_nurse:
            if shift == 'N':
                priority *= 2.5  # Increased priority for night nurses on night shifts
            elif shift == 'D':
                priority *= 0.1  # Strongly discourage day shifts for night nurses
            elif shift == 'E':
                priority *= 0.3  # Evening shifts are slightly better than day shifts
        else:
            if shift == 'N':
                priority *= 0.5  # Lower priority for non-night nurses on night shifts
            
        # Experience-based priority
        if nurse.experience_years >= self.config.min_experience_per_shift:
            priority *= 1.5
            # Extra boost for experienced nurses when we need them
            exp_nurses = sum(1 for n in self.nurses 
                            if (n.experience_years >= self.config.min_experience_per_shift and
                                np.any(self.roster_system.roster[self.nurses.index(n), day])))
            if exp_nurses < self.config.required_experienced_nurses:
                priority *= 1.3
            
        # Workload balancing
        nurse_idx = self.nurses.index(nurse)
        total_shifts = np.sum(self.roster_system.roster[nurse_idx, :day])
        avg_shifts = np.mean([np.sum(self.roster_system.roster[i, :day]) 
                             for i in range(len(self.nurses))])
        if total_shifts < avg_shifts:
            priority *= 1.2  # Boost priority for nurses with fewer shifts
        
        # Weekend handling
        if self._is_weekend(day):
            weekend_shifts = sum(1 for d in range(day) 
                               if self._is_weekend(d) and 
                               np.any(self.roster_system.roster[nurse_idx, d]))
            if weekend_shifts == 0:
                priority *= 1.2  # Boost priority for nurses who haven't worked weekends
            
        return priority

    def _calculate_fatigue_score(self, nurse_idx: int, day: int) -> float:
        """Calculate fatigue score for a nurse based on recent work history."""
        if day < 1:
            return 0.0
            
        # Look back up to 7 days
        lookback = min(day, 7)
        recent_work = self.roster_system.roster[nurse_idx, day-lookback:day]
        
        # Calculate weighted sum of recent work days
        weights = np.exp(-np.arange(lookback) * 0.5)  # Exponential decay
        work_days = np.sum(recent_work, axis=1) > 0
        fatigue = np.sum(work_days * weights) / np.sum(weights)
        
        return fatigue
        
    def _calculate_assignment_score(self, nurse_idx: int, nurse: Nurse, day: int, shift: str) -> float:
        """Calculate overall score for assigning a nurse to a shift."""
        shift_idx = self.config.shift_types.index(shift)
        score = 0.0
        
        # Base preference score (0-1)
        pref_score = self._get_shift_preference(nurse_idx, day, shift)
        score += 0.4 * pref_score  # 40% weight
        
        # Fatigue score (0-1, inverted so less fatigue is better)
        fatigue = self._calculate_fatigue_score(nurse_idx, day)
        score += 0.3 * (1 - fatigue)  # 30% weight
        
        # Experience bonus for complex shifts
        if shift in ['N', 'E'] and nurse.experience_years >= self.config.min_experience_per_shift:
            score += 0.15  # 15% weight
            
        # Specialization bonus
        if (shift == 'N' and nurse.is_night_nurse) or \
           (nurse.is_head_nurse and shift in ['D', 'E']):
            score += 0.15  # 15% weight
            
        return score

    def _assign_nurses_to_shift(self, day: int, shift: str, required: int) -> List[int]:
        """Assign nurses to a shift using improved scoring system."""
        assigned = []
        available = self._get_available_nurses(day)
        
        if not available:
            return assigned
            
        # Calculate scores for all available nurses
        scores = []
        for n_idx in available:
            if not self._can_assign_shift(n_idx, day, shift):
                continue
            score = self._calculate_assignment_score(n_idx, self.nurses[n_idx], day, shift)
            scores.append((n_idx, score))
            
        # Sort by score and assign best matches
        scores.sort(key=lambda x: x[1], reverse=True)
        for n_idx, _ in scores[:required]:
            self._assign_shift(n_idx, day, shift)
            assigned.append(n_idx)
            
        return assigned

    def _assign_day_evening_shifts_for_week(self, start_day: int, end_day: int):
        """Assign day and evening shifts for a week with improved balancing."""
        shifts = ['D', 'E']
        days = range(start_day, end_day)
        
        # First pass: assign based on preferences and scores
        for day in days:
            for shift in shifts:
                required = self.config.daily_shift_requirements[shift]
                self._assign_nurses_to_shift(day, shift, required)
                
        # Second pass: balance workload within the week
        self._balance_weekly_workload(start_day, end_day)
        
    def _balance_weekly_workload(self, start_day: int, end_day: int):
        """Balance workload within a week to avoid overwork."""
        shifts = ['D', 'E']
        
        # Calculate weekly workload for each nurse
        workloads = {}
        for n_idx, nurse in enumerate(self.nurses):
            work_days = 0
            for day in range(start_day, end_day):
                if np.any(self.roster_system.roster[n_idx, day, :-1]):  # Exclude OFF
                    work_days += 1
            workloads[n_idx] = work_days
            
        # Identify overworked nurses (more than 5 days in the week)
        overworked = [n_idx for n_idx, days in workloads.items() if days > 5]
        
        # Try to redistribute some shifts
        for n_idx in overworked:
            for day in range(start_day, end_day):
                for shift in shifts:
                    shift_idx = self.config.shift_types.index(shift)
                    if self.roster_system.roster[n_idx, day, shift_idx] == 1:
                        # Try to find a replacement
                        replacement = self._find_replacement(n_idx, day, shift)
                        if replacement is not None:
                            # Swap assignments
                            self._assign_shift(replacement, day, shift)
                            self.roster_system.roster[n_idx, day] = 0
                            break
                            
    def _find_replacement(self, current_nurse_idx: int, day: int, shift: str) -> Optional[int]:
        """Find a replacement nurse for a shift assignment."""
        available = self._get_available_nurses(day, {current_nurse_idx})
        
        best_score = -1
        best_nurse = None
        
        for n_idx in available:
            if not self._can_assign_shift(n_idx, day, shift):
                continue
                
            score = self._calculate_assignment_score(n_idx, self.nurses[n_idx], day, shift)
            if score > best_score:
                best_score = score
                best_nurse = n_idx
                
        return best_nurse

    def _fill_gaps(self):
        """Fill any remaining gaps in the roster."""
        print("Filling remaining gaps in roster...")
        
        for day in range(self.num_days):
            # Find unassigned nurses
            unassigned = [
                idx for idx in range(len(self.nurses))
                if not np.any(self.roster_system.roster[idx, day])
            ]
            
            # Set them to OFF
            off_idx = self.config.shift_types.index('OFF')
            for idx in unassigned:
                self.roster_system.roster[idx, day, off_idx] = 1

    def _can_assign_shift(self, nurse_idx, day, shift):
        """Check if a nurse can be assigned to a shift."""
        # Check if already assigned
        if np.any(self.roster_system.roster[nurse_idx, day]):
            return False
        
        nurse = self.nurses[nurse_idx]
        
        # Night nurse restrictions
        if nurse.is_night_nurse and shift in ['D', 'E']:
            return False
        
        # Check consecutive work days
        if not self.roster_system._check_consecutive_work_days(nurse_idx, day):
            return False
        
        # Check night shift constraints
        if shift == 'N' and not self.roster_system._check_night_constraints(nurse_idx, day):
            return False
        
        # Check head nurse weekend pattern
        if (nurse.is_head_nurse and nurse.head_nurse_off_pattern == 'weekend' and
            self._is_weekend(day)):
            return False
        
        return True

def main():
    print("\n=== Starting Nurse Rostering System V2 with Global Optimization ===")
    
    # Install OR-Tools if not already installed
    try:
        import ortools
    except ImportError:
        print("\nInstalling OR-Tools...")
        import subprocess
        subprocess.check_call(["pip", "install", "ortools"])
    
    # Load test data
    with Timer("Loading test data"):
        data = load_test_data('test_data.json')
        
    # Create configuration
    with Timer("Creating configuration"):
        config = NurseRosterConfig(**data['config'])
        print(f"Configured shift requirements: {config.daily_shift_requirements}")
        
    # Create nurses
    with Timer("Creating nurse objects"):
        nurses = create_nurses_from_data(data['nurses'])
        print(f"Created {len(nurses)} nurse objects")
        
    # Create roster system
    with Timer("Initializing roster system"):
        target_month = datetime.strptime(data['target_month'], '%Y-%m-%d').date()
        roster_system = RosterSystem(
            nurses=nurses,
            target_month=target_month,
            config=config
        )
        print(f"Initialized roster system for {target_month.strftime('%B %Y')}")
    
    # Apply off requests first (as hard constraints)
    with Timer("Applying off requests"):
        off_requests = {int(k): v for k, v in data['off_requests'].items()}
        roster_system.apply_off_requests(off_requests)
        print(f"Applied {len(off_requests)} off requests")
    
    # Generate initial roster using the RosterGenerator for seeding
    with Timer("Generating initial roster for seeding"):
        generator = RosterGenerator(roster_system)
        generator.generate_roster()
        
    # Optimize globally using CP-SAT
    with Timer("Optimizing roster with CP-SAT (Global optimization)"):
        success = roster_system.optimize_roster_with_cp_sat(time_limit_seconds=60)
        if success:
            print("Global optimization successful!")
        else:
            print("Global optimization failed, falling back to LNS approach...")
            # If global optimization failed, try LNS
            with Timer("Refining with Large Neighborhood Search"):
                success = roster_system.optimize_with_lns(max_iterations=5, time_limit_per_iteration=20)
                if success:
                    print("LNS refinement successful!")
                else:
                    print("LNS refinement completed with some remaining violations.")
    
    # Calculate and print metrics
    with Timer("Calculating detailed metrics"):
        try:
            detailed_metrics = roster_system.calculate_detailed_metrics()
            violations = detailed_metrics.get('constraint_violations', {})
            
            print("\n=== Constraint Violations ===")
            if not violations:
                print("No violations found! Perfect solution achieved.")
            else:
                for violation_type, count in violations.items():
                    print(f"{violation_type}: {count}")
                
            if 'workload_distribution' in detailed_metrics and 'statistics' in detailed_metrics['workload_distribution']:
                workload = detailed_metrics['workload_distribution']['statistics']
                print(f"\nWorkload statistics:")
                print(f"  Average shifts per nurse: {workload.get('mean_shifts', 0):.2f}")
                print(f"  Min shifts: {workload.get('min_shifts', 0)}, Max shifts: {workload.get('max_shifts', 0)}")
            
            if 'nurse_satisfaction' in detailed_metrics:
                satisfaction = detailed_metrics['nurse_satisfaction'].get('average', 0)
                print(f"\nAverage nurse satisfaction score: {satisfaction:.2f}")
        except Exception as e:
            print(f"Error calculating detailed metrics: {e}")
            # Calculate basic metrics instead
            basic_metrics = roster_system.calculate_metrics()
            print("\n=== Basic Metrics ===")
            for key, value in basic_metrics.items():
                if not isinstance(value, dict):
                    print(f"{key}: {value}")
    
    # Print final roster
    print("\n=== Final Roster ===")
    roster_system.print_roster()
    
    # Export to Excel with metrics
    with Timer("Exporting results"):
        export_roster_to_excel(roster_system, 'roster_v2.xlsx')
        print("Results exported to roster_v2.xlsx")
        
        # Export detailed metrics to a separate file if they were calculated
        try:
            if 'detailed_metrics' in locals() and detailed_metrics:
                with open('detailed_metrics.json', 'w') as f:
                    import json
                    json.dump(detailed_metrics, f, indent=2, default=lambda x: float(x) if isinstance(x, np.float32) else x)
                print("Detailed metrics exported to detailed_metrics.json")
            else:
                # Export basic metrics instead
                basic_metrics = roster_system.calculate_metrics()
                with open('basic_metrics.json', 'w') as f:
                    import json
                    json.dump(basic_metrics, f, indent=2, default=lambda x: float(x) if isinstance(x, np.float32) else x)
                print("Basic metrics exported to basic_metrics.json")
        except Exception as e:
            print(f"Error exporting metrics: {e}")
    
if __name__ == "__main__":
    main() 