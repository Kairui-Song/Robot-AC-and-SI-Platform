"""Mock recording archives, streaming analysis and isolated state-only replay."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

import yaml

from linglong_control_tools.bag_contracts import (
    BagAudit, TOPIC_TYPES, compare_replay, sha256, validate_profile, write_json)


def new_archive(root, prefix):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / (prefix + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    path.mkdir()
    return path


def finalize(path, manifest):
    manifest['files'] = {p.relative_to(path).as_posix(): sha256(p)
                         for p in sorted(path.rglob('*')) if p.is_file() and p != path / 'manifest.json'}
    write_json(path / 'manifest.json', manifest)


def verify_archive(path):
    path = Path(path).resolve()
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not manifest.get('files'):
        raise ValueError('Unsupported or empty archive manifest')
    for relative, digest in manifest['files'].items():
        file = (path / relative).resolve()
        if not file.is_relative_to(path) or not file.is_file() or sha256(file) != digest:
            raise ValueError('Archive integrity check failed: ' + relative)
    actual = {p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file() and p != path / 'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('Unindexed archive files')
    for required in ('bag/metadata.yaml', 'config/bag_profile.yaml', 'config/bag_qos.yaml'):
        if required not in actual:
            raise ValueError('Missing required archive file: ' + required)
    return manifest


def profile_at(path):
    return validate_profile(yaml.safe_load(Path(path).read_text(encoding='utf-8')))


def check_system_time(parameter_dump):
    dump = yaml.safe_load(Path(parameter_dump).read_text(encoding='utf-8'))
    if not isinstance(dump, dict) or len(dump) != 1:
        raise ValueError('Expected one ROS parameter dump')
    parameters = next(iter(dump.values()))['ros__parameters']
    if parameters.get('use_sim_time', False) is not False:
        raise ValueError('Normal bag profile requires use_sim_time=false')


def check_publishers(node, topics):
    for topic in topics:
        if len(node.get_publishers_info_by_topic(topic)) != 1:
            raise RuntimeError('Require exactly one live publisher: ' + topic)


def player_resume_service(node, topics):
    owners = set()
    for topic in topics:
        publishers = node.get_publishers_info_by_topic(topic)
        if len(publishers) != 1:
            return None
        endpoint = publishers[0]
        owners.add(endpoint.node_namespace.rstrip('/') + '/' + endpoint.node_name)
    if len(owners) != 1:
        return None
    service = owners.pop() + '/resume'
    return service if any(n == service and 'rosbag2_interfaces/srv/Resume' in ts
                          for n, ts in node.get_service_names_and_types()) else None


def analyze_bag(bag, profile, goal_id=None, prefix=''):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.convert import message_to_ordereddict
    from rosidl_runtime_py.utilities import get_message
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id=profile['storage_id']),
                rosbag2_py.ConverterOptions('', ''))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    classes = {}
    audit = BagAudit(profile, goal_id)
    while reader.has_next():
        topic, raw, received = reader.read_next()
        normalized = topic[len(prefix):] if prefix and topic.startswith(prefix + '/') else topic
        if normalized not in TOPIC_TYPES:
            audit.fail('unexpected_topic:' + topic)
            continue
        if types[topic] != TOPIC_TYPES[normalized]:
            audit.fail('wrong_type:' + topic)
            continue
        try:
            if types[topic] not in classes:
                classes[types[topic]] = get_message(types[topic])
            cls = classes[types[topic]]
            data = message_to_ordereddict(deserialize_message(raw, cls))
            audit.add(normalized, types[topic], data, received)
        except Exception as exc:
            audit.fail('deserialize:' + topic + ':' + type(exc).__name__)
    return audit.report()


def goal_id_at(path):
    accepted = path / 'goal.accepted.json'
    if not accepted.exists():
        return None
    ack = json.loads(accepted.read_text())
    result = json.loads((path / 'goal.result.json').read_text())
    if not ack['accepted'] or not result['passed'] or ack['goal_id'] != result['goal_id']:
        raise ValueError('Goal acknowledgement/result mismatch')
    return ack['goal_id']


def cleanup(path, manifest, children, node=None, client=None):
    """Attempt every cleanup even if one child misbehaves; always seal partial evidence."""
    failures = []
    for child in children:
        if child:
            try:
                if not child.stop():
                    failures.append('child did not exit cleanly')
            except Exception as exc:
                failures.append(str(exc))
    if node:
        try:
            import rclpy
            if client:
                node.destroy_client(client)
            node.destroy_node()
            rclpy.shutdown()
        except Exception as exc:
            failures.append(str(exc))
    if failures:
        manifest.update(state='failed', cleanup_errors=failures)
    finalize(path, manifest)
    if failures:
        raise RuntimeError('Cleanup failed; partial archive saved: ' + '; '.join(failures))


def command(args, log, timeout=15, env=None):
    with Path(log).open('x', encoding='utf-8') as stream:
        subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True, env=env)


class Child:
    def __init__(self, args, log, env=None):
        self.stream = Path(log).open('x', encoding='utf-8')
        try:
            self.process = subprocess.Popen(args, stdout=self.stream, stderr=subprocess.STDOUT,
                                            start_new_session=True, env=env)
        except BaseException:
            self.stream.close()
            raise

    def stop(self):
        forced = False
        try:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGINT)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    forced = True
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            return not forced and self.process.returncode == 0
        finally:
            self.stream.close()


def record_command(bag, topics, qos):
    if not topics or any(t not in TOPIC_TYPES and not (t.startswith('/replay/') and t[7:] in TOPIC_TYPES) for t in topics):
        raise ValueError('Only state topics may be recorded')
    return ['ros2', 'bag', 'record', '--storage', 'sqlite3', '--output', str(bag),
            '--node-name', 'linglong_bag_recorder', '--disable-keyboard-controls',
            '--include-hidden-topics', '--qos-profile-overrides-path', str(qos), '--topics', *topics]


def wait_recorder(node, topics, recorder, timeout=15):
    import rclpy
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if recorder.process.poll() is not None:
            raise RuntimeError('Recorder exited before discovery completed')
        rclpy.spin_once(node, timeout_sec=.1)
        if all(any(e.node_name == 'linglong_bag_recorder'
                   for e in node.get_subscriptions_info_by_topic(t)) for t in topics):
            return
    raise TimeoutError('Recorder subscriptions not ready: ' + ', '.join(topics))


def record(options):
    import rclpy
    from ament_index_python.packages import get_package_share_directory, get_package_prefix
    share = Path(get_package_share_directory('linglong_control'))
    path = new_archive(options.root, 'record')
    print('Archive: ' + str(path), flush=True)
    manifest = {'schema_version': 1, 'kind': 'record', 'state': 'failed', 'backend': 'mock',
                'scenario': options.scenario, 'ros_distro': os.getenv('ROS_DISTRO'),
                'ros_domain_id': os.getenv('ROS_DOMAIN_ID', '0'), 'rmw': os.getenv('RMW_IMPLEMENTATION', 'default'),
                'requested_duration_sec': options.duration}
    recorder = motion = node = None
    try:
        for directory in ('config', 'launch', 'urdf'):
            shutil.copytree(share / directory, path / directory)
        shutil.copy2(share / 'package.xml', path / 'package.xml')
        library = Path(get_package_prefix('linglong_control')) / 'lib/liblinglong_sim_system.so'
        manifest['mock_plugin_sha256'] = sha256(library)
        shutil.copytree(Path(__file__).parent, path / 'source',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        profile = profile_at(path / 'config/bag_profile.yaml')
        for name in ('controller_manager', 'arm_trajectory_controller',
                     'linglong_control_diagnostics', 'robot_state_publisher'):
            command(['ros2', 'param', 'dump', '/' + name], path / (name + '.parameters.yaml'))
            check_system_time(path / (name + '.parameters.yaml'))
        command(['ros2', 'run', 'linglong_control', 'fault_snapshot', '--duration', '1',
                 '--output', str(path / 'before.json')], path / 'before.log')
        before = json.loads((path / 'before.json').read_text())
        if before['hardware_feedback']['level'] != 0 or before['hardware_feedback']['health']['mock'] != 1:
            raise RuntimeError('Recording normal baseline requires healthy mock feedback')
        controllers = (before.get('controllers') or {}).get('items', [])
        matched = [c for c in controllers if c['name'] == 'arm_trajectory_controller']
        from linglong_control_tools.interfaces import JOINT_NAMES
        if (len(matched) != 1 or matched[0]['state'] != 'active' or
                set(matched[0]['claimed_interfaces']) != {n + '/position' for n in JOINT_NAMES}):
            raise RuntimeError('Expected active controller owning exactly four position interfaces')
        command(['ros2', 'run', 'linglong_control', 'tf_probe', '--output', str(path / 'tf.json')], path / 'tf.log')
        rclpy.init()
        node = rclpy.create_node('linglong_archive_observer')
        cmd = record_command(path / 'bag', list(profile['topics']), path / 'config/bag_qos.yaml')
        manifest['record_command'] = cmd
        recorder = Child(cmd, path / 'record.log')
        required = [t for t, s in profile['topics'].items() if s['min_count'] > 0]
        if options.scenario == 'wave':
            required.append('/arm_trajectory_controller/follow_joint_trajectory/_action/status')
        wait_recorder(node, required, recorder)
        check_publishers(node, required)
        started = time.monotonic()
        if options.scenario == 'wave':
            cmd = ['ros2', 'run', 'linglong_control', 'left_arm_motion', '--wave', '--duration', '6',
                   '--goal-output', str(path / 'goal.json')]
            manifest['motion_command'] = cmd
            motion = Child(cmd, path / 'motion.log')
        while time.monotonic() - started < options.duration:
            rclpy.spin_once(node, timeout_sec=.1)
            if recorder.process.poll() is not None:
                raise RuntimeError('Recorder stopped early')
            if motion and motion.process.poll() not in (None, 0):
                raise RuntimeError('Mock wave failed; inspect motion.log')
        if motion and motion.process.poll() != 0:
            raise TimeoutError('Mock wave did not finish within recording window')
        check_publishers(node, required)
        if not recorder.stop():
            raise RuntimeError('Recorder did not finalize cleanly')
        recorder = None
        goal_id = goal_id_at(path)
        if options.scenario == 'wave' and goal_id is None:
            raise RuntimeError('Wave completed without archived Goal UUID')
        report = analyze_bag(path / 'bag', profile, goal_id)
        write_json(path / 'analysis.json', report)
        manifest.update(state='complete', acceptance_passed=report['passed'])
        if not report['passed']:
            raise RuntimeError('Recording finalized but data acceptance failed; inspect analysis.json')
    except BaseException as exc:
        manifest['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        cleanup(path, manifest, [motion, recorder], node)


def replay_command(bag, topics, qos):
    if not topics or not set(topics).issubset(TOPIC_TYPES):
        raise ValueError('Replay is restricted to the state topic allowlist')
    return ['ros2', 'bag', 'play', str(bag), '--start-paused', '--disable-keyboard-controls',
            '--wait-for-all-acked', '2000', '--qos-profile-overrides-path', str(qos),
            '--topics', *topics, '--remap', *[t + ':=/replay' + t for t in topics]]


def replay(options):
    import rclpy
    from rosbag2_interfaces.srv import Resume
    source = Path(options.archive).resolve()
    original = verify_archive(source)
    if options.domain == int(os.getenv('ROS_DOMAIN_ID', '0')) or options.domain == int(original.get('ros_domain_id', '0')):
        raise ValueError('Replay domain must differ from current and recorded domains')
    profile = profile_at(source / 'config/bag_profile.yaml')
    baseline = analyze_bag(source / 'bag', profile, goal_id_at(source))
    if original.get('state') != 'complete' or not baseline['passed']:
        raise ValueError('Replay acceptance requires a complete, passing source archive')
    if baseline['duration_sec'] > 180:
        raise ValueError('Replay tool supports archives up to 180 seconds')
    path = new_archive(options.root, 'replay')
    print('Replay archive: ' + str(path), flush=True)
    manifest = {'schema_version': 1, 'kind': 'replay', 'state': 'failed',
                'source_manifest_sha256': sha256(source / 'manifest.json'),
                'source': str(source), 'ros_domain_id': options.domain}
    env = dict(os.environ, ROS_DOMAIN_ID=str(options.domain), ROS_LOCALHOST_ONLY='1')
    recorder = player = node = client = None
    try:
        os.environ['ROS_LOCALHOST_ONLY'] = '1'
        rclpy.init(domain_id=options.domain)
        node = rclpy.create_node('linglong_replay_observer')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        if any(n != node.get_name() for n, _ in node.get_node_names_and_namespaces()):
            raise RuntimeError('Replay domain is occupied; choose an unused domain')
        topics = [t for t, s in baseline['topics'].items() if s['count'] > 0]
        # Replay transport intentionally reliable/volatile after explicit discovery.
        # Compare message content, not live QoS or historical receipt timing.
        qos = {t: {'history': 'keep_last', 'depth': 1000, 'reliability': 'reliable',
                   'durability': 'volatile'} for t in topics}
        (path / 'play_qos.yaml').write_text(yaml.safe_dump(qos))
        (path / 'record_qos.yaml').write_text(yaml.safe_dump({'/replay'+t: q for t, q in qos.items()}))
        cmd = record_command(path / 'bag', ['/replay'+t for t in topics], path / 'record_qos.yaml')
        recorder = Child(cmd, path / 'record.log', env)
        cmd = replay_command(source / 'bag', topics, path / 'play_qos.yaml')
        manifest['play_command'] = cmd
        player = Child(cmd, path / 'play.log', env)
        wait_recorder(node, ['/replay'+t for t in topics], recorder)
        # Discover the player service instead of relying on distribution-specific CLI node prefixes.
        deadline = time.monotonic() + 10
        resume = None
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
            resume = player_resume_service(node, ['/replay'+t for t in topics])
            if resume:
                break
        if not resume:
            raise RuntimeError('Cannot uniquely identify paused player resume service')
        client = node.create_client(Resume, resume)
        if not client.wait_for_service(timeout_sec=5):
            raise TimeoutError('Player resume service unavailable')
        future = client.call_async(Resume.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=5)
        if not future.done() or future.exception():
            raise TimeoutError('Player resume not acknowledged')
        deadline = time.monotonic() + baseline['duration_sec'] + 30
        while player.process.poll() is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
            if recorder.process.poll() is not None:
                raise RuntimeError('Replay recorder stopped early')
        if player.process.poll() != 0:
            raise RuntimeError('Replay player failed or timed out')
        # Ack is DDS transport evidence only; allow recorder callbacks to drain before SIGINT.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        if not recorder.stop():
            raise RuntimeError('Replay recorder failed to finalize')
        recorder = None
        repeated = analyze_bag(path / 'bag', profile, goal_id_at(source), prefix='/replay')
        write_json(path / 'source-analysis.json', baseline)
        write_json(path / 'replay-analysis.json', repeated)
        result = compare_replay(baseline, repeated)
        write_json(path / 'comparison.json', result)
        manifest.update(state='complete', acceptance_passed=result['passed'])
        if not result['passed']:
            raise RuntimeError('Replay content mismatch; inspect comparison.json')
    except BaseException as exc:
        manifest['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        cleanup(path, manifest, [player, recorder], node, client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    record_parser = sub.add_parser('record')
    record_parser.add_argument('--root', default='verification/bags')
    record_parser.add_argument('--scenario', choices=('observe', 'wave'), default='observe')
    record_parser.add_argument('--duration', type=int, default=20, choices=range(10, 121), metavar='10..120')
    analyze_parser = sub.add_parser('analyze')
    analyze_parser.add_argument('archive')
    analyze_parser.add_argument('--output', required=True)
    replay_parser = sub.add_parser('replay-verify')
    replay_parser.add_argument('archive')
    replay_parser.add_argument('--root', default='verification/replays')
    replay_parser.add_argument('--domain', type=int, default=88, choices=range(0, 102), metavar='0..101')
    options = parser.parse_args()
    if options.mode == 'analyze':
        source = Path(options.archive).resolve()
        verify_archive(source)
        if Path(options.output).resolve().is_relative_to(source):
            parser.error('Analysis output must be outside the sealed source archive')
        result = analyze_bag(source / 'bag', profile_at(source / 'config/bag_profile.yaml'), goal_id_at(source))
        write_json(options.output, result)
        if not result['passed']:
            raise SystemExit(1)
    else:
        if os.name != 'posix' or os.getenv('ROS_DISTRO') != 'jazzy':
            parser.error('Run in the existing Ubuntu/Jazzy environment; this tool installs nothing')
        if options.mode == 'record':
            record(options)
        else:
            replay(options)
