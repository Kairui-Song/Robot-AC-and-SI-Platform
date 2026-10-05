"""Web → supervisor services / trajectory Action; no direct EtherCAT writes."""
import math
import os
import queue
import threading
import time
import json
import uuid
import xml.etree.ElementTree as ET

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.clock import Clock, ClockType
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger
from control_msgs.msg import DynamicJointState
from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint

from linglong_control_tools.gateway_http import GatewayTransport, make_server
from linglong_control_tools.health import HealthMonitor
from linglong_control_tools.interfaces import JOINT_NAMES, TRAJECTORY_ACTION
from linglong_control_tools.left_arm_motion_plan import build_plan


class WebGateway(Node):
    def __init__(self):
        super().__init__('linglong_web_gateway')
        self.declare_parameter('backend', 'mock')
        self.declare_parameter('robot_description', '')
        self.backend = self.get_parameter('backend').value
        root = ET.fromstring(self.get_parameter('robot_description').value)
        hardware = root.find('ros2_control')
        self.limits = {}
        for joint in hardware.findall('joint'):
            params = {p.get('name'): float(p.text) for p in joint.findall('param')}
            self.limits[joint.get('name')] = {k: params[k] for k in ('lower', 'upper', 'max_velocity')}
        period = float(hardware.find("hardware/param[@name='nominal_period']").text)
        self.monitor = HealthMonitor(stale_timeout=1., expected_backend=self.backend, nominal_period=period)
        self.system = None
        self.system_received = None
        self.goal = None
        self.goal_handle = None
        self.lifecycle_pending = False
        self.transport = GatewayTransport(os.environ.get('LINGLONG_ROS_TOKEN', ''))
        self.clients = {c: self.create_client(Trigger, '/system/' + c)
                        for c in ('enable', 'disable', 'recover', 'shutdown')}
        self.action = ActionClient(self, FollowJointTrajectory, TRAJECTORY_ACTION)
        self.create_subscription(String, '/system/state', self.receive_system,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(DynamicJointState, '/dynamic_joint_states', self.receive_feedback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_timer(.05, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.server = make_server((os.environ.get('LINGLONG_ROS_BIND', '127.0.0.1'),
                                   int(os.environ.get('LINGLONG_ROS_PORT', '8091'))), self.transport)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def receive_system(self, msg):
        try:
            value = json.loads(msg.data)
            if isinstance(value, dict) and value.get('backend') == self.backend:
                self.system, self.system_received = value, time.monotonic()
        except (TypeError, ValueError):
            pass

    def receive_feedback(self, msg):
        self.monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def view(self):
        now = time.monotonic()
        connected = self.system_received is not None and now - self.system_received <= 1.
        healthy = self.monitor.telemetry(now)['feedback_fresh'] and self.monitor.status(now)[0] <= 1
        system = dict(self.system or {})
        # A stopped supervisor cannot leave the last ENABLED label on screen.
        if not connected:
            system = dict(state='UNKNOWN', reason='system supervisor missing or stale', motion_authorized=False)
        joints = None
        if healthy:
            joints = {name: dict(self.monitor.snapshot[name]) for name in JOINT_NAMES}
        return dict(ok=connected, connected=connected, backend=self.backend, system=system,
                    feedback_fresh=healthy, joints=joints, limits=self.limits,
                    goal=dict(self.goal) if self.goal else None)

    def tick(self):
        for _ in range(16):
            try:
                task = self.transport.tasks.get_nowait()
            except queue.Empty:
                break
            if time.monotonic() >= task.deadline:
                task.finish(504, ok=False, error='expired queued request was not executed')
                continue
            try:
                self.execute(task)
            except (ValueError, RuntimeError, TypeError, KeyError) as error:
                task.finish(409, ok=False, error=str(error))
        self.transport.publish(self.view())

    def execute(self, task):
        view = self.view()
        if not view['connected']:
            raise RuntimeError('system supervisor unavailable; control rejected')
        if task.command in self.clients:
            if task.payload:
                raise ValueError('lifecycle commands take an empty JSON object')
            if self.lifecycle_pending:
                raise RuntimeError('lifecycle request awaiting response')
            client = self.clients[task.command]
            if not client.service_is_ready():
                raise RuntimeError('system service unavailable')
            self.lifecycle_pending = True
            future = client.call_async(Trigger.Request())
            future.add_done_callback(lambda f: self.lifecycle_reply(task, f))
        elif task.command == 'trajectory':
            self.send_trajectory(task, view)
        elif task.command == 'cancel':
            if task.payload:
                raise ValueError('cancel takes an empty JSON object')
            if self.goal_handle is None or not self.goal or self.goal['status'] not in ('ACCEPTED', 'RUNNING'):
                raise RuntimeError('no accepted Web trajectory to cancel')
            self.goal_handle.cancel_goal_async().add_done_callback(lambda f: self.cancel_reply(task, f))

    def lifecycle_reply(self, task, future):
        self.lifecycle_pending = False
        try:
            result = future.result()
            detail = json.loads(result.message) if result.success else result.message
            task.finish(202 if result.success else 409, ok=result.success,
                        accepted=result.success, operation=task.command, detail=detail)
        except Exception as error:
            task.finish(503, ok=False, completion_unknown=True, error=str(error))

    def send_trajectory(self, task, view):
        system = view['system']
        if system.get('state') != 'ENABLED' or not system.get('motion_authorized') or \
                system.get('operation') or not system.get('feedback_fresh') or not view['feedback_fresh']:
            raise RuntimeError('trajectory requires ENABLED, supervisor authorization and fresh feedback')
        if self.goal and self.goal['status'] in ('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCELLING', 'UNKNOWN'):
            raise RuntimeError('a Web trajectory is already in progress')
        if set(task.payload) != {'offsets', 'duration'}:
            raise ValueError('provide offsets [joint_1, joint_2, joint_3, joint_5] and duration')
        offsets, duration = task.payload['offsets'], task.payload['duration']
        if not isinstance(offsets, list) or len(offsets) != 4 or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > .05 for v in offsets):
            raise ValueError('each offset must be finite and within ±0.05 rad')
        if type(duration) not in (int, float):
            raise ValueError('duration must be a number')
        if any(abs(view['joints'][name]['velocity']) > .02 for name in JOINT_NAMES):
            raise RuntimeError('joints are still moving')
        initial = tuple(view['joints'][name]['position'] for name in JOINT_NAMES)
        plan = build_plan(initial, self.limits, duration, offsets=offsets)
        if not self.action.server_is_ready():
            raise RuntimeError('trajectory Action unavailable')
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(JOINT_NAMES)
        for sample in plan:
            point = JointTrajectoryPoint()
            point.positions = list(sample.positions)
            point.time_from_start.sec, point.time_from_start.nanosec = divmod(sample.time_ns, 10**9)
            goal.trajectory.points.append(point)
        self.goal = dict(id=uuid.uuid4().hex, status='SUBMITTING', result=None)
        self.action.send_goal_async(goal, feedback_callback=self.feedback).add_done_callback(
            lambda f: self.goal_reply(task, f))

    def feedback(self, _message):
        if self.goal and self.goal['status'] == 'ACCEPTED':
            self.goal['status'] = 'RUNNING'

    def goal_reply(self, task, future):
        try:
            handle = future.result()
            if not handle.accepted:
                self.goal['status'] = 'REJECTED'
                task.finish(409, ok=False, error='controller rejected trajectory', goal=self.goal)
                return
            self.goal_handle = handle
            self.goal['status'] = 'ACCEPTED'
            handle.get_result_async().add_done_callback(self.goal_result)
            task.finish(202, ok=True, accepted=True, goal=dict(self.goal))
        except Exception as error:
            self.goal['status'] = 'UNKNOWN'
            task.finish(503, ok=False, completion_unknown=True, error=str(error))

    def goal_result(self, future):
        try:
            value = future.result()
            success = value.status == 4 and value.result.error_code == 0
            self.goal.update(status='SUCCEEDED' if success else 'CANCELLED' if value.status == 5 else 'FAILED',
                result=dict(status=value.status, error_code=value.result.error_code,
                            message=value.result.error_string, success=success))
        except Exception as error:
            self.goal.update(status='UNKNOWN', result=dict(error=str(error)))
        self.goal_handle = None

    def cancel_reply(self, task, future):
        try:
            result = future.result()
            accepted = bool(result.goals_canceling)
            if accepted and self.goal_handle is not None:
                self.goal['status'] = 'CANCELLING'
            task.finish(202 if accepted else 409, ok=accepted, accepted=accepted,
                        detail='cancellation requested; await trajectory result')
        except Exception as error:
            task.finish(503, ok=False, completion_unknown=True, error=str(error))


def main():
    rclpy.init()
    node = None
    try:
        node = WebGateway()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.server.shutdown()
            node.server.server_close()
            node.thread.join(timeout=2.)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
