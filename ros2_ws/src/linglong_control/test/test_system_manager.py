"""Adapter contracts using ROS-shaped fakes; live checks are separate."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from linglong_control_tools.system_state import SystemStateMachine, SystemState as S


@pytest.fixture
def module(monkeypatch):
    names = ('rclpy', 'rclpy.node', 'rclpy.clock', 'rclpy.qos', 'rclpy.utilities', 'action_msgs',
             'action_msgs.msg', 'control_msgs', 'control_msgs.msg', 'std_msgs',
             'std_msgs.msg', 'std_srvs', 'std_srvs.srv', 'controller_manager_msgs',
             'controller_manager_msgs.srv')
    modules = {name: ModuleType(name) for name in names}
    modules['rclpy.node'].Node = type('Node', (), {})
    modules['rclpy.utilities'].remove_ros_args = Mock()
    for name in ('Clock', 'ClockType'):
        setattr(modules['rclpy.clock'], name, Mock())
    for name in ('QoSProfile', 'ReliabilityPolicy', 'DurabilityPolicy'):
        setattr(modules['rclpy.qos'], name, Mock())
    modules['action_msgs.msg'].GoalStatusArray = Mock()
    modules['control_msgs.msg'].DynamicJointState = Mock()
    modules['std_msgs.msg'].String = lambda **kwargs: NS(**kwargs)
    modules['std_srvs.srv'].Trigger = Mock()
    for name in ('ListControllers', 'ListHardwareComponents', 'SetHardwareComponentState', 'SwitchController'):
        class Request:
            STRICT, BEST_EFFORT = 2, 1
            def __init__(self):
                self.target_state = NS()
                self.timeout = NS()
        setattr(modules['controller_manager_msgs.srv'], name, NS(Request=Request))
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    path = Path(__file__).parents[1] / 'linglong_control_tools/system_manager.py'
    spec = importlib.util.spec_from_file_location('system_manager_under_test', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def adapter(module, operation='enable'):
    node = module.SystemManager.__new__(module.SystemManager)
    node.policy = SystemStateMachine()
    node.policy.operation = operation
    node.policy.state = S.ENABLING
    node.plan = [('controller', 'active')]
    node.step = ('hardware', 'active')
    node.pending = None
    node.verifying = False
    node.step_deadline = 1.
    node.operation_timeout = 40.
    node.late_reply_timeout = 10.
    node.restart_required = False
    node.intervention_reason = None
    node.get_logger = Mock()
    node.errors = []
    node.hardware_name = 'arm'
    node.controller_name = 'trajectory'
    node.cm_clients = {key: Mock() for key in ('hardware', 'controller')}
    node.finish = Mock()
    return node


def observer(module):
    node = adapter(module)
    node.stale_timeout = 1.
    node.hardware_future = node.controller_future = None
    node.hardware_time = node.controller_time = None
    node.hardware = node.controller = node.broadcaster = None
    node.cm_clients.update({key: Mock() for key in ('list_hardware', 'list_controllers')})
    for key in ('list_hardware', 'list_controllers'):
        node.cm_clients[key].call_async.side_effect = lambda request: Mock(done=lambda: False)
    return node


def test_read_only_timeout_retries_and_ignores_late_reply(module):
    node = observer(module)
    node.poll(0.)
    old = node.hardware_future[0]
    node.poll(.5)
    assert node.hardware_future[0] is old
    node.poll(1.)
    new = node.hardware_future[0]
    assert new is not old
    node.cm_clients['list_hardware'].remove_pending_request.assert_called_once_with(old)
    old.cancel.assert_called_once()
    old.done = lambda: True
    old.result = lambda: NS(component=[NS(name='arm', state=NS(label='active'))])
    node.poll(1.1)
    assert node.hardware is None and node.hardware_time is None
    new.done = lambda: True
    new.result = lambda: NS(component=[NS(name='arm', state=NS(label='inactive'))])
    node.poll(1.2)
    assert node.hardware == 'inactive' and node.hardware_time == 1.


def test_stale_completed_query_is_not_used(module):
    node = observer(module)
    node.poll(0.)
    old = node.controller_future[0]
    old.done = lambda: True
    node.poll(2.)
    old.result.assert_not_called()
    assert node.controller_time is None
    assert node.cm_clients['list_controllers'].call_async.call_count == 2


def test_missing_query_service_does_not_block_other_endpoint(module):
    node = observer(module)
    node.cm_clients['list_hardware'].service_is_ready.return_value = False
    node.poll(0.)
    assert node.hardware_future is None
    assert node.controller_future is not None


def test_permanent_lifecycle_timeout_requires_full_stack_restart(module):
    node = adapter(module)
    future = Mock(done=lambda: False)
    node.pending = future
    node.advance(2.)
    assert not node.restart_required
    node.advance(11.)
    assert node.restart_required and node.policy.state == S.FAULT
    assert node.policy.operation is None and node.pending is None and not node.plan
    assert node.last_result['completion_unknown']
    assert not node.last_result['success']
    assert 'controller_manager' in node.intervention_reason
    future.cancel.assert_called_once()
    for command in ('enable', 'disable', 'recover', 'shutdown'):
        response = node.request(command, NS())
        assert not response.success and 'restart required' in response.message
    future.done = lambda: True
    node.advance(10000.)
    assert node.restart_required
    assert not node.cm_clients['controller'].call_async.called
    assert not node.cm_clients['hardware'].call_async.called


def test_reply_observed_after_deadline_cannot_enable_controller(module):
    node = adapter(module)
    node.pending = NS(done=lambda: True, result=lambda: NS(ok=True, state=NS(label='active')))
    node.advance(2.)
    assert node.policy.state == S.FAULT
    assert node.finish.call_args.args[0] is False
    node.cm_clients['controller'].call_async.assert_not_called()


def test_terminal_timeout_keeps_publishing_without_compensating_race(module):
    node = adapter(module)
    node.pending = Mock(done=lambda: False)
    node.advance(11.)
    node.poll = Mock()
    node.observe = Mock()
    node.publisher = Mock()
    from linglong_control_tools.health import HealthMonitor
    node.monitor = HealthMonitor()
    node.hardware = node.controller = None
    node.last_sequence = -1
    node.fault_stop_attempted = False
    node.tick()
    message = json.loads(node.publisher.publish.call_args.args[0].data)
    assert message['state'] == 'FAULT' and message['restart_required']
    assert message['operation'] is None and not message['motion_authorized']
    assert message['last_result']['completion_unknown']
    assert message['reason'] == message['intervention_reason']
    node.observe.assert_not_called()
    node.cm_clients['hardware'].call_async.assert_not_called()
    node.cm_clients['controller'].call_async.assert_not_called()


def test_stop_timeout_does_not_issue_competing_hardware_transition(module):
    node = adapter(module, 'disable')
    node.step = ('controller', 'inactive')
    node.plan = [('hardware', 'inactive')]
    node.pending = Mock(done=lambda: False)
    node.advance(11.)
    assert node.restart_required
    assert node.last_result['operation'] == 'disable'
    node.cm_clients['hardware'].call_async.assert_not_called()


def test_late_enable_reply_cannot_race_a_stop(module):
    node = adapter(module)
    done = [False]
    node.pending = NS(done=lambda: done[0], result=lambda: NS(ok=True, state=NS(label='active')))
    future = node.pending
    node.advance(2.)
    assert node.policy.state == S.FAULT
    assert node.pending is future
    assert not node.cm_clients['controller'].call_async.called
    done[0] = True
    node.advance(3.)
    node.finish.assert_called_once()
    assert node.finish.call_args.args[0] is False
    assert not node.cm_clients['controller'].call_async.called


def test_controller_stop_rejection_still_attempts_hardware_stop(module):
    node = adapter(module, 'disable')
    node.plan = [('hardware', 'inactive')]
    node.step = ('controller', 'inactive')
    node.pending = NS(done=lambda: True, result=lambda: NS(ok=False))
    node.advance(.5)
    request = node.cm_clients['hardware'].call_async.call_args.args[0]
    assert request.target_state.label == 'inactive'


def test_successful_service_reply_requires_new_telemetry(module):
    node = adapter(module)
    node.plan = []
    node.step = None
    node.advance(.5)
    assert node.verifying
    assert not node.finish.called
    node.hardware_time = node.controller_time = .4
    node.monitor = NS(last_received=.4)
    node.evidence = lambda now: (dict(hardware_state=6, fault_code=0, commands_enabled=1), True, 'healthy')
    node.hardware = node.controller = node.broadcaster = 'active'
    node.advance(.6)
    assert not node.finish.called
    node.hardware_time = node.controller_time = node.monitor.last_received = .7
    node.advance(.8)
    node.finish.assert_called_once_with(True)


def test_old_action_goals_do_not_mark_new_session_running(module):
    node = adapter(module)
    node.goal_epoch = 2_000_000_000
    def goal(sec, status):
        return NS(status=status, goal_info=NS(stamp=NS(sec=sec, nanosec=0)))
    node.receive_goals(NS(status_list=[goal(1, 2), goal(2, 4)]))
    assert not node.active_goals
    node.receive_goals(NS(status_list=[goal(3, 2)]))
    assert node.active_goals
    node.receive_goals(NS(status_list=[goal(3, 4)]))
    assert not node.active_goals


def test_hardware_reply_wrong_state_is_failure(module):
    node = adapter(module)
    node.pending = NS(done=lambda: True, result=lambda: NS(ok=True, state=NS(label='inactive')))
    node.advance(.5)
    assert node.finish.call_args.args[0] is False
    assert not node.cm_clients['controller'].call_async.called


def test_client_ignores_fault_cached_before_recovery_request(module):
    path = Path(__file__).parents[1] / 'linglong_control_tools/system_client.py'
    spec = importlib.util.spec_from_file_location('system_client_under_test', path)
    client_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client_module)
    callback = []
    def subscribe(kind, topic, receive, qos):
        callback.append(receive)
    updates = [dict(state='FAULT', transition_sequence=6, operation=None, reason='old fault'),
               dict(state='RECOVERING', transition_sequence=7, operation='recover', reason='recovering'),
               dict(state='READY', transition_sequence=8, operation=None, reason='recovered')]
    future = NS(done=lambda: True, result=lambda: NS(success=True,
                message=json.dumps(dict(transition_sequence=7))))
    client = NS(wait_for_service=lambda **kwargs: True, call_async=lambda req: future)
    node = NS(create_subscription=subscribe, create_client=lambda *args: client,
              destroy_subscription=Mock(), destroy_client=Mock())
    client_module.rclpy.spin_once = lambda *args, **kwargs: callback[0](NS(data=json.dumps(updates.pop(0))))
    assert client_module.transition(node, 'recover')['state'] == 'READY'


def test_interval_warning_does_not_override_core_fault_threshold(module):
    node = adapter(module)
    health = dict(hardware_state=6, commands_enabled=1, transition_sequence=6,
                  active=1, fault_code=0, feedback_age_seconds=0)
    node.monitor = NS(snapshot={'control_health': health}, last_received=1., last_progress=1.,
                      status=lambda now: (1, 'control interval exceeds 15 ms'))
    node.hardware_time = node.controller_time = 1.
    node.stale_timeout = 1.
    assert node.evidence(1.1)[1]
    health['feedback_age_seconds'] = .1
    assert not node.evidence(1.1)[1]
    health['feedback_age_seconds'] = 0
    node.monitor.last_progress = 0.
    assert not node.evidence(1.1)[1]


def test_state_message_labels_expired_health_as_history(module):
    from linglong_control_tools.health import HealthMonitor
    node = adapter(module)
    node.policy.operation = None
    node.policy.fail('hardware fault 5: control cycle timeout')
    node.poll = Mock()
    node.observe = Mock()
    node.publisher = Mock()
    node.monitor = HealthMonitor()
    node.monitor.snapshot = {'control_health': {'hardware_state': 6., 'fault_code': 0., 'active': 1.}}
    node.monitor.last_received = node.monitor.last_progress = 0.
    node.hardware = node.controller = 'inactive'
    node.last_result = None
    node.last_sequence = -1
    node.fault_stop_attempted = True
    node.tick()
    message = json.loads(node.publisher.publish.call_args.args[0].data)
    assert message['hardware_state'] == 'UNKNOWN'
    assert message['fault_code'] is None
    assert not message['feedback_fresh']
    assert message['last_observed_health']['active'] == 1.
    assert 'control cycle timeout' in message['reason']


def test_physical_ready_requires_disabled_drive_feedback_not_only_internal_flags(module):
    node = adapter(module)
    node.policy = SystemStateMachine('ethercat_left_arm')
    health = dict(hardware_state=4., commands_enabled=0., transition_sequence=4.,
                  active=0., fault_code=0., feedback_age_seconds=0.)
    resources = {'control_health': health, 'ethercat_bus': dict(
        link_up=1, feedback_valid=1, state_valid=1, wc_state=2, working_counter=12)}
    for slave in (1, 2, 3, 5):
        resources[f'ethercat_slave_{slave}'] = dict(online=1, operational=1, state_valid=1,
            sample_valid=1, al_state=8, mode_display=8, status_word=0x27)
    node.monitor = NS(snapshot=resources, last_received=1., last_progress=1.,
                      status=lambda now: (1, 'inactive'))
    node.hardware_time = node.controller_time = 1.
    node.stale_timeout = 1.
    assert not node.evidence(1.1)[1]
    for slave in (1, 2, 3, 5):
        resources[f'ethercat_slave_{slave}']['status_word'] = 0x40
    assert node.evidence(1.1)[1]
    resources['ethercat_slave_5']['sample_valid'] = 0
    assert not node.evidence(1.1)[1]
