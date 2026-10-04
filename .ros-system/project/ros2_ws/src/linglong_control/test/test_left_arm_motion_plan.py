import math
import pytest
from linglong_control_tools.left_arm_configuration import NAMES
from linglong_control_tools.left_arm_motion_plan import build_plan, ordered_positions


def limits():
    return {n: {'lower': -1.57, 'upper': 1.57, 'max_velocity': .1} for n in NAMES}


def test_wave_moves_all_four_from_measured_pose_and_returns():
    start = (.2, -.3, .4, -.1)
    plan = build_plan(start, limits())
    assert plan[0].positions == plan[-1].positions == start
    assert plan[0].time_ns == 0 and plan[-1].time_ns == 6_000_000_000
    for i in range(4):
        assert any(abs(p.positions[i] - start[i]) > .001 for p in plan)
    for previous, point in zip(plan, plan[1:]):
        dt = (point.time_ns - previous.time_ns) / 1e9
        assert 0 < dt <= .05 + 1e-9
        assert all(abs(a-b) / dt <= .1 for a, b in zip(point.positions, previous.positions))


def test_offsets_and_reordered_feedback():
    start = ordered_positions(list(reversed(NAMES)), [4, 3, 2, 1])
    assert start == (1, 2, 3, 4)
    plan = build_plan((0, 0, 0, 0), limits(), offsets=(.02, -.03, .04, -.01))
    assert plan[-1].positions == (.02, -.03, .04, -.01)
    assert plan[60].positions == (.01, -.015, .02, -.005)


@pytest.mark.parametrize('kwargs', [
    {'duration': 0}, {'duration': math.nan}, {'duration': 61},
    {'amplitude': .1}, {'amplitude': math.nan},
    {'offsets': [0, 0, 0]}, {'offsets': [0, 0, 0, math.inf]},
    {'offsets': [0, 0, 0, 2]}, {'offsets': [.2, 0, 0, 0], 'duration': 1},
])
def test_reject_unsafe_plan(kwargs):
    with pytest.raises(ValueError):
        build_plan((0, 0, 0, 0), limits(), **kwargs)


def test_reject_invalid_limits_and_feedback():
    for key, value in [('upper', -2), ('lower', math.nan), ('max_velocity', 0)]:
        bounds = limits()
        bounds['joint_5'][key] = value
        with pytest.raises(ValueError):
            build_plan((0, 0, 0, 0), bounds)
    with pytest.raises(ValueError):
        ordered_positions(['joint_1'] * 4, [0] * 4)
    with pytest.raises(ValueError):
        build_plan((0, 0, 0, math.nan), limits())
