"""Bounded MOCK-only Action smoke test, starting from current measured simulation state."""
import time
import argparse
import json
import sys

import rclpy
from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import DynamicJointState
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.utilities import remove_ros_args
from trajectory_msgs.msg import JointTrajectoryPoint

from linglong_control_tools.health import HealthMonitor, JOINT_NAMES
from linglong_control_tools.acceptance import HoldWindow, cancel_matches
from linglong_control_tools.interfaces import DYNAMIC_STATES, TRAJECTORY_ACTION


def wait(node, future, timeout):
    deadline = time.monotonic() + timeout
    while rclpy.ok() and not future.done() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
    if not future.done():
        raise TimeoutError('ROS operation timed out')
    return future.result()


def observe_hold(node, monitor, duration=0.6, reference=None, active=True):
    window = None
    last_received = monitor.last_received
    deadline = time.monotonic() + duration + 2.0
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.02)
        now = time.monotonic()
        if monitor.status(now)[0] not in (0, 1):
            raise RuntimeError('healthy feedback lost during hold observation')
        if monitor.last_received == last_received:
            continue
        last_received = monitor.last_received
        h = monitor.snapshot['control_health']
        if h['mock'] != 1 or h['active'] != int(active) or h['feedback_age_seconds'] != 0:
            raise RuntimeError('active fresh MOCK feedback required')
        positions = [monitor.snapshot[n]['position'] for n in JOINT_NAMES]
        velocities = [monitor.snapshot[n]['velocity'] for n in JOINT_NAMES]
        if window is None:
            window = HoldWindow(positions if reference is None else reference)
        window.add(positions, velocities, h['cycles'], last_received)
        if window.samples >= 10 and window.last_time - window.first_time >= duration:
            return window.result(duration)
    raise TimeoutError('insufficient feedback for hold observation')


def run(node, cancel=False):
    monitor = HealthMonitor()
    subscription = node.create_subscription(DynamicJointState, DYNAMIC_STATES,
        lambda msg: monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic()),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    client = ActionClient(node, FollowJointTrajectory,
                          TRAJECTORY_ACTION)
    handle = None
    result_future = None
    try:
        if not client.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('trajectory action server unavailable')
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if monitor.status(time.monotonic())[0] == 0:
                break
        else:
            raise RuntimeError('healthy active MOCK feedback required before sending motion')
        initial = [monitor.snapshot[n]['position'] for n in JOINT_NAMES]
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(JOINT_NAMES)
        # Two time-stamped points: small relative displacement and return to initial state.
        for seconds, offset in ((2, 0.03), (4, 0.0)):
            point = JointTrajectoryPoint()
            point.positions = [p + offset for p in initial]
            point.velocities = [0.0] * len(initial)
            point.time_from_start.sec = seconds
            goal.trajectory.points.append(point)
        handle = wait(node, client.send_goal_async(goal), 5.0)
        if not handle.accepted:
            raise RuntimeError('trajectory rejected')
        result_future = handle.get_result_async()
        if cancel:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.02)
            if result_future.done():
                raise RuntimeError('goal ended before cancellation experiment')
            if monitor.status(time.monotonic())[0] not in (0, 1):
                raise RuntimeError('feedback lost before cancellation')
            displacement = max(abs(monitor.snapshot[n]['position'] - p)
                               for n, p in zip(JOINT_NAMES, initial))
            if displacement < 0.002:
                raise RuntimeError('no measured motion before cancellation')
            response = wait(node, handle.cancel_goal_async(), 3.0)
            if not cancel_matches(response, handle.goal_id):
                raise RuntimeError('server did not accept cancellation for this goal')
            result = wait(node, result_future, 3.0)
            if result.status != GoalStatus.STATUS_CANCELED:
                raise RuntimeError(f'expected CANCELED, got {result.status}')
            # Let the mock settle before measuring a continuous stationary window.
            settle = time.monotonic() + 0.3
            while time.monotonic() < settle:
                rclpy.spin_once(node, timeout_sec=0.02)
            evidence = observe_hold(node, monitor)
            print(json.dumps({'scenario': 'cancel', 'passed': True,
                              'pre_cancel_displacement_rad': displacement, **evidence}))
            return
        result = wait(node, result_future, 10.0)
        if result.status != GoalStatus.STATUS_SUCCEEDED or result.result.error_code != 0:
            raise RuntimeError(f'trajectory failed: {result.result.error_code} {result.result.error_string}')
        # Action result alone is not evidence of current feedback; require a fresh sample.
        prior_stamp = monitor.last_received
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if monitor.last_received != prior_stamp:
                break
        if monitor.last_received == prior_stamp or monitor.status(time.monotonic())[0] != 0:
            raise RuntimeError('no fresh healthy feedback after trajectory')
        errors = [abs(monitor.snapshot[n]['position'] - p) for n, p in zip(JOINT_NAMES, initial)]
        if max(errors) > 0.005:
            raise RuntimeError(f'final feedback outside 0.005 rad tolerance: {errors}')
        node.get_logger().info(f'MOCK Action and final feedback verified; errors(rad)={errors}')
        print(json.dumps({'scenario': 'trajectory', 'passed': True,
                          'initial': initial, 'final_errors_rad': errors}))
    finally:
        try:
            if handle is not None and handle.accepted and (result_future is None or not result_future.done()):
                response = wait(node, handle.cancel_goal_async(), 3.0)
                if not cancel_matches(response, handle.goal_id):
                    node.get_logger().error('Cleanup cancellation not confirmed')
        except Exception as exc:
            # Do not mask the original experiment failure; always release ROS resources.
            node.get_logger().error(f'Cleanup cancellation failed: {exc}')
        finally:
            client.destroy()
            node.destroy_subscription(subscription)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cancel', action='store_true')
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    rclpy.init()
    node = Node('linglong_trajectory_demo')
    try:
        run(node, cancel=options.cancel)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
