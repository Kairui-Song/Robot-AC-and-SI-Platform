import json
import math
import pytest

from linglong_control_tools.evidence import Evidence, save_report
from linglong_control_tools.health import JOINT_NAMES


def feed_health(evidence, now, **changes):
    health = dict(mock=1, active=1, fault_code=0, cycles=1, period_seconds=.01,
                  max_period_seconds=.01, deadline_misses=0, feedback_age_seconds=0)
    health.update(changes)
    values = [(['position', 'velocity'], [.1, 0.]) for _ in JOINT_NAMES]
    values.append((list(health), list(health.values())))
    evidence.dynamic([*JOINT_NAMES, 'control_health'], values, now)


def test_no_data_does_not_claim_ethercat_fault():
    report = Evidence(0).report(2)
    assert report['root_cause'] is None
    assert report['hardware_feedback']['level'] == 3
    assert all(layer['status'] == 'NOT_OBSERVED' for layer in report['physical_layers'].values())
    assert all(not f['root_cause_confirmed'] for f in report['findings'])


def test_idle_is_not_reported_as_motor_failure():
    evidence = Evidence(0)
    for now in (.1, .3):
        evidence.controller_frame(JOINT_NAMES, [.1] * 4, [.1] * 4, now)
    assert not any(f['layer'] == 'tracking' for f in evidence.report(.3)['findings'])


def test_target_motion_without_feedback_is_only_an_investigation_hint():
    evidence = Evidence(0)
    evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4, .1, stamp_ns=100)
    evidence.controller_frame(JOINT_NAMES, [.03] * 4, [0] * 4, .3, stamp_ns=300)
    finding = next(f for f in evidence.report(.3)['findings'] if f['layer'] == 'tracking')
    assert not finding['root_cause_confirmed']


def test_stale_samples_cannot_prove_current_tracking_failure():
    evidence = Evidence(0)
    evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4, .1)
    evidence.controller_frame(JOINT_NAMES, [.03] * 4, [0] * 4, .3)
    report = evidence.report(2)
    assert report['controller_motion']['status'] == 'STALE'
    assert not any(f['layer'] == 'tracking' for f in report['findings'])


def test_joint_order_normalized():
    evidence = Evidence(0)
    evidence.controller_frame(list(reversed(JOINT_NAMES)), [4, 3, 2, 1], [8, 7, 6, 5], .1)
    assert evidence.motion(.1)['last_reference'] == [1, 2, 3, 4]


@pytest.mark.parametrize('positions', [[math.nan] * 4, [math.inf] * 4, [1]])
def test_malformed_frames_not_used_as_motion_evidence(positions):
    evidence = Evidence(0)
    evidence.controller_frame(JOINT_NAMES, positions, [0] * 4, .1)
    assert evidence.motion(.1)['status'] == 'UNKNOWN'
    assert evidence.invalid_frames == 1


def test_recent_bad_frame_marks_existing_data_invalid():
    evidence = Evidence(0)
    evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4, .1)
    evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4, .3)
    evidence.controller_frame(JOINT_NAMES, [math.nan] * 4, [0] * 4, .4)
    assert evidence.motion(.4)['status'] == 'INVALID'


def test_ring_buffer_is_bounded_and_window_explicit():
    evidence = Evidence(0, capacity=3)
    for i in range(10):
        evidence.controller_frame(JOINT_NAMES, [i * .01] * 4, [0] * 4, i * .1)
    motion = evidence.motion(.9)
    assert motion['retained_samples'] == 3
    assert motion['received_samples'] == 10
    assert motion['window_sec'] == pytest.approx(.2)


def test_timeline_retains_fault_and_later_recovery():
    evidence = Evidence(0)
    feed_health(evidence, .1)
    feed_health(evidence, .2, fault_code=6, active=0)
    feed_health(evidence, .3, cycles=2)
    report = evidence.report(.3)
    assert [event['level'] for event in report['events']] == [0, 2, 0]
    assert report['root_cause'] is None


