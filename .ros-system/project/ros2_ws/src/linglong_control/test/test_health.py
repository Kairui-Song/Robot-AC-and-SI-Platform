import math
import pytest

from linglong_control_tools.health import HealthMonitor, JOINT_NAMES, decode_snapshot


def snapshot(**health):
    data = dict(mock=1., active=1., fault_code=0., cycles=1., period_seconds=.01,
                max_period_seconds=.01, deadline_misses=0., feedback_age_seconds=0.)
    data.update(health)
    names = [*JOINT_NAMES, 'control_health']
    values = [(['position', 'velocity'], [0.1, 0.0]) for _ in JOINT_NAMES]
    values.append((list(data), list(data.values())))
    return names, values


def test_waiting_then_healthy_then_stale():
    monitor = HealthMonitor()
    assert monitor.status(0)[0] == 3
    monitor.receive(*snapshot(), 1.)
    assert monitor.status(1.1)[0] == 0
    assert monitor.status(2.)[0] == 3


def test_republished_frozen_snapshot_is_not_healthy():
    monitor = HealthMonitor()
    monitor.receive(*snapshot(), 1.)
    monitor.receive(*snapshot(), 2.)
    assert monitor.status(2.) == (2, 'control cycle counter stopped')


def test_fault_reason_survives_nan_joint_state_and_stale_stream():
    monitor = HealthMonitor()
    names, values = snapshot(fault_code=6, active=0)
    values[0] = (['position', 'velocity'], [math.nan, math.nan])
    monitor.receive(names, values, 1.)
    assert monitor.status(10.) == (2, 'latched fault: feedback timeout')


@pytest.mark.parametrize('changes,level', [
    ({'active': 0}, 1), ({'mock': 0}, 2), ({'feedback_age_seconds': .03}, 1),
    ({'period_seconds': .02}, 1), ({'fault_code': 7}, 2),
])
def test_health_states(changes, level):
    monitor = HealthMonitor()
    monitor.receive(*snapshot(**changes), 1.)
    assert monitor.status(1.)[0] == level


def test_malformed_frame_does_not_refresh_health():
    monitor = HealthMonitor()
    monitor.receive(*snapshot(), 1.)
    names, values = snapshot()
    values[0] = (['position', 'velocity'], [math.nan, 0])
    monitor.receive(names, values, 2.)
    assert monitor.status(2.)[0] == 2
    assert monitor.last_received == 1.


def test_duplicate_or_missing_resources_rejected():
    names, values = snapshot()
    with pytest.raises(ValueError):
        decode_snapshot(names + [names[0]], values + [values[0]])
    with pytest.raises(ValueError):
        decode_snapshot(names[:-1], values[:-1])


def test_empty_frame_does_not_mask_failure():
    monitor = HealthMonitor()
    monitor.receive([], [], 0.)
    assert monitor.status(0.)[0] == 2


@pytest.mark.parametrize('changes', [
    {'cycles': -1}, {'fault_code': .5}, {'active': 2}, {'feedback_age_seconds': -.01},
])
def test_invalid_health_values_are_not_healthy(changes):
    monitor = HealthMonitor()
    monitor.receive(*snapshot(**changes), 1.)
    assert monitor.status(1.)[0] == 2
