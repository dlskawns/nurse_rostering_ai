"""
Simple test script for verifying the CP-SAT nurse rostering implementation.
Tests only the core functionality with minimal dependencies.
"""

import time
from datetime import date, datetime, timedelta
import numpy as np
import json

try:
    from ortools.sat.python import cp_model
except ImportError:
    print("Error: OR-Tools is not installed. Please install it with: pip install ortools")
    exit(1)

def test_cp_sat_simple():
    """Simplified test of CP-SAT using a minimal example."""
    print("\n=== CP-SAT Simplified Test ===")

    # Define a small problem
    num_nurses = 5
    num_days = 7
    shift_types = ['D', 'E', 'N', 'OFF']
    
    # Define which nurses are night nurses (indices)
    night_nurses = [2, 4]  # Nurses 2 and 4 are night nurses
    
    # Staffing requirements
    requirements = {'D': 1, 'E': 1, 'N': 1}
    
    # Create the model
    model = cp_model.CpModel()
    
    # Define variables: x[nurse, day, shift] = 1 if nurse works that shift
    x = {}
    for n in range(num_nurses):
        for d in range(num_days):
            for s, shift in enumerate(shift_types):
                x[n, d, s] = model.NewBoolVar(f'n{n}_d{d}_s{shift}')
    
    # Each nurse works exactly one shift per day
    for n in range(num_nurses):
        for d in range(num_days):
            model.AddExactlyOne(x[n, d, s] for s in range(len(shift_types)))
            
    # Staffing requirements
    for d in range(num_days):
        for shift, required in requirements.items():
            s = shift_types.index(shift)
            model.Add(sum(x[n, d, s] for n in range(num_nurses)) == required)
            
    # Night nurses CANNOT work day shifts
    for n in night_nurses:
        day_idx = shift_types.index('D')
        for d in range(num_days):
            model.Add(x[n, d, day_idx] == 0)
            
    # Minimum 2 days OFF per week per nurse
    for n in range(num_nurses):
        off_idx = shift_types.index('OFF')
        model.Add(sum(x[n, d, off_idx] for d in range(num_days)) >= 2)
    
    # Objective function: simple balance of shifts
    objective_terms = []
    
    # Try to distribute shifts evenly
    for shift in ['D', 'E', 'N']:
        s = shift_types.index(shift)
        for n in range(num_nurses):
            # Count this shift type for this nurse
            shift_count = sum(x[n, d, s] for d in range(num_days))
            
            # Target is roughly requirements[shift] * num_days / num_nurses
            if shift == 'N':
                # For night shifts, prefer night nurses
                if n in night_nurses:
                    # Bonus for night nurses doing night shifts
                    objective_terms.append(100 * shift_count)
                else:
                    # Penalty for non-night nurses doing night shifts
                    objective_terms.append(-50 * shift_count)
            else:
                # For day shifts, prefer non-night nurses
                if n not in night_nurses:
                    objective_terms.append(50 * shift_count)
    
    model.Maximize(sum(objective_terms))
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10  # Short time limit for test
    print("Solving model...")
    start_time = time.time()
    status = solver.Solve(model)
    solve_time = time.time() - start_time
    
    print(f"Solution status: {status}")
    print(f"Solving time: {solve_time:.2f} seconds")
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("\n=== Solution ===")
        
        # Print roster
        print("    ", end="")
        for d in range(num_days):
            print(f"D{d+1} ", end="")
        print()
        
        for n in range(num_nurses):
            print(f"N{n} {'*' if n in night_nurses else ' '}", end="")
            for d in range(num_days):
                for s, shift in enumerate(shift_types):
                    if solver.Value(x[n, d, s]) == 1:
                        print(f" {shift} ", end="")
                        break
            print()
            
        # Verify night nurse constraint
        night_violations = 0
        day_idx = shift_types.index('D')
        for n in night_nurses:
            for d in range(num_days):
                if solver.Value(x[n, d, day_idx]) == 1:
                    night_violations += 1
        
        print(f"\nNight nurse constraint violations: {night_violations}")
        
        return night_violations == 0
    else:
        print("No solution found.")
        return False

if __name__ == "__main__":
    test_cp_sat_simple() 