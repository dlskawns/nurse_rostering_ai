# Nurse Rostering System with Global Optimization

A nurse rostering system using constraint programming (CP-SAT) to generate optimal shift schedules that satisfy all necessary constraints.

## Features

- **Global Optimization**: Uses Google OR-Tools CP-SAT solver to find globally optimal solutions
- **Hard Constraints**:

  - Night nurses CANNOT work day shifts (strict constraint)
  - Staffing requirements must be met for each shift
  - Experience requirements must be met for each shift type
  - Consecutive work day limits
  - Night shift limits
  - Head nurse weekend patterns
  - Automatic handling of resignation dates

- **Preference Modeling**:

  - Nurse shift preferences
  - Work pattern preferences
  - Specialization preferences

- **Workload Balancing**:

  - Equitable distribution of shifts
  - Fair weekend assignment

- **Comprehensive Metrics**:
  - Detailed workload analysis
  - Nurse satisfaction scores
  - Fairness metrics using Gini coefficient

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Running the System

```bash
python main_v2.py
```

This will:

1. Load test data from `test_data.json`
2. Initialize the roster system
3. Generate an initial roster using constraint-based methods
4. Optimize the roster using global CP-SAT optimization
5. Calculate detailed metrics
6. Export the roster to Excel (`roster_v2.xlsx`)
7. Export detailed metrics to `detailed_metrics.json`

### Running Tests

Simple test to verify CP-SAT implementation:

```bash
python cp_sat_simple_test.py
```

Comprehensive test for all constraints:

```bash
python test_cp_sat.py
```

## Implementation Details

### Key Components

- **RosterSystem**: Core system managing constraints and roster generation
- **Nurse**: Class representing nurse properties and preferences
- **RosterGenerator**: Helper class for generating initial feasible rosters
- **CP-SAT Optimization**: Global optimization using constraint programming

### Optimization Approaches

1. **Initial Roster Generation**: Creates a feasible starting roster
2. **Global CP-SAT Optimization**: Finds a globally optimal solution
3. **LNS Refinement**: (Optional) Large Neighborhood Search for further improvements

### Customization

Modify `config.py` to change:

- Shift types
- Staffing requirements
- Experience requirements
- Consecutive work day limits
- Night shift limits

## Data Format

The `test_data.json` file contains:

- Nurse data (experience, specialization, etc.)
- Configuration parameters
- Off requests
- Target month

## Benefits Over Sequential Optimization

The global CP-SAT approach offers several advantages:

- Eliminates the "fix one, break another" cycle
- Considers all constraints simultaneously
- Guarantees a globally optimal solution if one exists
- Properly enforces all hard constraints, including night nurse restrictions
- Balances multiple objectives through weighted optimization
