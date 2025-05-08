"""
Test script for validating the CP-SAT implementation of nurse rostering.
"""

import time
from datetime import datetime
import json
import numpy as np
from config import NurseRosterConfig
from nurse import Nurse
from roster_system import RosterSystem
from main_v2 import create_nurses_from_data, export_roster_to_excel

def test_cp_sat_algorithm():
    """Test the CP-SAT algorithm with a small dataset."""
    print("\n=== Testing CP-SAT Nurse Rostering Algorithm ===")
    
    # Load test data
    print("Loading test data...")
    with open('test_data.json', 'r') as f:
        data = json.load(f)
    
    # Create config
    config = NurseRosterConfig(**data['config'])
    print(f"Shift requirements: {config.daily_shift_requirements}")
    
    # Create nurses
    nurses = create_nurses_from_data(data['nurses'])
    print(f"Created {len(nurses)} nurse objects")
    
    # Create roster system
    target_month = datetime.strptime(data['target_month'], '%Y-%m-%d').date()
    roster_system = RosterSystem(
        nurses=nurses,
        target_month=target_month,
        config=config
    )
    
    # Apply off requests
    off_requests = {int(k): v for k, v in data['off_requests'].items()}
    roster_system.apply_off_requests(off_requests)
    
    # Run CP-SAT optimization
    print("\nRunning CP-SAT optimization...")
    start_time = time.time()
    success = roster_system.optimize_roster_with_cp_sat(time_limit_seconds=20)
    optimization_time = time.time() - start_time
    
    print(f"Optimization completed in {optimization_time:.2f} seconds")
    print(f"Success: {success}")
    
    # Validate key constraints
    print("\nValidating key constraints...")
    
    # 1. Check night nurse constraint (night nurses never assigned to day shifts)
    night_nurse_violations = 0
    day_idx = config.shift_types.index('D')
    
    for n_idx, nurse in enumerate(nurses):
        if nurse.is_night_nurse:
            for day in range(roster_system.num_days):
                if roster_system.roster[n_idx, day, day_idx] == 1:
                    night_nurse_violations += 1
    
    # 2. Check staffing requirements
    staffing_violations = 0
    for day in range(roster_system.num_days):
        for shift, required in config.daily_shift_requirements.items():
            shift_idx = config.shift_types.index(shift)
            assigned = np.sum(roster_system.roster[:, day, shift_idx])
            if assigned != required:
                staffing_violations += 1
    
    # 3. Check experience requirements
    exp_violations = 0
    for day in range(roster_system.num_days):
        if not roster_system._check_experience_requirements(day):
            exp_violations += 1
    
    # Report validation results
    print("\n=== Constraint Validation Results ===")
    print(f"Night nurse day shift violations: {night_nurse_violations}")
    print(f"Staffing requirement violations: {staffing_violations}")
    print(f"Experience requirement violations: {exp_violations}")
    
    # Calculate overall metrics
    metrics = roster_system.calculate_detailed_metrics()
    
    print("\n=== Workload Distribution ===")
    workload = metrics['workload_distribution']['statistics']
    print(f"Average shifts per nurse: {workload['mean_shifts']:.2f}")
    print(f"Standard deviation: {workload['std_shifts']:.2f}")
    print(f"Min shifts: {workload['min_shifts']}, Max shifts: {workload['max_shifts']}")
    
    print("\n=== Nurse Satisfaction ===")
    satisfaction = metrics['nurse_satisfaction']['average']
    print(f"Average satisfaction score: {satisfaction:.2f}")
    
    # Export the roster for visual inspection
    export_roster_to_excel(roster_system, 'cp_sat_test_result.xlsx')
    print("\nTest roster exported to cp_sat_test_result.xlsx")
    
    return night_nurse_violations == 0 and staffing_violations == 0 and exp_violations == 0

if __name__ == "__main__":
    test_cp_sat_algorithm() 