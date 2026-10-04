import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from linglong_control_tools.bag_contracts import TOPIC_TYPES, sha256, write_json
from linglong_control_tools.bag_session import (
    finalize, new_archive, verify_archive, record_command, replay_command, goal_id_at, cleanup)


def archive(tmp_path):
    path = new_archive(tmp_path, 'record')
    (path/'bag').mkdir()
    (path/'config').mkdir()
    for name in ('bag/metadata.yaml', 'config/bag_profile.yaml', 'config/bag_qos.yaml'):
        (path/name).write_text('test')
    finalize(path, {'schema_version': 1, 'state': 'complete'})
    return path


def test_archive_sealing_detects_tampering_and_extra_files(tmp_path):
    path = archive(tmp_path)
    assert verify_archive(path)['state'] == 'complete'
    (path/'extra').write_text('new')
    with pytest.raises(ValueError, match='Unindexed'):
        verify_archive(path)
    (path/'extra').unlink()
    (path/'bag/metadata.yaml').write_text('changed')
    with pytest.raises(ValueError, match='integrity'):
        verify_archive(path)


def test_archive_rejects_path_escape_and_missing_file(tmp_path):
    path = archive(tmp_path)
    manifest = json.loads((path/'manifest.json').read_text())
    outside = tmp_path/'outside'
    outside.write_text('secret')
    manifest['files']['../outside'] = sha256(outside)
    (path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='integrity'):
        verify_archive(path)


def test_unique_runs_and_no_report_overwrite(tmp_path):
    assert new_archive(tmp_path, 'record') != new_archive(tmp_path, 'record')
    write_json(tmp_path/'report.json', {'passed': False})
    with pytest.raises(FileExistsError):
        write_json(tmp_path/'report.json', {'passed': True})


def test_commands_allow_only_state_topics_and_replay_remaps_every_topic():
    topics = list(TOPIC_TYPES)
    record = record_command(Path('bag'), topics, Path('qos.yaml'))
    assert '--include-hidden-topics' in record and '--all' not in record
    replay = replay_command(Path('bag'), topics, Path('qos.yaml'))
    assert '--start-paused' in replay and '--publish-service-requests' not in replay
    assert set(replay[replay.index('--remap')+1:]) == {t+':=/replay'+t for t in topics}
    for command in (record_command, replay_command):
        with pytest.raises(ValueError):
            command(Path('bag'), ['/joint_command'], Path('qos'))


def test_goal_result_is_bound_to_accepted_uuid(tmp_path):
    write_json(tmp_path/'goal.accepted.json', {'accepted': True, 'goal_id': '01'*16})
    write_json(tmp_path/'goal.result.json', {'passed': True, 'goal_id': '02'*16})
    with pytest.raises(ValueError, match='mismatch'):
        goal_id_at(tmp_path)


def test_cleanup_attempts_all_children_and_seals_failure(tmp_path):
    calls = []
    def broken():
        calls.append('broken')
        raise RuntimeError('process failure')
    def good():
        calls.append('good')
        return True
    with pytest.raises(RuntimeError, match='Cleanup failed'):
        cleanup(tmp_path, {'schema_version': 1, 'state': 'complete'}, [NS(stop=broken), NS(stop=good)])
    assert calls == ['broken', 'good']
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    assert manifest['state'] == 'failed' and manifest['cleanup_errors']


def test_recorder_readiness_times_out_and_detects_early_exit(monkeypatch):
    import sys
    from types import ModuleType
    from linglong_control_tools import bag_session as module
    clock = [0.]
    fake = ModuleType('rclpy')
    fake.spin_once = lambda *a, **kw: clock.__setitem__(0, clock[0]+.1)
    monkeypatch.setitem(sys.modules, 'rclpy', fake)
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: clock[0]))
    node = NS(get_subscriptions_info_by_topic=lambda topic: [])
    recorder = NS(process=NS(poll=lambda: None))
    with pytest.raises(TimeoutError):
        module.wait_recorder(node, ['/joint_states'], recorder, timeout=.3)
    recorder.process.poll = lambda: 1
    with pytest.raises(RuntimeError, match='exited'):
        module.wait_recorder(node, ['/joint_states'], recorder)


def test_sequential_reader_adapter_uses_deserialized_content(monkeypatch):
    import sys
    from types import ModuleType
    from linglong_control_tools import bag_session as module
    modules = {n: ModuleType(n) for n in ('rosbag2_py', 'rclpy.serialization',
        'rosidl_runtime_py.convert', 'rosidl_runtime_py.utilities')}
    rows = iter([('/joint_states', b'payload', 1_000_000_000)])
    remaining = [True]
    def read():
        remaining[0] = False
        return next(rows)
    reader = NS(open=lambda *a: None, has_next=lambda: remaining[0], read_next=read,
                get_all_topics_and_types=lambda: [NS(name='/joint_states', type=TOPIC_TYPES['/joint_states'])])
    modules['rosbag2_py'].SequentialReader = lambda: reader
    modules['rosbag2_py'].StorageOptions = lambda **kw: kw
    modules['rosbag2_py'].ConverterOptions = lambda *a: a
    modules['rclpy.serialization'].deserialize_message = lambda raw, cls: {
        'header': {'stamp': {'sec': 1, 'nanosec': 0}},
        'name': ['joint_1', 'joint_2', 'joint_3', 'joint_5'], 'position': [0]*4, 'velocity': [0]*4}
    modules['rosidl_runtime_py.convert'].message_to_ordereddict = lambda m: m
    modules['rosidl_runtime_py.utilities'].get_message = lambda name: object
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    report = module.analyze_bag('fake', module.profile_at(Path(__file__).parents[1]/'config/bag_profile.yaml'))
    assert report['topics']['/joint_states']['count'] == 1
    assert not report['passed']  # A readable bag alone cannot pass the contract.


