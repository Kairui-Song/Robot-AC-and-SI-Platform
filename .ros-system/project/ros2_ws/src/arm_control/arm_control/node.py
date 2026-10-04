"""Single-point JointTrajectory -> EtherCAT -> measured JointState."""
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory

from arm_control.backend import (
    NAMES, Calibration, EthercatBackend, MockBackend, validate_command,
)


class ArmControl(Node):
    def __init__(self):
        super().__init__('arm_control')
        defaults = {
            'backend': 'mock', 'ethercat_executable': 'ethercat', 'master_index': 0,
            'counts_per_radian': [100000.0] * 4, 'zero_counts': [0.0] * 4,
            'lower_limits': [-1.57] * 4, 'upper_limits': [1.57] * 4,
            'calibration_confirmed': False, 'poll_hz': 5.0,
            'command_timeout_sec': 2.0, 'command_max_age_sec': 0.5,
            'cli_timeout_sec': 0.5, 'max_step_rad': 0.05,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        p = lambda name: self.get_parameter(name).value
        self.calibration = Calibration(p('counts_per_radian'), p('zero_counts'),
                                       p('lower_limits'), p('upper_limits'))
        for name in ('poll_hz', 'command_timeout_sec', 'command_max_age_sec',
                     'cli_timeout_sec', 'max_step_rad'):
            if not math.isfinite(p(name)) or p(name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        self.timeout = p('command_timeout_sec')
        self.max_age = p('command_max_age_sec')
        self.max_step = p('max_step_rad')
        mode = p('backend')
        if mode == 'ethercat':
            if not p('calibration_confirmed'):
                raise ValueError('Hardware requires measured calibration and calibration_confirmed=true')
            if p('master_index') < 0:
                raise ValueError('master_index must be nonnegative')
            self.backend = EthercatBackend(self.calibration, p('ethercat_executable'),
                                          p('master_index'), p('cli_timeout_sec'))
        elif mode == 'mock':
            self.backend = MockBackend()
        else:
            raise ValueError('backend must be mock or ethercat')
        self.target = None
        self.active = False
        self.faulted = False
        self.last_command = 0.0
        self.publisher = self.create_publisher(JointState, '/joint_states', 10)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.create_subscription(
            JointTrajectory, '/joint_command', self.command, qos)
        self.timer = self.create_timer(1.0 / p('poll_hz'), self.tick)
        self.get_logger().info(f'Backend={mode}; single-point position commands, radians')

    def command(self, msg):
        if self.faulted:
            self.get_logger().error('Fault latched; recommission hardware and restart node')
            return
        try:
            if len(msg.points) != 1:
                raise ValueError('Only one immediate trajectory point is supported')
            point = msg.points[0]
            if (point.time_from_start.sec or point.time_from_start.nanosec or
                    point.velocities or point.accelerations or point.effort):
                raise ValueError('Only positions with time_from_start=0 are supported')
            stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            if stamp:
                age = (self.get_clock().now().nanoseconds - stamp) / 1e9
                if age < 0 or age > self.max_age:
                    raise ValueError('Command timestamp is future or stale')
            # Reject shape/limits/NaN before any I/O; step checked against fresh feedback below.
            validate_command(msg.joint_names, point.positions, [0.0] * 4,
                             self.calibration, float('inf'))
        except ValueError as exc:
            self.get_logger().warning(f'Command rejected: {exc}')
            return
        try:
            current = self.backend.read()
            try:
                target = validate_command(msg.joint_names, point.positions, current,
                                          self.calibration, self.max_step)
            except ValueError as exc:
                self.get_logger().warning(f'Command rejected: {exc}')
                return
            self.backend.check_ready()
            # Mark ownership before the first write, including partially failed writes.
            self.active = True
            self.backend.write(target)
            self.target = target
            self.last_command = time.monotonic()
        except Exception as exc:
            self.fail(exc)

    def tick(self):
        if self.faulted:
            return
        try:
            if self.active:
                if time.monotonic() - self.last_command > self.timeout:
                    raise RuntimeError('Command watchdog expired')
                self.backend.check_ready()
                self.backend.write(self.target)
            positions = self.backend.read()
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = list(NAMES)
            msg.position = positions
            self.publisher.publish(msg)
        except Exception as exc:
            self.fail(exc)

    def fail(self, exc):
        self.faulted = True
        self.get_logger().error(f'Control stopped: {exc}')
        self.stop()

    def stop(self):
        if self.active:
            self.active = False
            self.target = None
            try:
                self.backend.stop()
            except Exception as exc:
                self.get_logger().error(f'Disable failed; check physical stop: {exc}')


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = ArmControl()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
