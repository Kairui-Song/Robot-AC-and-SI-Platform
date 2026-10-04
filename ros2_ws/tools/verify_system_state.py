#!/usr/bin/env python3
"""Live ROS Jazzy MOCK integration; run with an isolated ROS_DOMAIN_ID.

Starts and terminates only its own process groups. Never selects real hardware.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger
from linglong_control_tools.system_client import transition


def stop(process):
    if process.poll() is not None:
        return
    # Signal launch once; it forwards SIGINT to its children. Signalling the
    # whole group here would double-interrupt rclpy during resource cleanup.
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def wait_for(node, predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=.05)
        if predicate():
            return
    raise TimeoutError('system-state integration condition timed out')


def rejected(node, command):
    client = node.create_client(Trigger, '/system/' + command)
    try:
        assert client.wait_for_service(timeout_sec=5)
        future = client.call_async(Trigger.Request())
        wait_for(node, future.done, 5)
        assert not future.result().success, future.result().message
    finally:
        node.destroy_client(client)


def scenario(directory, fault=False):
    with (directory / ('fault-launch.log' if fault else 'normal-launch.log')).open('w') as log:
        launch = subprocess.Popen(['ros2', 'launch', 'linglong_control', 'control.launch.py',
                                   'backend:=mock', 'rviz:=false',
                                   f'fault_after_cycles:={600 if fault else 0}'],
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        node = Node('system_state_integration')
        history = []
        node.create_subscription(String, '/system/state', lambda msg: history.append(json.loads(msg.data)),
                                 QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE,
                                            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        motion = None
        try:
            initial = transition(node, 'ready')
            assert not initial['motion_authorized'] and initial['hardware_state'] == 'INACTIVE'
            rejected(node, 'recover')
            transition(node, 'enable')
            if fault:
                wait_for(node, lambda: history and history[-1]['state'] == 'FAULT')
                wait_for(node, lambda: history and history[-1]['state'] == 'FAULT' and not history[-1]['operation'])
                rejected(node, 'enable')
                recovered = transition(node, 'recover')
                assert not recovered['motion_authorized'] and recovered['controller_state'] == 'inactive'
                assert any(s['state'] == 'RECOVERING' for s in history)
            else:
                with (directory / 'trajectory.log').open('w') as trajectory_log:
                    motion = subprocess.Popen(['ros2', 'run', 'linglong_control', 'trajectory_demo'],
                                              stdout=trajectory_log, stderr=subprocess.STDOUT,
                                              start_new_session=True)
                    wait_for(node, lambda: any(s['state'] == 'RUNNING' for s in history), 10)
                    wait_for(node, lambda: motion.poll() is not None, 20)
                    assert motion.returncode == 0
                    wait_for(node, lambda: history[-1]['state'] == 'ENABLED', 5)
                for name, args in [('cancel', ['trajectory_demo', '--cancel']),
                                   ('restart', ['architecture_probe', 'restart'])]:
                    with (directory / f'{name}.log').open('w') as probe_log:
                        motion = subprocess.Popen(['ros2', 'run', 'linglong_control', *args],
                                                  stdout=probe_log, stderr=subprocess.STDOUT,
                                                  start_new_session=True)
                        wait_for(node, lambda: motion.poll() is not None, 40)
                        assert motion.returncode == 0, f'{name} probe failed'
                transition(node, 'disable')
                transition(node, 'enable')
                with (directory / 'interrupted-trajectory.log').open('w') as trajectory_log:
                    motion = subprocess.Popen(['ros2', 'run', 'linglong_control', 'trajectory_demo'],
                                              stdout=trajectory_log, stderr=subprocess.STDOUT,
                                              start_new_session=True)
                    wait_for(node, lambda: history[-1]['state'] == 'RUNNING', 10)
                    stopped = transition(node, 'disable')
                    assert not stopped['motion_authorized'] and stopped['controller_state'] == 'inactive'
                    wait_for(node, lambda: motion.poll() is not None, 20)
                    assert motion.returncode != 0  # interrupted goal must not report success
            transition(node, 'shutdown')
            rejected(node, 'enable')
            return dict(scenario='fault_recovery' if fault else 'normal', passed=True,
                        states=list(dict.fromkeys(s['state'] for s in history)))
        finally:
            if motion is not None:
                stop(motion)
            node.destroy_node()
            stop(launch)
            (directory / ('fault-states.json' if fault else 'normal-states.json')).write_text(
                json.dumps(history, indent=2) + '\n')


def main():
    directory = Path('verification') / time.strftime('state-machine-%Y%m%d-%H%M%S')
    directory.mkdir(parents=True, exist_ok=False)
    rclpy.init()
    results = []
    try:
        for fault in (False, True):
            results.append(scenario(directory, fault))
        print(json.dumps(results))
    finally:
        rclpy.shutdown()
        (directory / 'result.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
