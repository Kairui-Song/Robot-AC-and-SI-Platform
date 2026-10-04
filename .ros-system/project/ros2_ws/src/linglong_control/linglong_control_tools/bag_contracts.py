"""Streaming bag evidence checks; no ROS imports and no device operations."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from linglong_control_tools.health import JOINT_NAMES, decode_snapshot
from linglong_control_tools.interfaces import CONTROLLER_STATE, ACTION_STATUS

CONTROLLER = CONTROLLER_STATE
STATUS = ACTION_STATUS
TOPIC_TYPES = {
    '/joint_states': 'sensor_msgs/msg/JointState',
    '/dynamic_joint_states': 'control_msgs/msg/DynamicJointState',
    '/diagnostics': 'diagnostic_msgs/msg/DiagnosticArray',
    '/tf': 'tf2_msgs/msg/TFMessage', '/tf_static': 'tf2_msgs/msg/TFMessage',
    CONTROLLER: 'control_msgs/msg/JointTrajectoryControllerState',
    STATUS: 'action_msgs/msg/GoalStatusArray',
    '/arm_trajectory_controller/follow_joint_trajectory/_action/feedback':
        'control_msgs/action/FollowJointTrajectory_FeedbackMessage',
}


def validate_profile(p):
    if p['schema_version'] != 1 or p['expected_backend'] != 'mock' or p['storage_id'] != 'sqlite3':
        raise ValueError('Only version 1 mock/sqlite3 profile is supported')
    if set(p['topics']) != set(TOPIC_TYPES):
        raise ValueError('Topic list must match the read-only left-arm contract')
    for name, spec in p['topics'].items():
        if spec['type'] != TOPIC_TYPES[name] or type(spec['min_count']) is not int or spec['min_count'] < 0:
            raise ValueError('Invalid topic contract: ' + name)
        if name in ('/joint_states', '/dynamic_joint_states', CONTROLLER, '/diagnostics', '/tf') and spec['min_count'] < 1:
            raise ValueError('Required topic cannot be optional')
    for key in ('min_duration_sec', 'max_gap_sec', 'max_tracking_error_rad'):
        if not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError('Invalid acceptance threshold: ' + key)
    if p['required_tf_edges'] != [['base_link', 'link_1'], ['link_1', 'link_2'],
                                  ['link_2', 'link_3'], ['link_3', 'link_5']]:
        raise ValueError('TF edges must match the current schematic model')
    return p


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def stamp(header):
    s = header['stamp']
    if not 0 <= s['nanosec'] < 10**9:
        raise ValueError('Invalid nanoseconds')
    return s['sec'] * 10**9 + s['nanosec']


def positions(names, values):
    if len(names) != 4 or set(names) != set(JOINT_NAMES) or len(values) != 4:
        raise ValueError('Expected exactly four joint values')
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite joint values')
    return [dict(zip(names, values))[n] for n in JOINT_NAMES]


class BagAudit:
    def __init__(self, profile, goal_id=None):
        self.profile = validate_profile(profile)
        self.goal_id = goal_id
        self.counts, self.errors = Counter(), Counter()
        self.hashes, self.last, self.first, self.gaps, self.stamps = {}, {}, {}, {}, {}
        self.parents, self.edges = {}, set()
        self.first_cycle = self.last_cycle = None
        self.progress_time = None
        self.max_error = 0.
        self.goal_succeeded = False

    def fail(self, reason):
        self.errors[reason] += 1

    def check_stamp(self, key, value):
        if value <= 0 or (key in self.stamps and value <= self.stamps[key]):
            self.fail('nonpositive_or_nonincreasing_header_stamp:' + key)
        self.stamps[key] = value

    def add(self, topic, type_name, data, receipt_ns):
        if topic not in self.profile['topics']:
            self.fail('unexpected_topic:' + topic)
            return
        self.counts[topic] += 1
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=True).encode()
        h = self.hashes.setdefault(topic, hashlib.sha256())
        h.update(len(canonical).to_bytes(8, 'big'))
        h.update(canonical)
        self.first.setdefault(topic, receipt_ns)
        if topic in self.last:
            gap = (receipt_ns - self.last[topic]) / 1e9
            if gap < 0:
                self.fail('receipt_time_regressed:' + topic)
            self.gaps[topic] = max(self.gaps.get(topic, 0.), gap)
        self.last[topic] = receipt_ns
        if type_name != self.profile['topics'][topic]['type']:
            self.fail('wrong_type:' + topic)
            return
        try:
            if topic in ('/joint_states', '/dynamic_joint_states', CONTROLLER):
                self.check_stamp(topic, stamp(data['header']))
            if topic == '/joint_states':
                positions(data['name'], data['position'])
                positions(data['name'], data['velocity'])
            elif topic == '/dynamic_joint_states':
                s = decode_snapshot(data['joint_names'], [
                    (v['interface_names'], v['values']) for v in data['interface_values']])
                h = s['control_health']
                if h['mock'] != 1 or h['active'] != 1 or h['fault_code'] != 0 or h['feedback_age_seconds'] != 0:
                    self.fail('unhealthy_or_nonmock_feedback')
                cycle = h['cycles']
                if self.first_cycle is None:
                    self.first_cycle = cycle
                if self.last_cycle is not None and cycle < self.last_cycle:
                    self.fail('control_cycles_regressed')
                if cycle != self.last_cycle:
                    self.progress_time = receipt_ns
                elif (receipt_ns - self.progress_time) / 1e9 > self.profile['max_gap_sec']:
                    self.fail('control_cycles_frozen')
                self.last_cycle = cycle
            elif topic == CONTROLLER:
                reference = positions(data['joint_names'], data['reference']['positions'])
                feedback = positions(data['joint_names'], data['feedback']['positions'])
                self.max_error = max(self.max_error, max(abs(a-b) for a, b in zip(reference, feedback)))
            elif topic == '/diagnostics':
                statuses = [s for s in data['status'] if s['name'] == 'linglong/control']
                if len(statuses) != 1 or statuses[0]['level'] != 0:
                    self.fail('diagnostics_not_healthy')
            elif topic in ('/tf', '/tf_static'):
                for transform in data['transforms']:
                    parent, child = transform['header']['frame_id'], transform['child_frame_id']
                    if not parent or not child or parent == child:
                        raise ValueError('Invalid TF edge')
                    if child in self.parents and self.parents[child] != parent:
                        self.fail('conflicting_tf_parent:' + child)
                    self.parents[child] = parent
                    self.edges.add((parent, child))
                    t = transform['transform']
                    xyz = [t['translation'][axis] for axis in ('x', 'y', 'z')]
                    q = [t['rotation'][axis] for axis in ('x', 'y', 'z', 'w')]
                    if not all(math.isfinite(v) for v in xyz + q) or abs(sum(v*v for v in q)-1) > .001:
                        raise ValueError('Invalid TF transform')
                    if topic == '/tf':
                        self.check_stamp('tf:' + child, stamp(transform['header']))
            elif topic == STATUS:
                for s in data['status_list']:
                    if bytes(s['goal_info']['goal_id']['uuid']).hex() == self.goal_id and s['status'] == 4:
                        self.goal_succeeded = True
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            self.fail('malformed:' + topic + ':' + type(exc).__name__)

    def report(self):
        errors = self.errors.copy()
        for topic, spec in self.profile['topics'].items():
            if self.counts[topic] < spec['min_count']:
                errors['missing_or_insufficient:' + topic] += 1
        for topic in ('/joint_states', '/dynamic_joint_states', CONTROLLER, '/diagnostics', '/tf'):
            duration = (self.last.get(topic, 0) - self.first.get(topic, 0)) / 1e9
            if duration < self.profile['min_duration_sec']:
                errors['insufficient_coverage:' + topic] += 1
            if self.gaps.get(topic, 0) > self.profile['max_gap_sec']:
                errors['stream_gap:' + topic] += 1
            if self.last and (max(self.last.values()) - self.last.get(topic, 0)) / 1e9 > self.profile['max_gap_sec']:
                errors['stream_ended_early:' + topic] += 1
        if self.first_cycle is None or self.last_cycle <= self.first_cycle:
            errors['no_control_cycle_progress'] += 1
        if self.max_error > self.profile['max_tracking_error_rad']:
            errors['tracking_error_exceeded'] += 1
        for edge in self.profile['required_tf_edges']:
            if tuple(edge) not in self.edges:
                errors['missing_tf_edge:' + '->'.join(edge)] += 1
        for child in self.parents:
            seen, current = set(), child
            while current in self.parents:
                if current in seen:
                    errors['tf_cycle'] += 1
                    break
                seen.add(current)
                current = self.parents[current]
        if self.goal_id and not self.goal_succeeded:
            errors['goal_success_not_observed'] += 1
        return {'schema_version': 1, 'passed': not errors, 'errors': dict(errors),
                'scope': 'recorded mock state and TF evidence; not hardware or real-time acceptance',
                'topics': {t: {'count': self.counts[t], 'type': TOPIC_TYPES[t],
                    'digest': self.hashes[t].hexdigest() if t in self.hashes else None,
                    'max_receipt_gap_sec': self.gaps.get(t, 0.)} for t in TOPIC_TYPES},
                'duration_sec': (max(self.last.values())-min(self.first.values()))/1e9 if self.last else 0,
                'max_tracking_error_rad': self.max_error,
                'tf_edges': sorted([list(e) for e in self.edges]),
                'goal_id': self.goal_id, 'goal_succeeded': self.goal_succeeded}


def compare_replay(source, replay):
    differences = []
    for topic in TOPIC_TYPES:
        a, b = source['topics'][topic], replay['topics'][topic]
        if any(a[k] != b[k] for k in ('count', 'type', 'digest')):
            differences.append(topic)
    return {'schema_version': 1, 'passed': source['passed'] and not differences,
            'source_acceptance_passed': source['passed'], 'different_topics': differences,
            'scope': 'per-topic ordered decoded message equality; ignores receive times and cross-topic ordering; no command re-execution'}
