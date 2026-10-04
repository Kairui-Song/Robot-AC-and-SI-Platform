#!/usr/bin/env python3
"""Closed-loop controller benchmark using the proven EtherCAT CLI transport."""

import argparse
import json
import math
import os
import signal
import statistics
import time

try:
    import resource
except ImportError:
    resource = None

try:
    from ethercat_left_arm_test import Cancelled, EthercatRunner, LeftArmJogTest, emit
except ImportError:
    from .ethercat_left_arm_test import Cancelled, EthercatRunner, LeftArmJogTest, emit


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(values):
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 3),
        "max": round(max(values), 3),
        "min": round(min(values), 3),
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "p99": round(percentile(values, 99), 3),
        "stdev": round(statistics.pstdev(values), 3),
    }


def read_cpu():
    with open("/proc/stat", "r", encoding="ascii") as stream:
        fields = [int(value) for value in stream.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return sum(fields), idle


def cpu_percent(before, after):
    total = after[0] - before[0]
    idle = after[1] - before[1]
    return round((1.0 - idle / total) * 100.0, 2) if total > 0 else 0.0


class ControlBenchmark:
    def __init__(
        self,
        runner,
        joint=0,
        amplitude=1000,
        frequency=10.0,
        iterations=20,
        tolerance=500,
        response_threshold=20,
        settle_timeout=3.0,
        sleep=time.sleep,
    ):
        self.runner = runner
        self.joint = int(joint)
        self.amplitude = int(amplitude)
        self.frequency = float(frequency)
        self.iterations = int(iterations)
        self.tolerance = int(tolerance)
        self.response_threshold = int(response_threshold)
        self.settle_timeout = float(settle_timeout)
        self.sleep = sleep

    def _wait_feedback(self, start_position, target):
        started_ns = None
        final_position = start_position
        deadline = time.monotonic() + self.settle_timeout
        while time.monotonic() < deadline:
            self.runner.check_cancelled()
            now_ns = time.monotonic_ns()
            final_position = self.runner.upload(self.joint, "0x6064", "0x00", "int32")
            if started_ns is None and abs(final_position - start_position) >= self.response_threshold:
                started_ns = now_ns
            if abs(final_position - target) <= self.tolerance:
                return started_ns or now_ns, now_ns, final_position
            self.sleep(0.001)
        raise RuntimeError(f"反馈超时，目标={target}，实际={final_position}")

    def run(self):
        helper = LeftArmJogTest(
            self.runner,
            amplitude=self.amplitude,
            tolerance=self.tolerance,
            step_timeout=self.settle_timeout,
        )
        emit("progress", stage="checking_slaves")
        helper._verify_slaves()
        emit("progress", stage="initializing", joint=self.joint)
        status = helper._initialize_joint(self.joint)
        original = self.runner.upload(self.joint, "0x6064", "0x00", "int32")
        period_ns = int(1_000_000_000 / self.frequency)
        start_ns = time.monotonic_ns()
        cpu_before = read_cpu()
        process_cpu_before = time.process_time()
        samples = []
        try:
            for sequence in range(self.iterations):
                scheduled_ns = start_ns + sequence * period_ns
                remaining = scheduled_ns - time.monotonic_ns()
                if remaining > 0:
                    self.sleep(remaining / 1_000_000_000)
                actual_send_ns = time.monotonic_ns()
                start_position = self.runner.upload(self.joint, "0x6064", "0x00", "int32")
                direction = 1 if sequence % 2 == 0 else -1
                target = original + direction * self.amplitude
                t0_ns = time.monotonic_ns()
                sample = {
                    "sequence": sequence,
                    "scheduled_ns": scheduled_ns,
                    "t0_ns": t0_ns,
                    "target": target,
                    "start_position": start_position,
                    "ok": False,
                }
                try:
                    self.runner.download(self.joint, "0x607a", "0x00", "int32", target)
                    command_done_ns = time.monotonic_ns()
                    t1_ns, t2_ns, final = self._wait_feedback(start_position, target)
                    sample.update(
                        ok=True,
                        command_duration_ms=(command_done_ns - t0_ns) / 1_000_000,
                        response_latency_ms=(t1_ns - t0_ns) / 1_000_000,
                        closed_loop_latency_ms=(t2_ns - t0_ns) / 1_000_000,
                        schedule_jitter_ms=(actual_send_ns - scheduled_ns) / 1_000_000,
                        final_position=final,
                    )
                except Exception as exc:
                    sample["error"] = str(exc)
                samples.append(sample)
                emit("sample", **sample)
                emit(
                    "progress",
                    stage="sampling",
                    completed=sequence + 1,
                    total=self.iterations,
                    frequency_hz=self.frequency,
                )
        finally:
            try:
                self.runner.download(self.joint, "0x607a", "0x00", "int32", original)
                helper._wait_position(self.joint, original)
            except Exception as exc:
                emit("warning", message=f"恢复原位失败: {exc}")
            helper._disable(self.joint)

        cpu_after = read_cpu()
        process_cpu_after = time.process_time()
        successful = [sample for sample in samples if sample["ok"]]
        elapsed = max((time.monotonic_ns() - start_ns) / 1_000_000_000, 1e-9)
        result = {
            "target": "controller_benchmark",
            "ok": bool(successful) and len(successful) == len(samples),
            "transport": "ethercat_cli",
            "measurement_note": "结果包含ethercat CLI进程开销，不代表Robot SDK极限频率",
            "joint": self.joint,
            "requested_frequency_hz": self.frequency,
            "iterations": self.iterations,
            "successful": len(successful),
            "failed": len(samples) - len(successful),
            "success_rate_percent": round(len(successful) * 100 / len(samples), 2) if samples else 0,
            "actual_rate_hz": round(len(samples) / elapsed, 3),
            "response_latency_ms": summarize([s["response_latency_ms"] for s in successful]),
            "closed_loop_latency_ms": summarize([s["closed_loop_latency_ms"] for s in successful]),
            "schedule_jitter_ms": summarize([s["schedule_jitter_ms"] for s in successful]),
            "command_duration_ms": summarize([s["command_duration_ms"] for s in successful]),
            "system_cpu_percent": cpu_percent(cpu_before, cpu_after),
            "process_cpu_seconds": round(process_cpu_after - process_cpu_before, 4),
            "initial_status_word": f"0x{status:04x}",
            "original_position": original,
            "samples": samples,
            "duration": round(elapsed, 3),
        }
        emit("result", **result)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--joint", type=int, choices=range(0, 256), default=0)
    parser.add_argument("--amplitude", type=int, default=1000)
    parser.add_argument("--frequency", type=float, default=10)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--tolerance", type=int, default=500)
    parser.add_argument("--settle-timeout", type=float, default=3)
    args = parser.parse_args()
    if os.name != "nt" and os.geteuid() != 0:
        emit("result", target="controller_benchmark", ok=False, error="必须使用sudo/root运行")
        return 2
    if not 1 <= args.frequency <= 1000 or not 1 <= args.iterations <= 10000:
        emit("result", target="controller_benchmark", ok=False, error="频率或样本数超出范围")
        return 2
    runner = EthercatRunner()
    signal.signal(signal.SIGINT, runner.cancel)
    signal.signal(signal.SIGTERM, runner.cancel)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, runner.cancel)
    try:
        result = ControlBenchmark(
            runner,
            joint=args.joint,
            amplitude=args.amplitude,
            frequency=args.frequency,
            iterations=args.iterations,
            tolerance=args.tolerance,
            settle_timeout=args.settle_timeout,
        ).run()
        return 0 if result["ok"] else 1
    except Cancelled:
        emit("result", target="controller_benchmark", ok=False, cancelled=True, error="测试已停止")
        return 130
    except Exception as exc:
        emit("result", target="controller_benchmark", ok=False, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
