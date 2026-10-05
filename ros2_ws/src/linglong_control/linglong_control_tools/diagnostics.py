import time
import json

import rclpy
from control_msgs.msg import DynamicJointState
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from std_msgs.msg import String
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

from linglong_control_tools.health import HealthMonitor
from linglong_control_tools.interfaces import DYNAMIC_STATES, DIAGNOSTICS, DIAGNOSTIC_NAME


class ControlDiagnostics(Node):
    def __init__(self):
        super().__init__('linglong_control_diagnostics')
        self.declare_parameter('stale_timeout', 0.5,
                               ParameterDescriptor(read_only=True))
        self.declare_parameter('expected_backend', 'mock', ParameterDescriptor(read_only=True))
        self.declare_parameter('nominal_period', 0.01, ParameterDescriptor(read_only=True))
        self.backend = self.get_parameter('expected_backend').value
        self.monitor = HealthMonitor(self.get_parameter('stale_timeout').value,
                                     self.backend, self.get_parameter('nominal_period').value)
        self.group = MutuallyExclusiveCallbackGroup()
        self.system_state = self.system_received = None
        self.system_subscription = self.create_subscription(
            String, '/system/state', self.receive_system,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL), callback_group=self.group)
        qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.create_subscription(
            DynamicJointState, DYNAMIC_STATES, self.receive, qos,
            callback_group=self.group)
        self.publisher = self.create_publisher(DiagnosticArray, DIAGNOSTICS, 10)
        # A paused /clock must not stop the stale-data monitor.
        self.timer = self.create_timer(0.2, self.publish,
            callback_group=self.group, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def receive(self, msg):
        self.monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def receive_system(self, msg):
        try:
            value = json.loads(msg.data)
            if isinstance(value, dict) and isinstance(value.get('state'), str):
                self.system_state, self.system_received = value, time.monotonic()
        except (ValueError, TypeError):
            pass

    def publish(self):
        now = time.monotonic()
        level, message = self.monitor.status(now)
        if self.system_received is not None and now - self.system_received <= 1.0 and \
                self.system_state.get('state') == 'FAULT':
            level, message = 2, 'system FAULT: ' + self.system_state.get('reason', 'system fault')
        status = DiagnosticStatus(level=bytes([level]), name=DIAGNOSTIC_NAME,
                                  message=message, hardware_id=(
                                      'MOCK_ONLY' if self.backend == 'mock' else 'EYOU_LEFT_ARM_1_2_3_5'))
        status.values = [KeyValue(key=k, value=v) for k, v in self.monitor.diagnostic_fields(now).items()]
        if self.monitor.snapshot and self.monitor.telemetry(now)['feedback_fresh']:
            for resource, fields in self.monitor.snapshot.items():
                if resource.startswith('ethercat_'):
                    status.values.extend(KeyValue(key=f'{resource}/{k}', value=str(v))
                                         for k, v in fields.items())
        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self.publisher.publish(msg)


def main():
    rclpy.init()
    node = ControlDiagnostics()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
