import json
import time
from datetime import date, datetime
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
    
if __name__ == "__main__":
    main()
