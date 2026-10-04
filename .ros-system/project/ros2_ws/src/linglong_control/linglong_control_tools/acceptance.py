"""Evidence checks shared by live ROS probes and offline tests."""
import math


class HoldWindow:
    def __init__(self, reference, tolerance=0.002, velocity_limit=0.02):
        if not reference or not all(math.isfinite(v) for v in reference):
            raise ValueError('finite reference positions required')
        self.reference = list(reference)
        self.tolerance = tolerance
        self.velocity_limit = velocity_limit
        self.samples = 0
        self.first_time = self.last_time = self.last_cycle = None
        self.max_error = 0.0

    def add(self, positions, velocities, cycle, now):
        if len(positions) != len(self.reference) or len(velocities) != len(self.reference):
            raise ValueError('incomplete feedback')
        if not all(math.isfinite(v) for v in [*positions, *velocities, cycle, now]):
            raise ValueError('nonfinite feedback')
        if self.last_cycle is not None and cycle <= self.last_cycle:
            raise ValueError('feedback cycle did not advance')
        if self.last_time is not None and now <= self.last_time:
            raise ValueError('observation time did not advance')
        error = max(abs(p - r) for p, r in zip(positions, self.reference))
        if error > self.tolerance or max(abs(v) for v in velocities) > self.velocity_limit:
            raise ValueError('position hold violated')
        self.max_error = max(self.max_error, error)
        self.first_time = now if self.first_time is None else self.first_time
        self.last_time, self.last_cycle = now, cycle
        self.samples += 1

    def result(self, duration, min_samples=10):
        if self.samples < min_samples or self.last_time - self.first_time < duration:
            raise ValueError('insufficient fresh observation coverage')
        return {'samples': self.samples, 'duration': self.last_time - self.first_time,
                'reference': self.reference, 'max_error_rad': self.max_error}


def cancel_matches(response, goal_id):
    return response.return_code == 0 and any(
        list(goal.goal_id.uuid) == list(goal_id.uuid) for goal in response.goals_canceling)
