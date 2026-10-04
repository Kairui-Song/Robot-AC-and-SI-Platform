"""ROS-independent health checks; receipt and progress time use a monotonic clock."""
import math

JOINT_NAMES = ('joint_1', 'joint_2', 'joint_3', 'joint_5')
FAULTS = {
    1: 'invalid command', 2: 'position limit', 3: 'command step limit',
    4: 'following error', 5: 'control cycle timeout', 6: 'feedback timeout',
    7: 'injected mock fault', 8: 'hardware lifecycle error',
}
HEALTH_KEYS = ('mock', 'active', 'fault_code', 'cycles', 'period_seconds',
               'max_period_seconds', 'deadline_misses', 'feedback_age_seconds')


def decode_snapshot(names, values):
    """Accept only one complete, finite snapshot with an unambiguous schema."""
    if len(names) != len(values) or len(set(names)) != len(names):
        raise ValueError('invalid dynamic state resource names')
    resources = {}
    for name, (interfaces, samples) in zip(names, values):
        if len(interfaces) != len(samples) or len(set(interfaces)) != len(interfaces):
            raise ValueError(f'invalid interfaces for {name}')
        resources[name] = dict(zip(interfaces, samples))
    health = resources.get('control_health', {})
    if any(key not in health or not math.isfinite(health[key]) for key in HEALTH_KEYS):
        raise ValueError('missing or invalid control_health')
    if any(health[key] not in (0, 1) for key in ('mock', 'active')):
        raise ValueError('invalid control_health flags')
    for key in ('fault_code', 'cycles', 'deadline_misses'):
        if health[key] < 0 or health[key] != math.floor(health[key]):
            raise ValueError(f'invalid control_health counter: {key}')
    if any(health[key] < 0 for key in ('period_seconds', 'max_period_seconds', 'feedback_age_seconds')):
        raise ValueError('negative control_health duration')
    # Fault frames may intentionally contain NaN position. Preserve fault reason first.
    if health['fault_code'] == 0:
        for name in JOINT_NAMES:
            state = resources.get(name, {})
            if any(key not in state or not math.isfinite(state[key]) for key in ('position', 'velocity')):
                raise ValueError(f'missing or invalid feedback for {name}')
    return resources


class HealthMonitor:
    def __init__(self, stale_timeout=0.5):
        if not math.isfinite(stale_timeout) or stale_timeout <= 0:
            raise ValueError('stale_timeout must be finite and positive')
        self.stale_timeout = stale_timeout
        self.snapshot = None
        self.last_received = None
        self.last_progress = None
        self.last_cycles = None
        self.invalid_reason = None

    def receive(self, names, values, now):
        try:
            snapshot = decode_snapshot(names, values)
        except ValueError as exc:
            self.invalid_reason = str(exc)
            return
        cycles = snapshot['control_health']['cycles']
        if self.last_cycles is None or cycles != self.last_cycles:
            self.last_progress = now
        self.last_cycles = cycles
        self.snapshot = snapshot
        self.last_received = now
        self.invalid_reason = None

    def status(self, now):
        if self.invalid_reason:
            return 2, self.invalid_reason
        if self.snapshot is None:
            return 3, 'waiting for /dynamic_joint_states'
        h = self.snapshot['control_health']
        if h['fault_code']:
            return 2, 'latched fault: ' + FAULTS.get(int(h['fault_code']), 'unknown')
        if now - self.last_received > self.stale_timeout:
            return 3, 'state stream stopped; hardware state unknown'
        if h['mock'] != 1:
            return 2, 'unexpected backend; this monitor expects MOCK'
        if not h['active']:
            return 1, 'MOCK hardware inactive'
        # Repeated cached frames must not make a stopped control loop look healthy.
        if now - self.last_progress > self.stale_timeout:
            return 2, 'control cycle counter stopped'
        if h['feedback_age_seconds'] > 0:
            return 1, 'MOCK feedback delayed'
        if h['period_seconds'] > 0.015:
            return 1, 'MOCK control interval exceeds 15 ms'
        return 0, 'MOCK control running (no physical feedback)'