def test_missing_controller_and_unavailable_interfaces_are_separate_evidence():
    evidence = Evidence(0)
    evidence.controllers = {'items': []}
    evidence.hardware = {'items': [{'name': 'arm', 'state': 'unconfigured',
        'command_interfaces': [{'name': 'joint_1/position', 'available': False}]}]}
    layers = {f['layer'] for f in evidence.report(.1)['findings']}
    assert {'controller', 'hardware_lifecycle', 'hardware_interfaces'} <= layers


def test_probe_qos_failure_scope_is_explicit():
    evidence = Evidence(0)
    evidence.graph['/dynamic_joint_states'] = {'publishers': [{'compatibility_to_probe': 'ERROR'}]}
    finding = next(f for f in evidence.report(.1)['findings'] if f['layer'] == 'qos')
    assert 'diagnostic subscriber' in finding['next_check']


def test_reports_are_valid_json_and_not_overwritten(tmp_path):
    path = tmp_path / 'incident.json'
    save_report(path, Evidence(0).report(1))
    assert json.loads(path.read_text(encoding='utf-8'))['schema_version'] == 1
    with pytest.raises(FileExistsError):
        save_report(path, {'different': True})


def test_nan_json_is_rejected_before_creating_file(tmp_path):
    path = tmp_path / 'invalid.json'
    with pytest.raises(ValueError):
        save_report(path, {'bad': math.nan})
    assert not path.exists()


def test_historical_aborted_goal_is_not_a_current_root_cause():
    evidence = Evidence(0)
    evidence.action = {'goals': [{'status': 6, 'goal_id': 'abc'}]}
    finding = next(f for f in evidence.report(1)['findings'] if f['layer'] == 'application')
    assert 'earlier run' in finding['next_check']
    assert not finding['root_cause_confirmed']


def test_fault_nan_feedback_saved_as_null_with_fault_evidence(tmp_path):
    evidence = Evidence(0)
    feed_health(evidence, .1, fault_code=6, active=0)
    evidence.monitor.snapshot['joint_1']['position'] = math.nan
    report = evidence.report(.1)
    assert report['hardware_feedback']['joint_state']['joint_1']['position'] is None
    save_report(tmp_path / 'fault.json', report)


def test_transition_buffer_drops_oldest_with_explicit_count():
    evidence = Evidence(0)
    for i in range(80):
        feed_health(evidence, i * .1, cycles=i, active=i % 2)
    report = evidence.report(7.9)
    assert len(report['events']) == 64
    assert report['events_dropped'] == 16


def test_replayed_controller_frames_are_not_fresh_motion_evidence():
    evidence = Evidence(0)
    evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4, .1, stamp_ns=100)
    evidence.controller_frame(JOINT_NAMES, [.03] * 4, [0] * 4, .3, stamp_ns=100)
    report = evidence.report(.3)
    assert report['controller_motion']['status'] == 'UNVERIFIED'
    assert not any(f['layer'] == 'tracking' for f in report['findings'])


@pytest.mark.parametrize('stamps', [(100, 200, 200), (100, 300, 200), (100, 200, 0), (0, 0, 0)])
def test_partial_replay_regression_or_missing_stamps_suppress_tracking_hint(stamps):
    evidence = Evidence(0)
    for i, stamp in enumerate(stamps):
        evidence.controller_frame(JOINT_NAMES, [i * .03] * 4, [0] * 4,
                                  .1 + i * .2, stamp_ns=stamp)
    report = evidence.report(.5)
    assert report['controller_motion']['status'] == 'UNVERIFIED'
    assert not any(f['layer'] == 'tracking' for f in report['findings'])


def test_timestamp_warning_clears_after_bad_window_is_evicted():
    evidence = Evidence(0, capacity=2)
    for i, stamp in enumerate((100, 100, 200, 300)):
        evidence.controller_frame(JOINT_NAMES, [0] * 4, [0] * 4,
                                  .1 + i * .2, stamp_ns=stamp)
    assert evidence.motion(.7)['status'] == 'OBSERVED'