def test_parameter_time_basis_and_duplicate_publishers_rejected(tmp_path):
    from linglong_control_tools.bag_session import check_system_time, check_publishers
    path = tmp_path/'params.yaml'
    path.write_text('/node:\n  ros__parameters:\n    use_sim_time: true\n')
    with pytest.raises(ValueError, match='use_sim_time'):
        check_system_time(path)
    path.write_text('/node:\n  ros__parameters:\n    use_sim_time: false\n')
    check_system_time(path)
    for publishers in ([], [1, 2]):
        with pytest.raises(RuntimeError, match='exactly one'):
            check_publishers(NS(get_publishers_info_by_topic=lambda topic: publishers), ['/joint_states'])


def test_resume_targets_player_not_recorder_with_same_service_type():
    from linglong_control_tools.bag_session import player_resume_service
    services = [('/player/resume', ['rosbag2_interfaces/srv/Resume']),
                ('/linglong_bag_recorder/resume', ['rosbag2_interfaces/srv/Resume'])]
    node = NS(get_service_names_and_types=lambda: services,
              get_publishers_info_by_topic=lambda topic: [NS(node_name='player', node_namespace='/')])
    assert player_resume_service(node, ['/replay/joint_states']) == '/player/resume'
    node.get_publishers_info_by_topic = lambda topic: [
        NS(node_name='player', node_namespace='/'), NS(node_name='other', node_namespace='/')]
    assert player_resume_service(node, ['/replay/joint_states']) is None


@pytest.mark.parametrize('accepted', [True, False])
def test_record_orchestration_seals_analysis_outcome(monkeypatch, tmp_path, accepted):
    """Fake ROS/processes exercise orchestration, not storage or DDS integration."""
    import sys
    from types import ModuleType
    from linglong_control_tools import bag_session as module
    from linglong_control_tools.interfaces import JOINT_NAMES
    clock = [0.]
    pkg = Path(__file__).parents[1]
    prefix = tmp_path/'prefix'
    (prefix/'lib').mkdir(parents=True)
    (prefix/'lib/liblinglong_sim_system.so').write_bytes(b'offline fake binary')
    packages = ModuleType('ament_index_python.packages')
    packages.get_package_share_directory = lambda name: str(pkg)
    packages.get_package_prefix = lambda name: str(prefix)
    monkeypatch.setitem(sys.modules, 'ament_index_python', ModuleType('ament_index_python'))
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', packages)
    ros = ModuleType('rclpy')
    ros.init = lambda: None
    ros.shutdown = lambda: None
    ros.spin_once = lambda *a, **kw: clock.__setitem__(0, clock[0]+1)
    ros.create_node = lambda name: NS(destroy_node=lambda: None,
        get_publishers_info_by_topic=lambda topic: [1])
    monkeypatch.setitem(sys.modules, 'rclpy', ros)
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, 'wait_recorder', lambda *a: None)
    def command(args, log):
        if args[1] == 'param':
            Path(log).write_text('/node:\n  ros__parameters:\n    use_sim_time: false\n')
        else:
            Path(log).write_text('fake command')
            output = Path(args[args.index('--output')+1])
            if 'fault_snapshot' in args:
                write_json(output, {'hardware_feedback': {'level': 0, 'health': {'mock': 1}},
                    'controllers': {'items': [{'name': 'arm_trajectory_controller', 'state': 'active',
                        'claimed_interfaces': [n+'/position' for n in JOINT_NAMES]}]}})
            else:
                write_json(output, {'passed': True})
    monkeypatch.setattr(module, 'command', command)
    stopped = []
    class FakeChild:
        def __init__(self, args, log):
            Path(log).write_text('fake recorder')
            bag = Path(args[args.index('--output')+1])
            bag.mkdir()
            (bag/'metadata.yaml').write_text('fake storage')
            self.process = NS(poll=lambda: None)
        def stop(self):
            stopped.append(True)
            return True
    monkeypatch.setattr(module, 'Child', FakeChild)
    monkeypatch.setattr(module, 'analyze_bag', lambda *a: {'passed': accepted})
    options = NS(root=tmp_path/'runs', scenario='observe', duration=10)
    if accepted:
        module.record(options)
    else:
        with pytest.raises(RuntimeError, match='acceptance failed'):
            module.record(options)
    path = next((tmp_path/'runs').iterdir())
    manifest = verify_archive(path)
    assert manifest['state'] == 'complete'
    assert manifest['acceptance_passed'] is accepted
    assert len(stopped) == 1
