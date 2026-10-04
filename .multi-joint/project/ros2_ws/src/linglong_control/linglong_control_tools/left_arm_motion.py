"""Run one coordinated four-joint Action through the existing controller stack."""
import argparse
import json
from pathlib import Path
import sys
import time

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import DynamicJointState
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.utilities import remove_ros_args
from trajectory_msgs.msg import JointTrajectoryPoint

from linglong_control_tools.acceptance import cancel_matches
from linglong_control_tools.health import HealthMonitor
from linglong_control_tools.left_arm_configuration import NAMES, validate
from linglong_control_tools.left_arm_motion_plan import build_plan
from linglong_control_tools.trajectory_demo import wait


def run(node, options):
    if options.backend == 'ethercat_left_arm':
        if not options.hardware_config:
            raise ValueError('Physical motion requires the same commissioned hardware_config used by launch')
        config = validate(yaml.safe_load(Path(options.hardware_config).read_text(encoding='utf-8')))
        limits = config['joints']
        period = 1 / config['update_rate']
    else:
        if options.hardware_config:
            raise ValueError('hardware_config is only used for ethercat_left_arm')
        limits = {name: {'lower': -1.57, 'upper': 1.57, 'max_velocity': .1} for name in NAMES}
        period = .01
    monitor = HealthMonitor(expected_backend=options.backend, nominal_period=period)
    subscription = node.create_subscription(
        DynamicJointState, '/dynamic_joint_states',
        lambda msg: monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic()),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    client = ActionClient(node, FollowJointTrajectory, '/arm_trajectory_controller/follow_joint_trajectory')
    handle = None
    result_future = None
    try:
        if not client.wait_for_server(timeout_sec=10):
            raise TimeoutError('Left-arm trajectory controller unavailable')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if monitor.status(time.monotonic())[0] == 0 and monitor.snapshot['control_health']['active'] == 1:
                break
        else:
            raise RuntimeError('No fresh active feedback matching the requested backend')
        if any(abs(monitor.snapshot[name]['velocity']) > .02 for name in NAMES):
            raise RuntimeError('Arm is already moving; finish or cancel its current task first')
        initial = tuple(monitor.snapshot[name]['position'] for name in NAMES)
        plan = build_plan(initial, limits, options.duration,
                          offsets=options.offsets, amplitude=options.amplitude)
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(NAMES)
        for sample in plan:
            point = JointTrajectoryPoint()
            point.positions = list(sample.positions)
            # Only positions: controller linearly interpolates within the checked bounds.
            point.time_from_start.sec, point.time_from_start.nanosec = divmod(sample.time_ns, 10**9)
            goal.trajectory.points.append(point)
        handle = wait(node, client.send_goal_async(goal), 5)
        if not handle.accepted:
            raise RuntimeError('Four-joint trajectory rejected')
        result_future = handle.get_result_async()
        deadline = time.monotonic() + options.duration + 8
        while not result_future.done():
            rclpy.spin_once(node, timeout_sec=.05)
            level, reason = monitor.status(time.monotonic())
            if level >= 2 or monitor.snapshot['control_health']['active'] != 1:
                raise RuntimeError(f'Left-arm feedback became unhealthy: {reason}')
            if time.monotonic() > deadline:
                raise TimeoutError('Four-joint trajectory result timed out')
        result = result_future.result()
        if result.status != GoalStatus.STATUS_SUCCEEDED or result.result.error_code != 0:
            raise RuntimeError(f'Action failed: {result.result.error_code} {result.result.error_string}')
        previous = monitor.last_received
        deadline = time.monotonic() + 2
        while monitor.last_received == previous and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
        if (monitor.last_received == previous or monitor.status(time.monotonic())[0] >= 2
                or monitor.snapshot['control_health']['active'] != 1):
            raise RuntimeError('Missing fresh final feedback')
        errors = [abs(monitor.snapshot[name]['position'] - target)
                  for name, target in zip(NAMES, plan[-1].positions)]
        if max(errors) > .005:
            raise RuntimeError(f'Final joint error exceeds 0.005 rad: {errors}')
        print(json.dumps({'backend': options.backend, 'joints': NAMES, 'passed': True,
                          'scenario': 'offsets' if options.offsets is not None else 'wave',
                          'final_errors_rad': errors}))
    finally:
        try:
            if handle is not None and handle.accepted and (result_future is None or not result_future.done()):
                response = wait(node, handle.cancel_goal_async(), 3)
                if not cancel_matches(response, handle.goal_id):
                    node.get_logger().error('Cancellation not confirmed; inspect controller state')
        except Exception as exc:
            node.get_logger().error(f'Cancellation failed: {exc}')
        finally:
            client.destroy()
            node.destroy_subscription(subscription)


def main():
    parser = argparse.ArgumentParser(description='Coordinated left arm through FollowJointTrajectory')
    parser.add_argument('--backend', choices=('mock', 'ethercat_left_arm'), default='mock')
    parser.add_argument('--hardware-config')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--wave', action='store_true', help='One bounded wave returning to measured start pose')
    mode.add_argument('--offsets', type=float, nargs=4, metavar=('J1', 'J2', 'J3', 'J5'),
                      help='Relative joint offsets in radians, ordered joint_1/2/3/5')
    parser.add_argument('--duration', type=float, default=6.0)
    parser.add_argument('--amplitude', type=float, default=.03, help='Wave amplitude in radians')
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    rclpy.init()
    node = Node('left_arm_motion')
    try:
        run(node, options)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
