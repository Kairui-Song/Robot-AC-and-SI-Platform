import json
import time

import rclpy
from control_msgs.msg import DynamicJointState
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String

from linglong_control_tools.health import HealthMonitor


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
        qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.create_subscription(
            DynamicJointState, '/dynamic_joint_states', self.receive, qos,
            callback_group=self.group)
        self.publisher = self.create_publisher(DiagnosticArray, '/diagnostics', 10)
        self.system_state = None
        self.system_received = None
        self.create_subscription(String, '/system/state', self.receive_system,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        # A paused /clock must not stop the stale-data monitor.
        self.timer = self.create_timer(0.2, self.publish,
            callback_group=self.group, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def receive(self, msg):
        self.monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def receive_system(self, msg):
        try:
            state = json.loads(msg.data)
            if not isinstance(state, dict) or not isinstance(state.get('state'), str):
                return
        except (ValueError, TypeError):
            return
        self.system_state, self.system_received = state, time.monotonic()

    def publish(self):
        now = time.monotonic()
        level, message = self.monitor.status(now)
        fields = self.monitor.diagnostic_fields(now)
        system = self.system_state
        if system is not None:
            age = now - self.system_received
            prefix = 'system.' if age <= self.monitor.stale_timeout else 'last_observed_system.'
            fields.update({prefix + 'state': system['state'], prefix + 'reason': str(system.get('reason')),
                           'system_sample_age_seconds': str(age)})
            if age <= self.monitor.stale_timeout and system['state'] == 'FAULT':
                # Supervisor keeps the first cause after broadcaster shutdown/cleanup.
                level = 2
                message = f"system FAULT: {system.get('reason')}; feedback: {message}"
        # Jazzy represents the IDL byte/octet field as bytes, not Python int.
        wire_level = (DiagnosticStatus.OK, DiagnosticStatus.WARN,
                      DiagnosticStatus.ERROR, DiagnosticStatus.STALE)[level]
        status = DiagnosticStatus(level=wire_level, name='linglong/control',
                                  message=message, hardware_id=(
                                      'MOCK_ONLY' if self.backend == 'mock' else 'EYOU_LEFT_ARM_1_2_3_5'))
        status.values = [KeyValue(key=k, value=str(v)) for k, v in fields.items()]
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
