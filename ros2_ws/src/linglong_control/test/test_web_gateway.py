"""HTTP + gateway adapter contracts; DDS/ros2_control validation is a separate probe."""
import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from linglong_control_tools.gateway_http import GatewayTransport, RequestTask, make_server
from linglong_control_tools.health import HealthMonitor
from linglong_control_tools.interfaces import JOINT_NAMES


@pytest.fixture
def gateway_module(monkeypatch):
    names = ('rclpy', 'rclpy.node', 'rclpy.action', 'rclpy.clock', 'rclpy.qos',
             'std_msgs', 'std_msgs.msg', 'std_srvs', 'std_srvs.srv', 'control_msgs',
             'control_msgs.msg', 'control_msgs.action', 'trajectory_msgs', 'trajectory_msgs.msg')
    modules = {n: ModuleType(n) for n in names}
    modules['rclpy.node'].Node = type('Node', (), {})
    for name in ('Clock', 'ClockType'):
        setattr(modules['rclpy.clock'], name, Mock())
    for name in ('QoSProfile', 'ReliabilityPolicy', 'DurabilityPolicy'):
        setattr(modules['rclpy.qos'], name, Mock())
    modules['rclpy.action'].ActionClient = Mock()
    modules['std_msgs.msg'].String = Mock()
    modules['std_srvs.srv'].Trigger = NS(Request=lambda: NS())
    modules['control_msgs.msg'].DynamicJointState = Mock()
    modules['control_msgs.action'].FollowJointTrajectory = NS(
        Goal=lambda: NS(trajectory=NS(joint_names=[], points=[])))
    modules['trajectory_msgs.msg'].JointTrajectoryPoint = lambda: NS(time_from_start=NS(sec=0, nanosec=0))
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    path = Path(__file__).parents[1] / 'linglong_control_tools/web_gateway.py'
    spec = importlib.util.spec_from_file_location('web_gateway_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def node_for(module, state='ENABLED'):
    node = module.WebGateway.__new__(module.WebGateway)
    node.backend = 'mock'
    node.monitor = HealthMonitor(stale_timeout=1.)
    node.system = dict(state=state, backend='mock', motion_authorized=state == 'ENABLED',
                       operation=None, feedback_fresh=True, transition_sequence=0)
    node.system_received = time.monotonic()
    node.goal = node.goal_handle = None
    node.lifecycle_pending = False
    node.lifecycle_sequence = 0
    node.limits = {name: dict(lower=-1.57, upper=1.57, max_velocity=.1) for name in JOINT_NAMES}
    node.transport = GatewayTransport(timeout=.3)
    node.action = Mock()
    node.action.server_is_ready.return_value = True
    node.clients = {c: Mock() for c in ('enable', 'disable', 'recover', 'shutdown')}
    for client in node.clients.values():
        client.service_is_ready.return_value = True
    refresh(node)
    return node


def refresh(node):
    now = time.monotonic()
    node.system_received = now
    active = node.system['state'] in ('ENABLED', 'RUNNING')
    health = dict(mock=1., active=float(active), fault_code=0., cycles=now * 100 // 1,
                  period_seconds=.01, max_period_seconds=.01, deadline_misses=0., feedback_age_seconds=0.,
                  hardware_state=6. if active else 4., transition_sequence=6., commands_enabled=float(active))
    values = [(['position', 'velocity'], [.2, 0.]) for _ in JOINT_NAMES]
    node.monitor.receive([*JOINT_NAMES, 'control_health'],
                         values + [(list(health), list(health.values()))], now)


def task(command, payload=None):
    return RequestTask(command, payload or {}, time.monotonic() + 1.)


@pytest.mark.parametrize('state', ['READY', 'FAULT', 'RUNNING', 'SHUTDOWN'])
def test_trajectory_rejected_outside_authorized_enabled_state(gateway_module, state):
    node = node_for(gateway_module, state)
    with pytest.raises(RuntimeError, match='requires ENABLED'):
        node.execute(task('trajectory', dict(offsets=[.01]*4, duration=6)))
    node.action.send_goal_async.assert_not_called()


def test_stale_supervisor_and_frozen_feedback_reject_motion(gateway_module):
    node = node_for(gateway_module)
    node.system_received -= 2.
    assert node.view()['system']['state'] == 'UNKNOWN'
    with pytest.raises(RuntimeError, match='supervisor unavailable'):
        node.execute(task('enable'))
    refresh(node)
    node.monitor.last_progress -= 2.
    with pytest.raises(RuntimeError, match='fresh feedback'):
        node.execute(task('trajectory', dict(offsets=[.01]*4, duration=6)))
    assert node.view()['joints'] is None


@pytest.mark.parametrize('payload', [dict(offsets=[.1]*4, duration=6),
    dict(offsets=[float('nan')]*4, duration=6), dict(offsets=[True]*4, duration=6),
    dict(offsets=[.01]*3, duration=6), dict(offsets=[.01]*4, duration=0)])
def test_invalid_trajectory_never_reaches_action(gateway_module, payload):
    node = node_for(gateway_module)
    with pytest.raises(ValueError):
        node.execute(task('trajectory', payload))
    node.action.send_goal_async.assert_not_called()


def test_accepted_goal_reports_actual_result_and_prevents_parallel_submission(gateway_module):
    node = node_for(gateway_module)
    request = task('trajectory', dict(offsets=[.03]*4, duration=6))
    node.execute(request)
    goal = node.action.send_goal_async.call_args.args[0]
    assert goal.trajectory.joint_names == list(JOINT_NAMES)
    assert goal.trajectory.points[0].positions == [.2]*4
    assert goal.trajectory.points[-1].positions == [.23]*4
    with pytest.raises(RuntimeError, match='already in progress'):
        node.execute(task('trajectory', request.payload))
    handle = Mock(accepted=True)
    node.goal_reply(request, NS(result=lambda: handle))
    assert request.status == 202 and request.result['accepted']
    assert request.result['goal']['status'] == 'ACCEPTED'
    node.goal_result(NS(result=lambda: NS(status=6, result=NS(error_code=-4, error_string='tracking error'))))
    assert node.goal['status'] == 'FAILED' and not node.goal['result']['success']


def test_lifecycle_request_acceptance_is_not_completion(gateway_module):
    node = node_for(gateway_module, 'READY')
    request = task('enable')
    node.execute(request)
    assert node.lifecycle_pending and not request.event.is_set()
    with pytest.raises(RuntimeError, match='awaiting response'):
        node.execute(task('disable'))
    node.lifecycle_reply(request, NS(result=lambda: NS(success=True,
        message=json.dumps(dict(accepted='enable', transition_sequence=9)))))
    assert request.status == 202 and node.system['state'] == 'READY'
    assert not node.lifecycle_pending


def test_expired_queue_task_is_never_executed(gateway_module):
    node = node_for(gateway_module)
    request = RequestTask('enable', {}, time.monotonic() - 1.)
    node.transport.tasks.put(request)
    node.tick()
    assert request.status == 504 and request.event.is_set()
    node.clients['enable'].call_async.assert_not_called()


def test_disable_acknowledgment_blocks_motion_until_new_system_sequence(gateway_module):
    node = node_for(gateway_module)
    request = task('disable')
    node.execute(request)
    with pytest.raises(RuntimeError, match='requires ENABLED'):
        node.execute(task('trajectory', dict(offsets=[.01]*4, duration=6)))
    node.lifecycle_reply(request, NS(result=lambda: NS(success=True,
        message=json.dumps(dict(accepted='disable', transition_sequence=3)))))
    assert node.view()['command_pending']
    with pytest.raises(RuntimeError, match='requires ENABLED'):
        node.execute(task('trajectory', dict(offsets=[.01]*4, duration=6)))
    node.action.send_goal_async.assert_not_called()
    node.system.update(state='READY', motion_authorized=False, transition_sequence=4)
    assert not node.view()['command_pending']


def test_late_cancel_reply_cannot_modify_a_new_goal(gateway_module):
    node = node_for(gateway_module)
    old_handle = NS(goal_id=NS(uuid=[1]*16))
    new_handle = NS(goal_id=NS(uuid=[2]*16))
    node.goal_handle = new_handle
    node.goal = dict(id='new', status='ACCEPTED')
    request = task('cancel')
    response = NS(return_code=0, goals_canceling=[NS(goal_id=old_handle.goal_id)])
    node.cancel_reply(request, NS(result=lambda: response), old_handle)
    assert request.result['accepted']
    assert node.goal['status'] == 'ACCEPTED' and node.goal['id'] == 'new'


@pytest.fixture
def server():
    transport = GatewayTransport(token='test-token', timeout=.2)
    server = make_server(('127.0.0.1', 0), transport)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield transport, f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.)


