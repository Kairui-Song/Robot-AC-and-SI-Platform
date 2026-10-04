"""Four-joint plans for the deployed left arm; independent of ROS and hardware."""
from dataclasses import dataclass
import math

from linglong_control_tools.left_arm_configuration import NAMES


@dataclass(frozen=True)
class MotionPoint:
    time_ns: int
    positions: tuple


def ordered_positions(names, positions):
    if len(names) != 4 or len(positions) != 4 or set(names) != set(NAMES):
        raise ValueError('Require all four left-arm joints exactly once')
    values = dict(zip(names, positions))
    result = tuple(values[name] for name in NAMES)
    if not all(math.isfinite(value) for value in result):
        raise ValueError('Nonfinite joint position')
    return result


def build_plan(initial, limits, duration=6.0, *, offsets=None, amplitude=0.03):
    """Position-only points use linear controller interpolation, avoiding overshoot.

    Wave phases and relative amplitudes follow controller/dance_flow.sh; raw
    absolute encoder bases are deliberately replaced by fresh measured radians.
    A smooth envelope starts/ends the wave at the measured pose.
    """
    initial = ordered_positions(NAMES, initial)
    if not math.isfinite(duration) or not 1 <= duration <= 60:
        raise ValueError('duration must be in [1, 60] seconds')
    if set(limits) != set(NAMES):
        raise ValueError('Require limits for exactly joint_1/2/3/5')
    for name in NAMES:
        p = limits[name]
        if not all(math.isfinite(p[k]) for k in ('lower', 'upper', 'max_velocity')):
            raise ValueError('Nonfinite limits')
        if p['lower'] >= p['upper'] or p['max_velocity'] <= 0:
            raise ValueError('Invalid limits')
    if offsets is not None:
        offsets = ordered_positions(NAMES, offsets)
    elif not math.isfinite(amplitude) or not 0 < amplitude <= 0.05:
        raise ValueError('wave amplitude must be in (0, 0.05] rad')
    count = math.ceil(duration / 0.05)
    points = []
    phases = (0.0, 1.2, 2.4, 3.6)
    ratios = (1.0, 0.75, 0.5, 0.3)
    for step in range(count + 1):
        u = step / count
        if offsets is not None:
            blend = 3 * u * u - 2 * u * u * u
            values = tuple(p + delta * blend for p, delta in zip(initial, offsets))
        else:
            envelope = math.sin(math.pi * u) ** 2
            values = tuple(p + amplitude * ratio * envelope * math.sin(2 * math.pi * u + phase)
                           for p, ratio, phase in zip(initial, ratios, phases))
            if step in (0, count):
                values = initial
        point = MotionPoint(round(duration * u * 1e9), values)
        for i, name in enumerate(NAMES):
            if not limits[name]['lower'] <= values[i] <= limits[name]['upper']:
                raise ValueError(f'{name}: planned position outside limits')
            if points:
                dt = (point.time_ns - points[-1].time_ns) * 1e-9
                speed = abs(values[i] - points[-1].positions[i]) / dt
                if speed > limits[name]['max_velocity'] + 1e-9:
                    raise ValueError(f'{name}: plan exceeds velocity limit; increase duration')
        points.append(point)
    return tuple(points)
