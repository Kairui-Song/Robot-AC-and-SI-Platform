"""Read-only, time-bounded ROS evidence collection; never sends motion or reset requests."""
import argparse
import math
import sys
import time

import rclpy
from action_msgs.msg import GoalStatusArray
from control_msgs.msg import DynamicJointState, JointTrajectoryControllerState
from controller_manager_msgs.srv import ListControllers, ListHardwareComponents
from rclpy.node import Node
from rclpy.qos import (QoSProfile, ReliabilityPolicy, DurabilityPolicy,
                       qos_check_compatible, qos_profile_action_status_default)
from rclpy.utilities import remove_ros_args

from linglong_control_tools.evidence import Evidence, save_report

TOPICS = {
    'dynamic': '/dynamic_joint_states',
    'controller': '/arm_trajectory_controller/controller_state',
    'action': '/arm_trajectory_controller/follow_joint_trajectory/_action/status',
}


class FaultSnapshot(Node):
    def __init__(self):
        super().__init__('linglong_fault_snapshot')
        self.evidence = Evidence(time.monotonic())
        self.state_qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                                    durability=DurabilityPolicy.VOLATILE)
        self.subscriptions_owned = [
            self.create_subscription(DynamicJointState, TOPICS['dynamic'], self.dynamic, self.state_qos),
            self.create_subscription(JointTrajectoryControllerState, TOPICS['controller'], self.controller, self.state_qos),
            self.create_subscription(GoalStatusArray, TOPICS['action'], self.action, qos_profile_action_status_default),
        ]

    def dynamic(self, msg):
        self.evidence.dynamic(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def controller(self, msg):
        self.evidence.controller_frame(msg.joint_names, msg.reference.positions, msg.feedback.positions,
            time.monotonic(), msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec)

    def action(self, msg):
        self.evidence.action = {'received_elapsed_sec': time.monotonic() - self.evidence.started,
            'goals': [{'goal_id': bytes(s.goal_info.goal_id.uuid).hex(), 'status': int(s.status),
                       'goal_stamp_ns': s.goal_info.stamp.sec * 10**9 + s.goal_info.stamp.nanosec}
                      for s in msg.status_list[-32:]],
            'total_statuses': len(msg.status_list),
            'note': 'Transient-local retained history; receipt time is not goal execution time.'}

    def collect_services(self):
        # Read-only requests run concurrently, with one overall deadline.
        pending = {}
        for key, srv_type, name in (
            ('controllers', ListControllers, 'list_controllers'),
            ('hardware', ListHardwareComponents, 'list_hardware_components')):
            client = self.create_client(srv_type, '/controller_manager/' + name)
            pending[key] = [client, srv_type, None]
        try:
            deadline = time.monotonic() + 3.0
            while pending and time.monotonic() < deadline:
                rclpy.spin_once(self, timeout_sec=.05)
                for key, (client, srv_type, future) in list(pending.items()):
                    if future is None and client.service_is_ready():
                        pending[key][2] = client.call_async(srv_type.Request())
                    elif future is not None and future.done():
                        try:
                            response = future.result()
                            if key == 'controllers':
                                items = [{'name': c.name, 'state': c.state, 'type': c.type,
                                          'claimed_interfaces': list(c.claimed_interfaces)}
                                         for c in response.controller]
                            else:
                                items = [{'name': h.name, 'state': h.state.label,
                                          'plugin': getattr(h, 'plugin_name', getattr(h, 'class_type', '')),
                                          'command_interfaces': [
                                              {'name': i.name, 'available': i.is_available, 'claimed': i.is_claimed}
                                              for i in h.command_interfaces],
                                          'state_interfaces': [i.name for i in h.state_interfaces]}
                                         for h in response.component]
                            setattr(self.evidence, key, {'received_elapsed_sec': time.monotonic() - self.evidence.started,
                                                        'items': items})
                        except Exception as exc:
                            self.evidence.errors[key] = str(exc)
                        self.destroy_client(client)
                        del pending[key]
                self.evidence.observe_condition(time.monotonic())
            for key in pending:
                self.evidence.errors[key] = 'read-only service unavailable or exceeded 3-second collection deadline'
        finally:
            for client, _, future in pending.values():
                if future is not None and not future.done():
                    future.cancel()
                self.destroy_client(client)

    def collect_graph(self):
        for key, topic in TOPICS.items():
            wanted = qos_profile_action_status_default if key == 'action' else self.state_qos
            try:
                publishers = []
                for endpoint in self.get_publishers_info_by_topic(topic):
                    compatibility, reason = qos_check_compatible(endpoint.qos_profile, wanted)
                    publishers.append({'node': endpoint.node_namespace.rstrip('/') + '/' + endpoint.node_name,
                        'type': endpoint.topic_type,
                        'reliability': endpoint.qos_profile.reliability.name,
                        'durability': endpoint.qos_profile.durability.name,
                        'compatibility_to_probe': compatibility.name, 'compatibility_reason': reason})
                self.evidence.graph[topic] = {'publishers': publishers,
                    'observed_elapsed_sec': time.monotonic() - self.evidence.started,
                    'scope': 'Publisher compatibility to this probe only, not application-to-controller QoS.'}
            except Exception as exc:
                self.evidence.errors[topic] = str(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=3.0)
    parser.add_argument('--until-fault', action='store_true',
                        help='End early only after healthy feedback changes to ERROR/STALE; duration is the maximum')
    parser.add_argument('--output', required=True, help='New JSON file; existing files are never overwritten')
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    if not math.isfinite(options.duration) or not .5 <= options.duration <= 60:
        parser.error('--duration must be between 0.5 and 60 seconds')
    rclpy.init()
    node = FaultSnapshot()
    try:
        deadline = time.monotonic() + options.duration
        healthy_seen = False
        completed_reason = 'observation_window_expired'
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            now = time.monotonic()
            node.evidence.observe_condition(now)
            level, _ = node.evidence.monitor.status(now)
            if level == 0:
                healthy_seen = True
            elif options.until_fault and healthy_seen and level >= 2:
                completed_reason = 'unhealthy_feedback_after_healthy_baseline'
                break
        node.collect_services()
        node.collect_graph()
        report = node.evidence.report(time.monotonic())
        report['collection_completion'] = completed_reason
        save_report(options.output, report)
        print(f'Evidence saved: {options.output}; findings={len(report["findings"])}; root cause not automatically confirmed')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
