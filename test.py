import numpy as np
from typing import List, Tuple

class NurseSchedulePSO:
    def __init__(self, num_nurses: int, num_days: int, num_particles: int):
        self.num_nurses = num_nurses
        self.num_days = num_days 
        self.num_particles = num_particles
        
        # PSO parameters
        self.w = 0.5  # inertia weight
        self.c1 = 1.5  # cognitive coefficient
        self.c2 = 1.5  # social coefficient
        
        # Initialize particles
        self.particles = np.random.randint(0, 3, (num_particles, num_nurses, num_days))
        self.velocities = np.zeros((num_particles, num_nurses, num_days))
        self.pbest = self.particles.copy()
        self.pbest_fitness = np.array([self.fitness(p) for p in self.particles])
        self.gbest = self.particles[np.argmin(self.pbest_fitness)].copy()
        self.gbest_fitness = np.min(self.pbest_fitness)

    def fitness(self, schedule: np.ndarray) -> float:
        """
        Calculate fitness score for a schedule
        0: Day shift, 1: Night shift, 2: Off
        """
        penalty = 0
        
        # Check consecutive working days
        for nurse in range(self.num_nurses):
            consecutive_work = 0
            for day in range(self.num_days):
                if schedule[nurse, day] != 2:  # if working
                    consecutive_work += 1
                else:
                    consecutive_work = 0
                if consecutive_work > 5:  # max 5 consecutive working days
                    penalty += 100
                    
        # Check minimum rest between shifts
        for nurse in range(self.num_nurses):
            for day in range(self.num_days - 1):
                if schedule[nurse, day] == 1 and schedule[nurse, day + 1] == 0:  # night to day
                    penalty += 200
                    
        # Check minimum nurses per shift
        min_nurses = 2  # minimum nurses needed per shift
        for day in range(self.num_days):
            day_nurses = np.sum(schedule[:, day] == 0)
            night_nurses = np.sum(schedule[:, day] == 1)
            if day_nurses < min_nurses or night_nurses < min_nurses:
                penalty += 150
                
        return penalty

    def update_velocity(self, particle_idx: int):
        r1, r2 = np.random.rand(2)
        self.velocities[particle_idx] = (self.w * self.velocities[particle_idx] + 
                                       self.c1 * r1 * (self.pbest[particle_idx] - self.particles[particle_idx]) +
                                       self.c2 * r2 * (self.gbest - self.particles[particle_idx]))

    def update_position(self, particle_idx: int):
        self.particles[particle_idx] += np.round(self.velocities[particle_idx]).astype(int)
        self.particles[particle_idx] = np.clip(self.particles[particle_idx], 0, 2)

    def optimize(self, max_iterations: int = 100) -> Tuple[np.ndarray, float]:
        """
        Run PSO optimization
        Returns: (best schedule, best fitness score)
        """
        for _ in range(max_iterations):
            for i in range(self.num_particles):
                # Update particle
                self.update_velocity(i)
                self.update_position(i)
                
                # Update personal best
                fitness = self.fitness(self.particles[i])
                if fitness < self.pbest_fitness[i]:
                    self.pbest[i] = self.particles[i].copy()
                    self.pbest_fitness[i] = fitness
                    
                    # Update global best
                    if fitness < self.gbest_fitness:
                        self.gbest = self.particles[i].copy()
                        self.gbest_fitness = fitness
                        
        return self.gbest, self.gbest_fitness

# Example usage
if __name__ == "__main__":
    num_nurses = 10
    num_days = 30
    num_particles = 50
    
    scheduler = NurseSchedulePSO(num_nurses, num_days, num_particles)
    best_schedule, best_fitness = scheduler.optimize(max_iterations=200)
    
    print("Best fitness score:", best_fitness)
    print("\nBest schedule (0: Day, 1: Night, 2: Off):")
    print(best_schedule)


    
