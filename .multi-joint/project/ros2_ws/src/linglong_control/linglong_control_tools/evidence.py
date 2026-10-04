"""Bounded, ROS-independent evidence recording. Observations are not root causes."""
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from linglong_control_tools.health import HealthMonitor, JOINT_NAMES


class Evidence:
    def __init__(self, started, capacity=512, expected_backend='mock', nominal_period=0.01):
        if capacity < 2:
            raise ValueError('capacity must be at least two')
        self.started = started
        self.monitor = HealthMonitor(expected_backend=expected_backend, nominal_period=nominal_period)
        self.frames = deque(maxlen=capacity)
        self.events = deque(maxlen=64)
        self.total_frames = self.invalid_frames = self.total_events = 0
        self.last_condition = None
        self.last_invalid = None
        self.action = None
        self.controllers = None
        self.hardware = None
        self.graph = {}
        self.errors = {}

    def observe_condition(self, now):
        level, message = self.monitor.status(now)
        condition = (level, message)
        if condition != self.last_condition:
            self.events.append({'elapsed_sec': now - self.started, 'level': level,
                                'observation': message})
            self.total_events += 1
            self.last_condition = condition

    def dynamic(self, names, values, now):
        self.monitor.receive(names, values, now)
        self.observe_condition(now)

    def controller_frame(self, names, reference, feedback, now, stamp_ns=0):
        self.total_frames += 1
        if (len(names) != len(JOINT_NAMES) or set(names) != set(JOINT_NAMES) or
                len(reference) != len(names) or len(feedback) != len(names) or
                not all(math.isfinite(v) for v in [*reference, *feedback])):
            self.invalid_frames += 1
            self.last_invalid = now
            return
        by_name = {name: (r, f) for name, r, f in zip(names, reference, feedback)}
        self.frames.append({'received': now, 'stamp_ns': stamp_ns,
                            'reference': [by_name[n][0] for n in JOINT_NAMES],
                            'feedback': [by_name[n][1] for n in JOINT_NAMES]})

    def motion(self, now):
        frames = list(self.frames)
        if not frames:
            return {'status': 'UNKNOWN', 'reason': 'no valid controller-state samples',
                    'invalid_samples': self.invalid_frames}
        age = now - frames[-1]['received']
        result = {'status': 'OBSERVED', 'age_sec': age, 'retained_samples': len(frames),
                  'received_samples': self.total_frames, 'invalid_samples': self.invalid_frames,
                  'window_sec': frames[-1]['received'] - frames[0]['received'],
                  'last_stamp_ns': frames[-1]['stamp_ns'], 'joints': list(JOINT_NAMES),
                  'last_reference': frames[-1]['reference'], 'last_feedback': frames[-1]['feedback']}
        if age > self.monitor.stale_timeout:
            result.update(status='STALE', reason='controller-state stream stopped')
        elif self.last_invalid is not None and now - self.last_invalid <= self.monitor.stale_timeout:
            result.update(status='INVALID', reason='recent malformed controller-state sample')
        elif len(frames) < 2 or result['window_sec'] < .1:
            result.update(status='UNKNOWN', reason='insufficient temporal coverage')
        elif any(f['stamp_ns'] <= 0 for f in frames):
            result.update(status='UNVERIFIED', reason='controller ROS timestamps unavailable')
        elif any(b['stamp_ns'] <= a['stamp_ns'] for a, b in zip(frames, frames[1:])):
            result.update(status='UNVERIFIED', reason='controller ROS timestamps repeated or regressed within retained window')
        for key in ('reference', 'feedback'):
            result[key + '_range_rad'] = [
                max(f[key][i] for f in frames) - min(f[key][i] for f in frames)
                for i in range(len(JOINT_NAMES))]
        result['max_tracking_error_rad'] = [
            max(abs(f['reference'][i] - f['feedback'][i]) for f in frames)
            for i in range(len(JOINT_NAMES))]
        result['interpretation'] = (
            'Ranges describe only retained received samples. Constant targets can mean idle/hold; '
            'changing targets with constant feedback suggest further investigation, not a confirmed motor fault.')
        return result

    def report(self, now):
        self.observe_condition(now)
        level, message = self.monitor.status(now)
        health = None if self.monitor.snapshot is None else self.monitor.snapshot['control_health']
        motion = self.motion(now)
        findings = []

        def add(layer, observation, next_check):
            findings.append({'layer': layer, 'observation': observation,
                             'root_cause_confirmed': False, 'next_check': next_check})

        if self.action is None:
            add('application', 'no Action status history received',
                'Check the client goal UUID, acceptance response and result; missing status does not prove no command was sent.')
        else:
            for goal in self.action['goals']:
                if goal['status'] == 6:
                    add('application', 'retained history includes ABORTED goal ' + goal['goal_id'],
                        'Correlate this UUID and goal timestamp with client result/error text; it may belong to an earlier run.')

        if self.controllers is None:
            add('controller', 'controller list unavailable',
                'Check controller_manager process, ROS_DOMAIN_ID, service discovery and permissions.')
        else:
            matches = [c for c in self.controllers['items'] if c['name'] == 'arm_trajectory_controller']
            if len(matches) != 1:
                add('controller', 'expected controller missing or ambiguous',
                    'Check launch and spawner logs; do not automatically activate hardware.')
            elif matches[0]['state'] != 'active':
                add('controller', 'trajectory controller is ' + matches[0]['state'],
                    'Check whether deliberately stopped or deactivated following a hardware error.')
            elif not {n + '/position' for n in JOINT_NAMES}.issubset(matches[0]['claimed_interfaces']):
                add('controller', 'active controller does not report all expected position claims',
                    'Check controller joint names, interface configuration and resource ownership.')
        if level != 0:
            add('hardware_feedback', message,
                'Correlate plugin fault code/log and controller lifecycle; stale ROS data alone does not prove a bus failure.')
        if self.hardware is None:
            add('hardware_lifecycle', 'hardware component list unavailable',
                'Check list_hardware_components service and plugin initialization logs.')
        else:
            if not self.hardware['items']:
                add('hardware_lifecycle', 'no hardware components reported',
                    'Check robot_description and plugin loading errors.')
            for component in self.hardware['items']:
                if component['state'] != 'active':
                    add('hardware_lifecycle', component['name'] + ' is ' + component['state'],
                        'Check configuration, activation and error transitions; do not automatically reset.')
                unavailable = [i['name'] for i in component['command_interfaces'] if not i['available']]
                if unavailable:
                    add('hardware_interfaces', 'unavailable commands: ' + ', '.join(unavailable),
                        'Correlate interface availability with hardware lifecycle and controller claims.')
        if motion['status'] != 'OBSERVED':
            add('controller_state', motion.get('reason', motion['status']),
                'Check controller lifecycle, topic publishers, message schema and QoS evidence.')
        elif any(r > .002 and f < .0001 for r, f in zip(
                motion['reference_range_rad'], motion['feedback_range_rad'])):
            add('tracking', 'changing reference with little observed feedback movement',
                'Compare hardware command/state, following error and sample freshness before inspecting drive state.')
        for topic, graph in self.graph.items():
            if not graph['publishers']:
                add('ros_graph', f'no discovered publisher for {topic}',
                    'Check node startup and ROS domain; discovery snapshot is not proof that the process is absent.')
            if len(graph['publishers']) > 1:
                add('ros_graph', f'multiple discovered publishers for {topic}',
                    'Identify each publisher before attributing samples to one control stack.')
            for publisher in graph['publishers']:
                if publisher['compatibility_to_probe'] == 'ERROR':
                    add('qos', f'incompatible publisher QoS to this probe on {topic}',
                        'Compare the actual application endpoints separately; this check only covers the diagnostic subscriber.')
        return {
            'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'observation_duration_sec': now - self.started,
            'scope': 'ROS2 evidence for Linglong; no device I/O and no automatic repair',
            'root_cause': None,
            'application': {'action_status': self.action,
                            'limitation': 'Status history does not prove the intended goal was accepted; rejected goals may not appear.'},
            'controllers': self.controllers, 'hardware_components': self.hardware,
            'controller_motion': motion,
            'ethercat_telemetry': {
                'source': 'reported ros2_control state interfaces; not independent physical verification',
                'resources': {name: {key: value if math.isfinite(value) else None
                                     for key, value in fields.items()}
                              for name, fields in (self.monitor.snapshot or {}).items()
                              if name.startswith('ethercat_')}},
            'hardware_feedback': {'level': level, 'observation': message, 'health': health,
                                 'sample_age_sec': None if self.monitor.last_received is None
                                 else now - self.monitor.last_received,
                                 'joint_state': None if self.monitor.snapshot is None else {
                                     name: {key: (value if math.isfinite(value) else None)
                                            for key, value in self.monitor.snapshot.get(name, {}).items()}
                                     for name in JOINT_NAMES}},
            'hardware_command_write': {'status': 'NOT_OBSERVED',
                                       'reason': 'Controller reference is not proof of hardware write or PDO transmission.'},
            'physical_layers': {name: {'status': 'NOT_OBSERVED',
                                      'reason': 'Reported ROS state interfaces are not independent physical verification.'}
                                for name in ('ethercat_cycle_and_AL', 'cia402_and_enable', 'encoder')},
            'ros_graph': self.graph, 'collection_errors': dict(self.errors),
            'events': list(self.events), 'events_total': self.total_events,
            'events_dropped': self.total_events - len(self.events), 'findings': findings,
        }


def save_report(path, report):
    """Exclusive creation prevents accidental overwriting of an earlier incident."""
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        stream.write(text + '\n')
