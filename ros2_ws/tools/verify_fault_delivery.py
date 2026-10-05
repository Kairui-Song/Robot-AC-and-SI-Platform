#!/usr/bin/env python3
"""Real Jazzy MOCK regression: fault transport, ordered release, cause and recovery.

Starts its own launches. The cycle-timeout case pauses ONLY its own MOCK
controller_manager process for 0.7 s; never use this probe against hardware.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from control_msgs.action import FollowJointTrajectory
from controller_manager_msgs.srv import ListControllers, ListHardwareComponents
from trajectory_msgs.msg import JointTrajectoryPoint
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger
from linglong_control_tools.system_client import transition
from verify_system_state import stop, wait_for


def controller_child(launch):
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[1]) == launch.pid and b'/ros2_control_node' in (p / 'cmdline').read_bytes():
                return int(p.name)
        except (OSError, ValueError):
            pass
    raise RuntimeError('Could not identify this launch own controller_manager child')


def scenario(out, kind):
    history, diagnostics = [], []
    node = Node('fault_delivery_verifier')
    qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(String, '/system/state',
                             lambda msg: history.append(json.loads(msg.data)), qos)
    node.create_subscription(DiagnosticArray, '/diagnostics',
                             lambda msg: diagnostics.extend(s for s in msg.status if s.name == 'linglong/control'), 100)
    path = out / (kind + '-launch.log')
    action = ActionClient(node, FollowJointTrajectory,
                          '/arm_trajectory_controller/follow_joint_trajectory')
    paused = None
    passed = False
    with path.open('w') as log:
        launch = subprocess.Popen(['ros2', 'launch', 'linglong_control', 'control.launch.py',
                                   'backend:=mock', 'rviz:=false',
                                   'web_gateway:=false',
                                   f'fault_after_cycles:={300 if kind == "injected" else 0}'],
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            transition(node, 'ready')
            transition(node, 'enable')
            assert action.wait_for_server(timeout_sec=5)
            goal = FollowJointTrajectory.Goal()
            goal.trajectory.joint_names = ['joint_1', 'joint_2', 'joint_3', 'joint_5']
            point = JointTrajectoryPoint()
            point.positions = [.18, -.07, .08, .05]
            point.velocities = [0.] * 4
            point.time_from_start.sec = 30
            goal.trajectory.points = [point]
            pending_goal = action.send_goal_async(goal)
            wait_for(node, pending_goal.done, 5)
            handle = pending_goal.result()
            assert handle.accepted
            result = handle.get_result_async()
            wait_for(node, lambda: any(s['state'] == 'RUNNING' for s in history), 10)
            if kind == 'cycle_timeout':
                paused = controller_child(launch)
                os.kill(paused, signal.SIGSTOP)
                time.sleep(.7)
                os.kill(paused, signal.SIGCONT)
                paused = None
            wait_for(node, lambda: history and history[-1]['state'] == 'FAULT'
                     and history[-1]['operation'] is None, 20)
            wait_for(node, result.done, 15)
            assert result.result().status != 4, 'Faulted trajectory must not succeed'
            (out / (kind + '-action.json')).write_text(json.dumps(dict(
                status=result.result().status, error_code=result.result().result.error_code)))
            expected = 7 if kind == 'injected' else 5
            fault = history[-1]
            assert not fault['motion_authorized']
            assert fault['controller_state'] == 'inactive'
            assert fault['last_result']['operation'] == 'fault_stop' and fault['last_result']['success']
            assert fault['last_observed_fault']['code'] == expected, fault
            assert f'hardware fault {expected}:' in fault['reason'], fault
            for service, name in ((ListControllers, 'list_controllers'),
                                  (ListHardwareComponents, 'list_hardware_components')):
                query = node.create_client(service, '/controller_manager/' + name)
                assert query.wait_for_service(timeout_sec=5)
                pending = query.call_async(service.Request())
                wait_for(node, pending.done, 5)
                reply = pending.result()
                if name == 'list_controllers':
                    actual = {c.name: c.state for c in reply.controller}
                    assert actual['arm_trajectory_controller'] == 'inactive', actual
                    assert actual['joint_state_broadcaster'] == 'inactive', actual
                else:
                    actual = {c.name: c.state.label for c in reply.component}
                    assert actual['LinglongSimSystem'] == 'unconfigured', actual
                node.destroy_client(query)
            # Wait beyond the freshness deadline: no stale ACTIVE/zero-fault fields.
            wait_for(node, lambda: history and history[-1]['feedback_fresh'] is False, 10)
            assert history[-1]['hardware_state'] == 'UNKNOWN'
            assert history[-1]['fault_code'] is None
            wait_for(node, lambda: diagnostics and 'system FAULT:' in diagnostics[-1].message
                     and dict((v.key, v.value) for v in diagnostics[-1].values).get('feedback_fresh') == 'false', 10)
            diag = diagnostics[-1]
            values = {v.key: v.value for v in diag.values}
            assert 'active' not in values and 'fault_code' not in values
            assert values['last_observed_fault.code'] == str(expected)
            # Enable cannot bypass the latched system fault.
            client = node.create_client(Trigger, '/system/enable')
            assert client.wait_for_service(timeout_sec=5)
            future = client.call_async(Trigger.Request())
            wait_for(node, future.done, 5)
            assert not future.result().success
            node.destroy_client(client)
            restored = transition(node, 'recover')
            assert restored['state'] == 'READY' and not restored['motion_authorized']
            transition(node, 'shutdown')
            passed = True
        finally:
            if paused is not None:
                os.kill(paused, signal.SIGCONT)
            stop(launch)
            action.destroy()
            node.destroy_node()
            (out / (kind + '-states.json')).write_text(json.dumps(history, indent=2))
            (out / (kind + '-diagnostics.json')).write_text(json.dumps([
                dict(message=s.message, values={v.key: v.value for v in s.values}) for s in diagnostics], indent=2))
    text = path.read_text()
    for forbidden in ('Not acceptable command interfaces combination',
                      'Error while attempting mode switch', 'process has died'):
        assert forbidden not in text, f'{kind}: {forbidden}'
    assert passed
    return dict(scenario=kind, passed=True, fault_code=expected)


def main():
    out = Path('verification') / time.strftime('fault-delivery-%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    results = []
    rclpy.init()
    try:
        for kind in ('injected', 'cycle_timeout'):
            results.append(scenario(out, kind))
        print(json.dumps(results))
    finally:
        rclpy.shutdown()
        (out / 'result.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
