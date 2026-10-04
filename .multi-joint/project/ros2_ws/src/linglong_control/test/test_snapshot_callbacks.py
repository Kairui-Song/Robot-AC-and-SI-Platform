"""Callback contract tests with message-shaped objects; not a ROS runtime test."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from linglong_control_tools.evidence import Evidence
from linglong_control_tools.health import JOINT_NAMES


@pytest.fixture
def module(monkeypatch):
    names = ('rclpy', 'rclpy.node', 'rclpy.qos', 'rclpy.utilities', 'action_msgs',
             'action_msgs.msg', 'control_msgs', 'control_msgs.msg',
             'controller_manager_msgs', 'controller_manager_msgs.srv')
    modules = {name: ModuleType(name) for name in names}
    modules['rclpy.node'].Node = type('Node', (), {})
    for name in ('QoSProfile', 'ReliabilityPolicy', 'DurabilityPolicy',
                 'qos_check_compatible', 'qos_profile_action_status_default'):
        setattr(modules['rclpy.qos'], name, Mock())
    modules['rclpy.utilities'].remove_ros_args = Mock()
    modules['action_msgs.msg'].GoalStatusArray = Mock()
    modules['control_msgs.msg'].DynamicJointState = Mock()
    modules['control_msgs.msg'].JointTrajectoryControllerState = Mock()
    modules['controller_manager_msgs.srv'].ListControllers = Mock()
    modules['controller_manager_msgs.srv'].ListHardwareComponents = Mock()
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    path = Path(__file__).parents[1] / 'linglong_control_tools/fault_snapshot.py'
    spec = importlib.util.spec_from_file_location('snapshot_under_test', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_action_status_array_has_no_header(module):
    node = NS(evidence=Evidence(0))
    status = NS(goal_info=NS(goal_id=NS(uuid=[1] * 16), stamp=NS(sec=2, nanosec=3)), status=4)
    module.FaultSnapshot.action(node, NS(status_list=[status]))
    goal = node.evidence.action['goals'][0]
    assert goal['goal_stamp_ns'] == 2000000003
    assert goal['goal_id'] == '01' * 16


def test_action_history_is_bounded(module):
    node = NS(evidence=Evidence(0))
    status = NS(goal_info=NS(goal_id=NS(uuid=[1] * 16), stamp=NS(sec=2, nanosec=3)), status=4)
    module.FaultSnapshot.action(node, NS(status_list=[status] * 50))
    assert node.evidence.action['total_statuses'] == 50
    assert len(node.evidence.action['goals']) == 32
    module.FaultSnapshot.action(node, NS(status_list=[]))
    assert node.evidence.action['total_statuses'] == 0
    assert node.evidence.action['goals'] == []


def test_jazzy_controller_reference_and_feedback(module):
    node = NS(evidence=Evidence(0))
    msg = NS(joint_names=JOINT_NAMES, reference=NS(positions=[.1] * 4),
             feedback=NS(positions=[.09] * 4), header=NS(stamp=NS(sec=2, nanosec=0)))
    module.FaultSnapshot.controller(node, msg)
    assert node.evidence.frames[-1]['reference'] == [.1] * 4
    assert node.evidence.frames[-1]['stamp_ns'] == 2000000000


def test_service_timeout_preserves_partial_read_only_evidence(module, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module, 'time', NS(monotonic=lambda: clock[0]))
    module.rclpy.spin_once = lambda *args, **kwargs: clock.__setitem__(0, clock[0] + .1)
    response = NS(controller=[NS(name='arm_trajectory_controller', state='inactive',
                                 type='trajectory', claimed_interfaces=[])])
    future = NS(done=lambda: True, result=lambda: response)
    good = NS(service_is_ready=lambda: True, call_async=lambda request: future)
    absent = NS(service_is_ready=lambda: False)
    names, destroyed = [], []

    def create(srv_type, name):
        names.append(name)
        return good if name.endswith('/list_controllers') else absent

    node = NS(evidence=Evidence(0), create_client=create, destroy_client=destroyed.append)
    module.FaultSnapshot.collect_services(node)
    assert node.evidence.controllers['items'][0]['state'] == 'inactive'
    assert node.evidence.hardware is None
    assert 'deadline' in node.evidence.errors['hardware']
    assert len(destroyed) == 2
    assert names == ['/controller_manager/list_controllers', '/controller_manager/list_hardware_components']
    assert clock[0] < 3.2
