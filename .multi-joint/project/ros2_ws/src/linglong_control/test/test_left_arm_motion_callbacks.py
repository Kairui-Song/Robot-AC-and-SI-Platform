"""Message-shaped Action contracts only; no ROS runtime or hardware."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from linglong_control_tools.health import JOINT_NAMES, HEALTH_KEYS


@pytest.fixture
def harness(monkeypatch):
    modules = {n: ModuleType(n) for n in (
        'rclpy', 'rclpy.node', 'rclpy.action', 'rclpy.qos', 'rclpy.utilities',
        'action_msgs', 'action_msgs.msg', 'control_msgs', 'control_msgs.msg',
        'control_msgs.action', 'trajectory_msgs', 'trajectory_msgs.msg')}
    modules['rclpy.node'].Node = Mock()
    modules['rclpy.qos'].QoSProfile = Mock()
    modules['rclpy.qos'].ReliabilityPolicy = NS(BEST_EFFORT=1)
    modules['rclpy.utilities'].remove_ros_args = Mock()
    modules['action_msgs.msg'].GoalStatus = NS(STATUS_SUCCEEDED=4)
    modules['control_msgs.msg'].DynamicJointState = Mock()
    modules['control_msgs.action'].FollowJointTrajectory = NS(
        Goal=lambda: NS(trajectory=NS(joint_names=[], points=[])))
    modules['trajectory_msgs.msg'].JointTrajectoryPoint = lambda: NS(
        positions=[], time_from_start=NS(sec=0, nanosec=0))
    clock = [0.]
    state = NS(goals=[], fail=False, rejected=False, backend=1, cycles=0, result_ready=True)
    future = lambda value: NS(done=lambda: True, result=lambda: value)
    result_future = NS(done=lambda: state.result_ready,
                       result=lambda: NS(status=4, result=NS(error_code=0, error_string='')))
    handle = NS(accepted=True, goal_id=NS(uuid=[1]*16), get_result_async=lambda: result_future)
    handle.cancel_goal_async = Mock(return_value=future(NS(return_code=0,
        goals_canceling=[NS(goal_id=handle.goal_id)])))
    def send(goal):
        state.goals.append(goal)
        handle.accepted = not state.rejected
        return future(handle)
    client = NS(wait_for_server=lambda **kw: True, send_goal_async=send, destroy=Mock())
    modules['rclpy.action'].ActionClient = lambda *a: client
    node = NS(destroy_subscription=Mock(), get_logger=lambda: NS(error=Mock()))
    def subscribe(typ, name, callback, qos):
        state.callback = callback
        return 1
    node.create_subscription = subscribe
    def spin(*a, **kw):
        clock[0] += .05
        state.cycles += 1
        values = [NS(interface_names=['position', 'velocity'], values=[0, 0]) for _ in JOINT_NAMES]
        values.append(NS(interface_names=HEALTH_KEYS,
            values=[state.backend, 1, 10 if state.fail and state.goals else 0,
                    state.cycles, .01, .01, 0, 0]))
        state.callback(NS(joint_names=[*JOINT_NAMES, 'control_health'], interface_values=values))
    modules['rclpy'].spin_once = spin
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    # Isolate the shared wait helper from ROS imports; test the client's contracts.
    helper = ModuleType('linglong_control_tools.trajectory_demo')
    helper.wait = lambda node, f, timeout: f.result()
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    path = Path(__file__).parents[1] / 'linglong_control_tools/left_arm_motion.py'
    spec = importlib.util.spec_from_file_location('motion_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: clock[0]))
    options = NS(backend='mock', hardware_config=None, duration=6, offsets=None, amplitude=.03)
    return module, node, options, state, handle, client


def test_single_goal_contains_all_four_joints(harness):
    module, node, options, state, handle, client = harness
    module.run(node, options)
    assert len(state.goals) == 1
    goal = state.goals[0]
    assert goal.trajectory.joint_names == list(JOINT_NAMES)
    assert all(len(p.positions) == 4 for p in goal.trajectory.points)
    handle.cancel_goal_async.assert_not_called()
    client.destroy.assert_called_once()
    node.destroy_subscription.assert_called_once()


def test_fault_cancels_the_whole_goal(harness):
    module, node, options, state, handle, client = harness
    state.fail, state.result_ready = True, False
    with pytest.raises(RuntimeError, match='unhealthy'):
        module.run(node, options)
    handle.cancel_goal_async.assert_called_once()
    client.destroy.assert_called_once()


def test_wrong_backend_never_sends_goal(harness):
    module, node, options, state, handle, client = harness
    state.backend = 0
    with pytest.raises(RuntimeError, match='matching'):
        module.run(node, options)
    assert not state.goals


def test_rejected_goal_does_not_claim_success(harness):
    module, node, options, state, handle, client = harness
    state.rejected = True
    with pytest.raises(RuntimeError, match='rejected'):
        module.run(node, options)
    handle.cancel_goal_async.assert_not_called()
