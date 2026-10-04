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
        # A paused /clock must not stop the stale-data monitor.
        self.timer = self.create_timer(0.2, self.publish,
            callback_group=self.group, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def receive(self, msg):
        self.monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def publish(self):
        level, message = self.monitor.status(time.monotonic())
        status = DiagnosticStatus(level=level, name='linglong/control',
                                  message=message, hardware_id=(
                                      'MOCK_ONLY' if self.backend == 'mock' else 'EYOU_LEFT_ARM_1_2_3_5'))
        if self.monitor.snapshot:
            health = self.monitor.snapshot['control_health']
            status.values = [KeyValue(key=k, value=str(v)) for k, v in health.items()]
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