def http(url, command='state', body=None, token='test-token', origin=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    data = None if body is None else json.dumps(body).encode()
    try:
        response = urlopen(Request(url + '/' + command, data=data, headers=headers), timeout=2.)
    except HTTPError as error:
        response = error
    with response:
        return response.code, json.loads(response.read())


def test_http_auth_staleness_and_no_cross_origin_access(server):
    transport, url = server
    assert http(url, token='wrong')[0] == 401
    assert http(url, origin='http://other-site')[0] == 403
    assert http(url)[0] == 503
    transport.publish(dict(ok=True, connected=True, system=dict(state='READY')))
    assert http(url)[1]['system']['state'] == 'READY'
    transport.received -= 2.
    status, value = http(url)
    assert status == 503 and value['state'] == 'UNKNOWN'


def test_http_timeout_does_not_claim_success(server):
    transport, url = server
    status, value = http(url, 'enable', {})
    assert status == 504 and value['completion_unknown']
    request = transport.tasks.get_nowait()
    assert time.monotonic() >= request.deadline


def test_remote_binding_requires_token():
    with pytest.raises(ValueError, match='requires'):
        make_server(('0.0.0.0', 8091), GatewayTransport())


def test_flask_http_ros_adapter_round_trip(server, gateway_module, monkeypatch):
    flask = pytest.importorskip('flask')
    # This test is also run from colcon; locate the Web module explicitly.
    root = Path(__file__).resolve().parents[4]
    if not (root / 'ros_control_bridge.py').is_file():
        pytest.skip('Web platform source is not included in this standalone ROS package')
    spec = importlib.util.spec_from_file_location('bridge_under_test', root / 'ros_control_bridge.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    transport, url = server
    monkeypatch.setenv('LINGLONG_ROS_URL', url)
    monkeypatch.setenv('LINGLONG_ROS_TOKEN', 'test-token')
    monkeypatch.delenv('LINGLONG_ADMIN_TOKEN', raising=False)
    app = flask.Flask(__name__)
    bridge.register(app)
    node = node_for(gateway_module, 'READY')
    node.transport = transport
    def complete(future_callback):
        node.system.update(state='ENABLED', motion_authorized=True, transition_sequence=3)
        future_callback(NS(result=lambda: NS(success=True,
            message=json.dumps(dict(transition_sequence=3, accepted='enable')))))
    node.clients['enable'].call_async.return_value.add_done_callback.side_effect = complete
    stop = threading.Event()
    def executor():
        while not stop.is_set():
            refresh(node)
            node.tick()
            stop.wait(.01)
    thread = threading.Thread(target=executor, daemon=True)
    thread.start()
    try:
        client = app.test_client()
        response = client.post('/api/ros/enable', json={})
        assert response.status_code == 202 and response.json['accepted']
        for _ in range(30):
            state = client.get('/api/ros/state').json
            if state['system']['state'] == 'ENABLED':
                break
            time.sleep(.01)
        assert state['system']['state'] == 'ENABLED' and state['joints']['joint_1']['position'] == .2
        assert client.post('/api/ros/disable', json={}, headers={'Origin': 'https://untrusted'}).status_code == 403
    finally:
        stop.set()
        thread.join(timeout=2.)
