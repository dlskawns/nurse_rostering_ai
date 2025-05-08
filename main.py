import json
import time
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np
from config import NurseRosterConfig
from nurse import Nurse
from roster_system import RosterSystem

class Timer:
    def __init__(self, name):
        self.name = name
        self.start_time = None
        
    def __enter__(self):
        print(f"\n[START] {self.name}")
        self.start_time = time.time()
        return self
        
    def __exit__(self, *args):
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        print(f"[END] {self.name} - Elapsed time: {elapsed_time:.4f} seconds")

def load_test_data(json_file: str):
    """Load test data from JSON file."""
    with open(json_file, 'r') as f:
        data = json.load(f)
    return data

def create_nurses_from_data(nurses_data):
    """Create nurse objects from JSON data."""
    nurses = []
    for nurse_data in nurses_data:
        # Convert resignation_date string to date object if present
        resignation_date = None
        if 'resignation_date' in nurse_data:
            resignation_date = datetime.strptime(
                nurse_data['resignation_date'], '%Y-%m-%d'
            ).date()
            
        nurse = Nurse(
            id=nurse_data['id'],
            name=nurse_data['name'],
            experience_years=nurse_data['experience_years'],
            is_night_nurse=nurse_data.get('is_night_nurse', False),
            is_head_nurse=nurse_data.get('is_head_nurse', False),
            remaining_off_days=nurse_data.get('remaining_off_days', 0),
            head_nurse_off_pattern=nurse_data.get('head_nurse_off_pattern'),
            resignation_date=resignation_date
        )
        nurses.append(nurse)
    return nurses

def calculate_nurse_satisfaction(roster_system, nurse_idx):
    """Calculate satisfaction metrics for a single nurse."""
    nurse = roster_system.nurses[nurse_idx]
    roster = roster_system.roster[nurse_idx]
    num_days = roster_system.num_days
    
    metrics = {
        'total_shifts': 0,
        'night_shifts': 0,
        'weekend_offs': 0,
        'preference_score': 0.0,
        'consecutive_work_days_max': 0
    }
    
    # Calculate metrics
    consecutive_work = 0
    for day in range(num_days):
        is_weekend = day % 7 >= 5
        shifts = roster[day]
        
        # Count shifts
        if np.any(shifts[:-1]):  # Excluding OFF
            metrics['total_shifts'] += 1
            consecutive_work += 1
            metrics['consecutive_work_days_max'] = max(
                metrics['consecutive_work_days_max'], 
                consecutive_work
            )
        else:
            consecutive_work = 0
            
        # Count night shifts
        if shifts[roster_system.config.shift_types.index('N')] == 1:
            metrics['night_shifts'] += 1
            
        # Count weekend offs
        if is_weekend and shifts[roster_system.config.shift_types.index('OFF')] == 1:
            metrics['weekend_offs'] += 1
            
        # Calculate preference alignment
        prefs = roster_system.preference_matrix[nurse_idx, day]
        metrics['preference_score'] += np.sum(prefs * shifts)
        
    # Normalize preference score
    metrics['preference_score'] /= num_days
    
    return metrics

def export_roster_to_excel(roster_system, filename='roster.xlsx'):
    """Export roster and metrics to Excel file."""
    # Create roster dataframe
    dates = [
        (roster_system.target_month + timedelta(days=i)).strftime('%Y-%m-%d')
        for i in range(roster_system.num_days)
    ]
    
    roster_data = []
    for n_idx, nurse in enumerate(roster_system.nurses):
        row = {'Nurse': nurse.name}
        for day in range(roster_system.num_days):
            shift_idx = np.where(roster_system.roster[n_idx, day] == 1)[0]
            if len(shift_idx) == 0:
                row[dates[day]] = '-'
            else:
                row[dates[day]] = roster_system.config.shift_types[shift_idx[0]]
        roster_data.append(row)
        
    roster_df = pd.DataFrame(roster_data)
    
    # Calculate satisfaction metrics
    metrics_data = []
    for n_idx, nurse in enumerate(roster_system.nurses):
        metrics = calculate_nurse_satisfaction(roster_system, n_idx)
        metrics['Nurse'] = nurse.name
        metrics_data.append(metrics)
        
    metrics_df = pd.DataFrame(metrics_data)
    
    # Create Excel writer
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        # Write roster sheet
        roster_df.to_excel(writer, sheet_name='Roster', index=False)
        
        # Write metrics sheet
        metrics_df.to_excel(writer, sheet_name='Satisfaction Metrics', index=False)
        
        # Auto-adjust columns width
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                max_length = 0
                column = [cell for cell in column]
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = (max_length + 2)
                sheet.column_dimensions[column[0].column_letter].width = adjusted_width

def main():
    print("\n=== Starting Nurse Rostering System ===")
    
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
        
    # Generate initial roster
    with Timer("Generating initial roster"):
        roster_system.generate_initial_roster()
        print("Initial roster generated")
        
    # Apply off requests
    with Timer("Applying off requests"):
        # Convert string keys to integers
        off_requests = {int(k): v for k, v in data['off_requests'].items()}
        roster_system.apply_off_requests(off_requests)
        print(f"Applied {len(off_requests)} off requests")
        
    # Optimize roster
    with Timer("Optimizing roster"):
        roster_system.optimize_roster()
        print("Roster optimization completed")
        
    # Print final roster
    print("\n=== Final Roster ===")
    roster_system.print_roster()
    
    # Export to Excel with metrics
    with Timer("Exporting results"):
        export_roster_to_excel(roster_system)
        print("Results exported to roster.xlsx")
    
if __name__ == "__main__":
    main()
