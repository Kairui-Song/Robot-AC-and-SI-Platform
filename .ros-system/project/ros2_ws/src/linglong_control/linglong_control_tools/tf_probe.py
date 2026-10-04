"""Bounded, read-only TF2 lookup; no hardware or controller commands."""
import argparse
import math
import sys
import time

from linglong_control_tools.bag_contracts import write_json
from linglong_control_tools.interfaces import BASE_FRAME, TIP_FRAME


def main():
    import rclpy
    from rclpy.duration import Duration
    from rclpy.time import Time
    from rclpy.utilities import remove_ros_args
    from tf2_ros import Buffer, TransformListener, TransformException
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args(remove_ros_args(sys.argv)[1:])
    rclpy.init()
    node = rclpy.create_node('left_arm_tf_probe')
    buffer = Buffer(cache_time=Duration(seconds=5))
    listener = TransformListener(buffer, node, spin_thread=False)
    deadline = time.monotonic() + 10
    result = {'schema_version': 1, 'passed': False, 'target': BASE_FRAME, 'source': TIP_FRAME}
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            try:
                # Nonblocking lookup; spin above services the TF subscriptions.
                t = buffer.lookup_transform(BASE_FRAME, TIP_FRAME, Time())
                age = (node.get_clock().now().nanoseconds -
                       (t.header.stamp.sec * 10**9 + t.header.stamp.nanosec)) / 1e9
                p, q = t.transform.translation, t.transform.rotation
                values = [p.x, p.y, p.z, q.x, q.y, q.z, q.w]
                if all(math.isfinite(v) for v in values) and 0 <= age <= .5:
                    result.update(passed=True, age_sec=age, translation_m=values[:3],
                                  quaternion_xyzw=values[3:])
                    break
            except TransformException:
                pass
        write_json(args.output, result)
        if not result['passed']:
            raise RuntimeError('No fresh base_link <- link_5 transform within 10 seconds')
    finally:
        listener.unregister()
        node.destroy_node()
        rclpy.shutdown()
