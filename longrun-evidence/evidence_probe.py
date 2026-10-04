"""Passive Jazzy diagnostics and Linux scheduling evidence; no robot commands."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import time

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy


def read(path):
    try:
        return Path(path).read_text()
    except OSError as exc:
        return str(exc)


def processes():
    rows = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmd = (p / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if not any(s in cmd for s in ('ros2_control_node', 'control_diagnostics',
                                          'robot_state_publisher', 'trajectory_demo')):
                continue
            rows.append(dict(pid=int(p.name), command=cmd,
                             status=read(p / 'status'), stat=read(p / 'stat'),
                             threads={t.name: read(t / 'schedstat')
                                      for t in (p / 'task').iterdir()}))
        except OSError:
            continue
    return rows


def main():
    out = Path(sys.argv[1])
    logger = logging.getLogger('evidence')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(out / 'telemetry.jsonl', maxBytes=16*1024*1024,
                                 backupCount=31, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)

    def emit(kind, **data):
        logger.info(json.dumps(dict(kind=kind, wall=time.time(), monotonic=time.monotonic(),
                                    boottime=time.clock_gettime(time.CLOCK_BOOTTIME), **data)))

    rclpy.init()
    node = Node('linglong_longrun_evidence')

    def receive(msg):
        statuses = []
        for s in msg.status:
            level = s.level[0] if isinstance(s.level, bytes) else int(s.level)
            statuses.append(dict(name=s.name, level=level, message=s.message,
                                 hardware_id=s.hardware_id,
                                 values={v.key: v.value for v in s.values}))
        emit('diagnostics', stamp_sec=msg.header.stamp.sec,
             stamp_nanosec=msg.header.stamp.nanosec, statuses=statuses)

    node.create_subscription(DiagnosticArray, '/diagnostics', receive,
                             QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT))
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    emit('start', pid=os.getpid(), cpu_count=os.cpu_count(),
         note='Observation only; probe adds some load. Rotation cap: 512 MiB.')
    (out / 'probe-ready').write_text(str(os.getpid()))
    next_sample = time.monotonic()
    try:
        while running and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
            now = time.monotonic()
            if now >= next_sample:
                emit('resources', sampling_delay_seconds=max(0, now-next_sample),
                     proc_stat=read('/proc/stat'), vmstat=read('/proc/vmstat'),
                     memory=read('/proc/meminfo'), load=read('/proc/loadavg'),
                     pressure={k: read('/proc/pressure/' + k) for k in ('cpu', 'memory', 'io')},
                     processes=processes())
                next_sample = time.monotonic() + 2
    finally:
        emit('stop')
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        handler.close()


if __name__ == '__main__':
    main()
