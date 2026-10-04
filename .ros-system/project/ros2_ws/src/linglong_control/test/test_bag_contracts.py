from copy import deepcopy
from pathlib import Path
import math
import pytest
import yaml

from linglong_control_tools.bag_contracts import BagAudit, CONTROLLER, STATUS, TOPIC_TYPES, compare_replay, validate_profile
from linglong_control_tools.health import HEALTH_KEYS, JOINT_NAMES


def profile():
    return yaml.safe_load((Path(__file__).parents[1] / 'config/bag_profile.yaml').read_text())


def messages():
    for i in range(31):
        t = 1_000_000_000 + i * 100_000_000
        header = {'stamp': {'sec': t // 10**9, 'nanosec': t % 10**9}, 'frame_id': ''}
        values = [{'interface_names': ['position', 'velocity'], 'values': [0., 0.]} for _ in JOINT_NAMES]
        values.append({'interface_names': list(HEALTH_KEYS), 'values': [1, 1, 0, i+1, .01, .01, 0, 0]})
        yield '/dynamic_joint_states', {'header': header, 'joint_names': [*JOINT_NAMES, 'control_health'], 'interface_values': values}, t
        yield '/joint_states', {'header': header, 'name': JOINT_NAMES, 'position': [0.]*4, 'velocity': [0.]*4}, t
        yield CONTROLLER, {'header': header, 'joint_names': JOINT_NAMES, 'reference': {'positions': [0.]*4}, 'feedback': {'positions': [0.]*4}}, t
        yield '/diagnostics', {'status': [{'name': 'linglong/control', 'level': 0}]}, t
        transforms = []
        for parent, child in profile()['required_tf_edges']:
            transforms.append({'header': dict(header, frame_id=parent), 'child_frame_id': child,
                'transform': {'translation': {'x': 0., 'y': 0., 'z': .1}, 'rotation': {'x': 0., 'y': 0., 'z': 0., 'w': 1.}}})
        yield '/tf', {'transforms': transforms}, t


def audit(rows=None, goal_id=None):
    a = BagAudit(profile(), goal_id)
    for topic, data, time in messages() if rows is None else rows:
        a.add(topic, TOPIC_TYPES[topic], data, time)
    return a


def test_normal_mock_and_absent_optional_static_tf_pass():
    r = audit().report()
    assert r['passed'] and len(r['tf_edges']) == 4
    assert r['topics']['/tf_static']['count'] == 0


@pytest.mark.parametrize('fault', ['missing', 'stamp', 'nan', 'tracking', 'backend', 'cycles', 'tf', 'gap', 'diagnostics'])
def test_bad_evidence_cannot_pass(fault):
    rows = list(messages())
    for topic, data, _ in rows:
        if fault == 'stamp' and topic == CONTROLLER:
            data['header']['stamp'] = {'sec': 0, 'nanosec': 0}
        if fault == 'nan' and topic == '/joint_states':
            data['position'][0] = math.nan
        if fault == 'tracking' and topic == CONTROLLER:
            data['reference']['positions'][0] = .2
        if fault in ('backend', 'cycles') and topic == '/dynamic_joint_states':
            data['interface_values'][-1]['values'][0 if fault == 'backend' else 3] = 0
        if fault == 'tf' and topic == '/tf':
            data['transforms'][-1]['header']['frame_id'] = 'wrong'
        if fault == 'diagnostics' and topic == '/diagnostics':
            data['status'][0]['level'] = 2
    if fault == 'missing':
        rows = [r for r in rows if r[0] != CONTROLLER]
    if fault == 'gap':
        rows = [r for r in rows if not (r[0] == CONTROLLER and 1.5e9 < r[2] < 3e9)]
    assert not audit(rows).report()['passed']


def test_goal_uuid_must_match_success_not_retained_other_goal():
    a = audit(goal_id='01'*16)
    msg = {'status_list': [{'goal_info': {'goal_id': {'uuid': [2]*16}}, 'status': 4}]}
    a.add(STATUS, TOPIC_TYPES[STATUS], msg, 4_000_000_000)
    assert not a.report()['passed']
    msg['status_list'][0]['goal_info']['goal_id']['uuid'] = [1]*16
    a.add(STATUS, TOPIC_TYPES[STATUS], msg, 4_100_000_000)
    assert a.report()['passed']


def test_replay_checks_order_and_contents_but_not_receipt_time():
    rows = list(messages())
    original = audit(rows).report()
    replay = audit([(t, d, ns+100_000_000_000) for t, d, ns in rows]).report()
    assert compare_replay(original, replay)['passed']
    changed = deepcopy(rows)
    changed[1][1]['position'][0] = .01
    assert not compare_replay(original, audit(changed).report())['passed']
    assert not compare_replay(original, audit(rows[:-1]).report())['passed']
    reordered = deepcopy(rows)
    reordered[1], reordered[6] = reordered[6], reordered[1]
    assert not compare_replay(original, audit(reordered).report())['passed']


def test_profile_rejects_command_topics_and_disabled_required_checks():
    p = profile()
    p['topics']['/joint_command'] = {'type': 'trajectory_msgs/msg/JointTrajectory', 'min_count': 0}
    with pytest.raises(ValueError):
        validate_profile(p)
    p = profile()
    p['topics'][CONTROLLER]['min_count'] = 0
    with pytest.raises(ValueError):
        validate_profile(p)


def test_bad_type_and_tf_quaternion():
    a = audit()
    a.add('/tf', 'wrong', {}, 5_000_000_000)
    assert not a.report()['passed']
    rows = list(messages())
    rows[4][1]['transforms'][0]['transform']['rotation']['w'] = 0.
    assert not audit(rows).report()['passed']


def test_feedback_ending_early_cannot_pass_on_old_healthy_samples():
    rows = [r for r in messages() if not (r[0] == '/dynamic_joint_states' and r[2] > 3_000_000_000)]
    assert 'stream_ended_early:/dynamic_joint_states' in audit(rows).report()['errors']


def test_profile_matches_shared_interfaces_and_controller_configuration():
    from linglong_control_tools.interfaces import JOINT_NAMES, TRAJECTORY_CONTROLLER, TRAJECTORY_ACTION, DYNAMIC_STATES
    root = Path(__file__).parents[1]
    controllers = yaml.safe_load((root/'config/controllers.yaml').read_text())
    assert controllers[TRAJECTORY_CONTROLLER]['ros__parameters']['joints'] == list(JOINT_NAMES)
    assert DYNAMIC_STATES in profile()['topics']
    assert TRAJECTORY_ACTION + '/_action/status' in profile()['topics']
    qos = yaml.safe_load((root/'config/bag_qos.yaml').read_text())
    assert set(qos) == set(TOPIC_TYPES)
    assert qos['/tf_static']['durability'] == 'transient_local'
