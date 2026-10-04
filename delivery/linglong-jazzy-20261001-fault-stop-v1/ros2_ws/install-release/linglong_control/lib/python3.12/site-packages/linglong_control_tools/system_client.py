"""Bounded supervisor client; accepted requests must reach the expected state."""
import argparse
import json
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.utilities import remove_ros_args
from std_msgs.msg import String
from std_srvs.srv import Trigger


def transition(node, command, timeout=50.0):
    observed = []
    subscription = node.create_subscription(String, '/system/state',
        lambda msg: observed.append(json.loads(msg.data)), QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    client = None
    deadline = time.monotonic() + timeout
    try:
        expected = {'ready': 'READY', 'enable': 'ENABLED', 'disable': 'READY',
                    'recover': 'READY', 'shutdown': 'SHUTDOWN'}[command]
        minimum_sequence = 0
        if command != 'ready':
            client = node.create_client(Trigger, '/system/' + command)
            if not client.wait_for_service(timeout_sec=min(timeout, 5.0)):
                raise TimeoutError('system service unavailable')
            future = client.call_async(Trigger.Request())
            while not future.done() and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.05)
            if not future.done():
                raise TimeoutError('system request timed out')
            if not future.result().success:
                raise RuntimeError(future.result().message)
            minimum_sequence = json.loads(future.result().message)['transition_sequence']
            # Ignore transient-local state that predates request acceptance.
            observed.clear()
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if not observed:
                continue
            latest = observed[-1]
            observed[:] = [latest]
            if latest['transition_sequence'] < minimum_sequence:
                continue
            if latest['state'] == expected and not latest['operation']:
                return latest
            if latest['state'] == 'FAULT' and latest['operation'] != 'recover':
                raise RuntimeError(latest['reason'])
        raise TimeoutError(f'system did not reach {expected}')
    finally:
        node.destroy_subscription(subscription)
        if client is not None:
            node.destroy_client(client)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['ready', 'enable', 'disable', 'recover', 'shutdown'])
    options = parser.parse_args(remove_ros_args(sys.argv)[1:])
    rclpy.init()
    node = Node('system_transition_client')
    try:
        print(json.dumps(transition(node, options.command)))
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
