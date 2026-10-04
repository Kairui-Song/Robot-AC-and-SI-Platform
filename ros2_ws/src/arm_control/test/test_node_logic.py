"""Exercise callbacks without ROS installed; these do not validate DDS or launch."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import Mock, patch

import pytest
from arm_control.backend import Calibration, NAMES


@pytest.fixture
def node():
    modules = {name: ModuleType(name) for name in (
        'rclpy', 'rclpy.node', 'rclpy.qos', 'sensor_msgs', 'sensor_msgs.msg',
        'trajectory_msgs', 'trajectory_msgs.msg')}
    modules['rclpy.node'].Node = type('Node', (), {})
    modules['rclpy.qos'].QoSProfile = Mock()
    modules['rclpy.qos'].DurabilityPolicy = Mock()
    modules['sensor_msgs.msg'].JointState = lambda: NS(header=NS())
    modules['trajectory_msgs.msg'].JointTrajectory = Mock()
    spec = importlib.util.spec_from_file_location(
        'arm_node_under_test', Path(__file__).parents[1] / 'arm_control/node.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    obj = module.ArmControl.__new__(module.ArmControl)
    obj.calibration = Calibration([1000.] * 4, [0.] * 4, [-1.] * 4, [1.] * 4)
    obj.backend = Mock()
    obj.backend.read.return_value = [.01] * 4
    obj.get_logger = Mock(return_value=Mock())
    obj.get_clock = Mock(return_value=NS(now=lambda: NS(nanoseconds=10**9, to_msg=lambda: 'now')))
    obj.publisher = Mock()
    obj.active, obj.faulted, obj.target = False, False, None
    obj.max_step, obj.max_age, obj.timeout, obj.last_command = .05, .5, 2., 0.
    return obj


def command():
    return NS(joint_names=list(NAMES), header=NS(stamp=NS(sec=0, nanosec=0)),
              points=[NS(positions=[.02] * 4, velocities=[], accelerations=[],
                         effort=[], time_from_start=NS(sec=0, nanosec=0))])


def test_command_then_feedback_reads_actual(node):
    node.command(command())
    node.backend.write.assert_called_with([.02] * 4)
    node.tick()
    assert node.publisher.publish.call_args.args[0].position == [.01] * 4


def test_partial_write_failure_disables_and_latches(node):
    node.backend.write.side_effect = RuntimeError('third slave failed')
    node.command(command())
    node.backend.stop.assert_called_once()
    assert node.faulted and not node.active
    node.command(command())
    assert node.backend.write.call_count == 1


def test_watchdog(node):
    node.active = True
    node.tick()
    node.backend.stop.assert_called_once()
    node.backend.write.assert_not_called()
    assert node.faulted


def test_invalid_trajectory_does_no_io(node):
    msg = command()
    msg.points *= 2
    node.command(msg)
    node.backend.read.assert_not_called()
    node.backend.write.assert_not_called()


def test_failed_feedback_is_not_published(node):
    node.active = True
    import time
    node.last_command = time.monotonic()
    node.backend.read.side_effect = RuntimeError('offline')
    node.tick()
    node.publisher.publish.assert_not_called()
    node.backend.stop.assert_called_once()


def test_stale_and_future_commands_rejected(node):
    for sec, nanosec in [(0, 1), (2, 0)]:
        msg = command()
        msg.header.stamp = NS(sec=sec, nanosec=nanosec)
        node.command(msg)
    node.backend.write.assert_not_called()
