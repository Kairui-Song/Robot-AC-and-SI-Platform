"""Live MOCK architecture experiments: controller ownership and fault propagation."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

import rclpy
from control_msgs.msg import DynamicJointState
from controller_manager_msgs.srv import ListControllers, SwitchController
from diagnostic_msgs.msg import DiagnosticArray
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.utilities import remove_ros_args

from linglong_control_tools.health import HealthMonitor, JOINT_NAMES
from linglong_control_tools.acceptance import HoldWindow
from linglong_control_tools.trajectory_demo import observe_hold, wait
from linglong_control_tools.interfaces import MANAGER, TRAJECTORY_CONTROLLER, DYNAMIC_STATES, DIAGNOSTICS
from linglong_control_tools.system_client import transition

CONTROLLER = TRAJECTORY_CONTROLLER


def service(node, srv_type, name, request):
    client = node.create_client(srv_type, MANAGER + '/' + name)
    try:
        if not client.wait_for_service(timeout_sec=5.0):
            raise TimeoutError(f'{name} unavailable')
        return wait(node, client.call_async(request), 8.0)
    finally:
        node.destroy_client(client)


def state(node):
    response = service(node, ListControllers, 'list_controllers', ListControllers.Request())
    matches = [c for c in response.controller if c.name == CONTROLLER]
    if len(matches) != 1:
        raise RuntimeError('expected exactly one trajectory controller')
    return matches[0].state


def switch(node, activate):
    transition(node, 'enable' if activate else 'disable')
    expected = 'active' if activate else 'inactive'
    if state(node) != expected:
        raise RuntimeError(f'controller did not reach {expected}')


def run(node, scenario, fault_log=None, expected_code=6):
    monitor = HealthMonitor()
    diagnostics = []
    hold_guard = [None]
    hold_errors = []

    def receive_state(msg):
        now = time.monotonic()
        monitor.receive(msg.joint_names,
            [(v.interface_names, v.values) for v in msg.interface_values], now)
        # Retain evidence during service waits as well as between switches. Checking
        # only the last sample after a service reply could miss an intervening jump.
        if hold_guard[0] is not None and not hold_errors:
            try:
                if monitor.invalid_reason or monitor.last_received != now:
                    raise ValueError('invalid feedback during controller switch')
                hold_guard[0].add(
                    [monitor.snapshot[n]['position'] for n in JOINT_NAMES],
                    [monitor.snapshot[n]['velocity'] for n in JOINT_NAMES],
                    monitor.snapshot['control_health']['cycles'], now)
            except ValueError as exc:
                hold_errors.append(str(exc))

    sub = node.create_subscription(DynamicJointState, DYNAMIC_STATES,
        receive_state,
        QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))

    def receive_diagnostics(msg):
        for status in msg.status:
            if status.name == 'linglong/control' and status.hardware_id == 'MOCK_ONLY':
                diagnostics[:] = [(time.monotonic(), status.level, status.message)]

    diagnostic_sub = node.create_subscription(DiagnosticArray, DIAGNOSTICS, receive_diagnostics, 10)
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if (monitor.status(time.monotonic())[0] == 0 and diagnostics and
                    diagnostics[0][1] == 0 and time.monotonic() - diagnostics[0][0] < .5):
                break
        else:
            raise RuntimeError('no healthy MOCK baseline; missing startup is not a passing fault test')
        if state(node) != 'active':
            raise RuntimeError('trajectory controller must initially be active')
        if scenario == 'restart':
            before = observe_hold(node, monitor)
            reference = before['reference']
            hold_guard[0] = HoldWindow(reference)
            switch(node, False)
            inactive = observe_hold(node, monitor, reference=reference, active=False)
            switch(node, True)
            reactivated = observe_hold(node, monitor, reference=reference)
            if hold_errors:
                raise RuntimeError(hold_errors[0])
            return {'scenario': scenario, 'passed': True, 'before': before,
                    'inactive': inactive, 'reactivated': reactivated,
                    'including_service_waits': hold_guard[0].result(1.2)}
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if diagnostics and diagnostics[0][1] >= 2 and time.monotonic() - diagnostics[0][0] < .5:
                # STALE alone could mean the publisher never existed. Require a healthy
                # baseline, the exact plugin fault code, and loss of controller activation.
                log = Path(fault_log).read_text(encoding='utf-8', errors='replace')
                if re.search(rf'MOCK fault latched, code={expected_code}\b', log):
                    controller_state = state(node)
                    if controller_state != 'active':
                        request = SwitchController.Request()
                        request.strictness = SwitchController.Request.STRICT
                        request.activate_controllers = [CONTROLLER]
                        request.timeout.sec = 3
                        retry = service(node, SwitchController, 'switch_controller', request)
                        if retry.ok or state(node) == 'active':
                            raise RuntimeError('faulted hardware allowed controller reactivation')
                        return {'scenario': scenario, 'passed': True, 'fault_code': expected_code,
                                'reactivation_rejected': True,
                                'controller_state': controller_state,
                                'diagnostic_level': diagnostics[0][1], 'diagnostic': diagnostics[0][2]}
        raise TimeoutError('expected fault, unhealthy diagnostics and stopped controller not all observed')
    finally:
        node.destroy_subscription(sub)
        node.destroy_subscription(diagnostic_sub)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario', choices=['restart', 'fault'])
    parser.add_argument('--fault-log')
    parser.add_argument('--expected-code', type=int, choices=[6, 7], default=6)
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    if options.scenario == 'fault' and not options.fault_log:
        parser.error('fault requires --fault-log from this launch run')
    rclpy.init()
    node = Node('linglong_architecture_probe')
    try:
        print(json.dumps(run(node, options.scenario, options.fault_log, options.expected_code)))
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
