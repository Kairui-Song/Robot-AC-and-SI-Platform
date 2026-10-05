"""Non-real-time lifecycle supervisor. No motor I/O runs in this node.

Trigger replies acknowledge a request, not its completion. /system/state carries
the operation result, transition reason and telemetry age. Only this node should
own controller/hardware lifecycle services during normal operation.
"""
import json
import math
import time

import rclpy
from action_msgs.msg import GoalStatusArray
from control_msgs.msg import DynamicJointState
from controller_manager_msgs.srv import (
    ListControllers, ListHardwareComponents, SetHardwareComponentState, SwitchController)
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger

from linglong_control_tools.health import HealthMonitor
from linglong_control_tools.system_state import HardwareState, SystemState, SystemStateMachine


class SystemManager(Node):
    def __init__(self):
        super().__init__('system_manager')
        defaults = dict(backend='mock', hardware_name='LinglongSimSystem',
                        controller_name='arm_trajectory_controller', stale_timeout=1.0,
                        operation_timeout=40.0, late_reply_timeout=10.0,
                        startup_timeout=45.0, nominal_period=0.01)
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        values = {name: self.get_parameter(name).value for name in defaults}
        for name in ('stale_timeout', 'operation_timeout', 'late_reply_timeout',
                     'startup_timeout', 'nominal_period'):
            if not math.isfinite(values[name]) or values[name] <= 0:
                raise ValueError(f'{name} must be finite and positive')
        self.policy = SystemStateMachine(values['backend'])
        self.hardware_name, self.controller_name = values['hardware_name'], values['controller_name']
        self.stale_timeout = values['stale_timeout']
        self.operation_timeout = values['operation_timeout']
        self.late_reply_timeout = values['late_reply_timeout']
        self.restart_required = False
        self.intervention_reason = None
        self.startup_deadline = time.monotonic() + values['startup_timeout']
        self.monitor = HealthMonitor(self.stale_timeout, values['backend'], values['nominal_period'])
        self.hardware = self.controller = self.broadcaster = None
        self.hardware_time = self.controller_time = None
        self.hardware_future = self.controller_future = None
        self.active_goals = False
        self.goal_epoch = 0
        self.plan = []
        self.pending = None
        self.step = None
        self.step_deadline = None
        self.errors = []
        self.verifying = False
        self.verify_after = 0.0
        self.fault_stop_attempted = False
        self.last_result = None
        self.last_sequence = -1
        self.cm_clients = {
            'hardware': self.create_client(SetHardwareComponentState,
                                           '/controller_manager/set_hardware_component_state'),
            'controller': self.create_client(SwitchController, '/controller_manager/switch_controller'),
            'list_hardware': self.create_client(ListHardwareComponents,
                                                '/controller_manager/list_hardware_components'),
            'list_controllers': self.create_client(ListControllers, '/controller_manager/list_controllers'),
        }
        self.publisher = self.create_publisher(String, '/system/state', QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(DynamicJointState, '/dynamic_joint_states', self.receive_health,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_subscription(GoalStatusArray,
                                 f'/{self.controller_name}/follow_joint_trajectory/_action/status',
                                 self.receive_goals, QoSProfile(depth=1,
                                 reliability=ReliabilityPolicy.RELIABLE,
                                 durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.system_services = [self.create_service(Trigger, f'/system/{command}',
                        lambda request, response, command=command: self.request(command, response))
                         for command in ('enable', 'disable', 'recover', 'shutdown')]
        self.create_timer(0.1, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def receive_health(self, msg):
        self.monitor.receive(msg.joint_names,
                             [(v.interface_names, v.values) for v in msg.interface_values], time.monotonic())

    def receive_goals(self, msg):
        # Ignore transient-local goals from an earlier enable/session.
        self.active_goals = any(
            s.status in (1, 2, 3) and
            s.goal_info.stamp.sec * 1_000_000_000 + s.goal_info.stamp.nanosec >= self.goal_epoch
            for s in msg.status_list)

    def request(self, command, response):
        if self.restart_required:
            response.success, response.message = False, self.intervention_reason
            return response
        # Refresh guards at request time, rather than using the last timer state.
        self.observe(time.monotonic())
        try:
            plan = self.policy.request(command)
        except ValueError as error:
            response.success, response.message = False, str(error)
            return response
        self.begin(plan)
        if command == 'enable':
            self.goal_epoch = self.get_clock().now().nanoseconds
            self.active_goals = False
        response.success = True
        response.message = json.dumps(dict(accepted=command,
            transition_sequence=self.policy.sequence, completion_topic='/system/state'))
        return response

    def begin(self, plan):
        self.plan, self.errors = list(plan), []
        self.pending = self.step = None
        self.verifying = False
        self.step_deadline = time.monotonic() + self.operation_timeout

    def poll(self, now):
        # At most one request per endpoint is in flight. Timestamp the request,
        # not the response, so a delayed/cached reply cannot refresh old evidence.
        for kind, service in (('hardware', ListHardwareComponents), ('controller', ListControllers)):
            key = 'list_hardware' if kind == 'hardware' else 'list_controllers'
            client = self.cm_clients[key]
            attr = f'{kind}_future'
            entry = getattr(self, attr)
            # Retire even a completed reply if its request is already stale.
            # Removing the local future does not cancel work on the server.
            # These two services are read-only, so retrying is safe.
            if entry is not None and now - entry[1] >= self.stale_timeout:
                client.remove_pending_request(entry[0])
                entry[0].cancel()
                setattr(self, attr, None)
                setattr(self, f'{kind}_time', None)
                entry = None
            if entry is not None and entry[0].done():
                future, requested = entry
                setattr(self, attr, None)
                try:
                    result = future.result()
                    if kind == 'hardware':
                        matches = [h for h in result.component if h.name == self.hardware_name]
                        self.hardware = matches[0].state.label if len(matches) == 1 else None
                        self.hardware_time = requested
                    else:
                        states = {c.name: c.state for c in result.controller}
                        self.controller = states.get(self.controller_name)
                        self.broadcaster = states.get('joint_state_broadcaster')
                        self.controller_time = requested
                except Exception as error:
                    self.get_logger().warning(f'{kind} observation failed: {error}')
            if getattr(self, attr) is None and client.service_is_ready():
                setattr(self, attr, (client.call_async(service.Request()), now))

    def evidence(self, now):
        health = self.monitor.snapshot['control_health'] if self.monitor.snapshot else None
        times = (self.hardware_time, self.controller_time, self.monitor.last_received)
        if any(t is None or now - t > self.stale_timeout for t in times):
            return health, False, 'hardware/controller/feedback observation missing or stale'
        if not health or any(k not in health for k in
                             ('hardware_state', 'transition_sequence', 'commands_enabled')):
            return health, False, 'hardware does not export the state-machine interfaces'
        try:
            HardwareState(health['hardware_state'])
            if health['commands_enabled'] not in (0, 1):
                raise ValueError('invalid commands_enabled')
        except (ValueError, TypeError):
            return health, False, 'invalid hardware state-machine telemetry'
        level, reason = self.monitor.status(now)
        if self.monitor.last_progress is None or now - self.monitor.last_progress > self.stale_timeout:
            return health, False, 'hardware feedback cycle counter stopped'
        # INACTIVE and a single slow interval are diagnostic warnings, not a
        # reason to invent a new fault threshold. The core enforces its cycle
        # timeout; missing/delayed feedback and stopped counters remain blocking.
        healthy = level in (0, 1) and health['feedback_age_seconds'] == 0
        if healthy and self.policy.backend == 'ethercat_left_arm':
            # Internal lifecycle flags alone do not prove CiA402 drive state.
            try:
                bus = self.monitor.snapshot['ethercat_bus']
                if any(bus.get(k) != 1 for k in ('link_up', 'feedback_valid', 'state_valid')) or \
                        bus.get('wc_state') != 2 or bus.get('working_counter', 0) <= 0:
                    raise ValueError('physical bus feedback is incomplete')
                for slave in (1, 2, 3, 5):
                    drive = self.monitor.snapshot[f'ethercat_slave_{slave}']
                    if any(drive.get(k) != 1 for k in ('online', 'operational', 'state_valid', 'sample_valid')) or \
                            drive.get('al_state') != 8 or drive.get('mode_display') != 8:
                        raise ValueError(f'slave p{slave}: OP/CSP feedback not confirmed')
                    status = drive['status_word']
                    if not math.isfinite(status) or status != int(status) or not 0 <= status <= 65535:
                        raise ValueError(f'slave p{slave}: invalid status word')
                    if health['hardware_state'] == HardwareState.INACTIVE and int(status) & 0x004f != 0x0040:
                        raise ValueError(f'slave p{slave}: disabled drive feedback not confirmed')
                    if health['hardware_state'] == HardwareState.ACTIVE and int(status) & 0x006f != 0x0027:
                        raise ValueError(f'slave p{slave}: enabled drive feedback not confirmed')
            except (KeyError, ValueError, TypeError) as error:
                return health, False, str(error)
        return health, healthy, reason

    def observe(self, now):
        health, healthy, reason = self.evidence(now)
        self.policy.observe(self.hardware, self.controller, self.broadcaster, health,
                            healthy, reason, self.active_goals)
        if not self.policy.ever_ready and now > self.startup_deadline and not self.policy.operation and \
                self.policy.state != SystemState.SHUTDOWN:
            self.policy.fail('startup deadline expired: ' + reason)

    def step_request(self, step):
        kind, target = step
        if kind == 'hardware':
            request = SetHardwareComponentState.Request()
            request.name = self.hardware_name
            request.target_state.id = {'unconfigured': 1, 'inactive': 2, 'active': 3, 'finalized': 4}[target]
            request.target_state.label = target
            return self.cm_clients['hardware'], request
        request = SwitchController.Request()
        name = self.controller_name if kind == 'controller' else 'joint_state_broadcaster'
        request.activate_controllers = [name] if target == 'active' else []
        request.deactivate_controllers = [name] if target == 'inactive' else []
        request.strictness = (SwitchController.Request.STRICT if target == 'active' and kind == 'controller'
                              else SwitchController.Request.BEST_EFFORT)
        request.activate_asap = False
        request.timeout.sec = 5
        return self.cm_clients['controller'], request

    def advance(self, now):
        if self.restart_required:
            return
        if self.verifying:
            health, healthy, reason = self.evidence(now)
            fresh = all(t is not None and t > self.verify_after for t in
                        (self.hardware_time, self.controller_time, self.monitor.last_received))
            enabling = self.policy.operation == 'enable'
            expected = HardwareState.ACTIVE if enabling else HardwareState.INACTIVE
            if fresh and health and health['fault_code']:
                self.finish(False, f"hardware fault {int(health['fault_code'])} during transition")
            elif fresh and healthy and health['hardware_state'] == expected and \
                    self.hardware == ('active' if enabling else 'inactive') and \
                    self.controller == ('active' if enabling else 'inactive') and \
                    self.broadcaster == 'active' and bool(health['commands_enabled']) == enabling:
                self.finish(True)
            elif now > self.step_deadline:
                self.finish(False, 'post-transition verification failed: ' + reason)
            return
        if self.pending is not None:
            if now > self.step_deadline:
                self.policy.fail(f'{self.step} timed out; awaiting bounded late reply before stop')
                if not self.errors:
                    self.errors.append(f'{self.step} timed out')
                if now >= self.step_deadline + self.late_reply_timeout:
                    self.require_restart()
                    return
            if self.pending.done():
                try:
                    response = self.pending.result()
                    ok = response.ok
                    if self.step[0] == 'hardware':
                        ok = ok and response.state.label == self.step[1]
                    if not ok:
                        self.errors.append(f'{self.step} rejected')
                except Exception as error:
                    self.errors.append(f'{self.step}: {error}')
                self.pending = None
                # Stop paths attempt hardware shutdown even if controller stop failed.
                if self.errors and self.policy.operation in ('enable', 'recover'):
                    self.plan = []
                self.step = None
                self.step_deadline = now + self.operation_timeout
            else:
                return
        if self.step is None and self.plan:
            self.step = self.plan.pop(0)
        if self.step is not None:
            client, request = self.step_request(self.step)
            if client.service_is_ready():
                self.pending = client.call_async(request)
            elif now > self.step_deadline:
                self.errors.append(f'{self.step} service unavailable')
                self.step = None
                self.step_deadline = now + self.operation_timeout
                if self.policy.operation in ('enable', 'recover'):
                    self.plan = []
            return
        if self.errors:
            self.finish(False, '; '.join(self.errors))
        elif self.policy.operation in ('shutdown', 'fault_stop'):
            self.finish(True)
        else:
            self.verifying = True
            self.verify_after = now
            self.step_deadline = now + self.operation_timeout

    def require_restart(self):
        # The remote operation may still execute. Do not issue competing state
        # changes, and never turn local cancellation into proof of drive stop.
        self.restart_required = True
        self.intervention_reason = (
            f'{self.step} has no confirmed completion; restart required. '
            'Secure the arm using the commissioned independent stop procedure, '
            'terminate the entire controller_manager/launch, correct the cause, '
            'then restart the stack; restarting only system_manager is insufficient.')
        command = self.policy.operation
        client, _ = self.step_request(self.step)
        client.remove_pending_request(self.pending)
        self.pending.cancel()
        self.pending = self.step = None
        self.plan = []
        self.verifying = False
        self.policy.operation = None
        self.policy.fail(self.intervention_reason)
        self.policy.reason = self.intervention_reason
        self.last_result = dict(operation=command, success=False,
                                reason=self.intervention_reason, completion_unknown=True)
        self.get_logger().error(self.intervention_reason)

    def finish(self, success, reason=''):
        command = self.policy.operation
        self.verifying = False
        self.last_result = dict(operation=command, success=success, reason=reason or 'confirmed')
        if command == 'fault_stop':
            self.policy.operation = None
            self.policy.fail(self.policy.fault_reason or reason)
        else:
            self.policy.complete(success, reason)
        if command == 'recover' and success:
            self.fault_stop_attempted = False
        self.observe(time.monotonic())

    def tick(self):
        now = time.monotonic()
        self.poll(now)
        if self.policy.operation:
            self.advance(now)
        elif not self.restart_required:
            self.observe(now)
        if self.policy.state == SystemState.FAULT and not self.policy.operation and \
                not self.fault_stop_attempted and not self.restart_required:
            self.fault_stop_attempted = True
            self.policy.operation = 'fault_stop'
            # UNCONFIGURED only deactivates/cleans up. Requesting INACTIVE could
            # configure an errored component and accidentally initiate recovery.
            self.begin([('controller', 'inactive'), ('broadcaster', 'inactive'),
                        ('hardware', 'unconfigured')])
        if self.policy.sequence != self.last_sequence:
            self.get_logger().info(f'{self.policy.state.value}: {self.policy.reason}')
            self.last_sequence = self.policy.sequence
        view = self.monitor.telemetry(now)
        health = view['current_health'] or {}
        phase = health.get('hardware_state')
        try:
            phase = HardwareState(phase).name
        except (ValueError, TypeError):
            phase = 'UNKNOWN'
        message = dict(state=self.policy.state.value, reason=self.policy.reason,
                       transition_sequence=self.policy.sequence, backend=self.policy.backend,
                       operation=self.policy.operation, last_result=self.last_result,
                       restart_required=self.restart_required,
                       intervention_reason=self.intervention_reason,
                       hardware_state=phase, hardware_lifecycle=self.hardware,
                       controller_state=self.controller,
                       feedback_age_seconds=None if self.monitor.last_received is None else
                       now - self.monitor.last_received,
                       motion_authorized=self.policy.motion_authorized,
                       fault_code=health.get('fault_code'),
                       feedback_fresh=view['feedback_fresh'],
                       last_observed_health=view['last_observed_health'],
                       last_observed_fault=view['last_observed_fault'])
        self.publisher.publish(String(data=json.dumps(message, allow_nan=False)))


def main():
    rclpy.init()
    node = SystemManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
