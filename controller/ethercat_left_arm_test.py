#!/usr/bin/env python3
"""Safe, bounded EtherCAT jog test for the five-axis left arm.

The script must run as root (normally through sudo). It prints one JSON object
per line so the web application can relay progress without parsing human text.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time


# The deployed left arm is connected at EtherCAT slave positions 1, 2, 3
# and 5.  Position 4 is not a left-arm drive (the proven dance_flow script
# intentionally skips it), so including it makes the preflight check abort
# before any joint can move.
JOINTS = (1, 2, 3, 5)
MASTER = "0"
MODE_CSP = 8

# EYOU_ServoModule_V144 (vendor 0x1097, product 0x2406) objects exposed by
# RxPDO 0x1600 and TxPDO 0x1a00.
CONTROL_WORD = "0x6040"
STATUS_WORD = "0x6041"
TARGET_POSITION = "0x607a"
POSITION_ACTUAL = "0x6064"
VELOCITY_ACTUAL = "0x606c"
TORQUE_ACTUAL = "0x6077"
MODE_OF_OPERATION = "0x6060"
MODE_DISPLAY = "0x6061"
ERROR_CODE = "0x603f"


class Cancelled(RuntimeError):
    pass


class EthercatError(RuntimeError):
    pass


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def parse_ethercat_value(output):
    tokens = re.findall(r"-?0x[0-9a-fA-F]+|-?\d+", output or "")
    if not tokens:
        raise EthercatError(f"无法解析 EtherCAT 返回值: {output!r}")
    token = tokens[-1]
    sign = -1 if token.startswith("-") else 1
    token = token[1:] if sign < 0 else token
    return sign * int(token, 16 if token.lower().startswith("0x") else 10)


class EthercatRunner:
    def __init__(self):
        self.cancelled = False

    def cancel(self, *_args):
        self.cancelled = True

    def check_cancelled(self):
        if self.cancelled:
            raise Cancelled("测试已停止")

    def run(self, args, timeout=8):
        self.check_cancelled()
        completed = subprocess.run(
            ["ethercat", "-m", MASTER, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise EthercatError(detail or f"ethercat 返回码 {completed.returncode}")
        return (completed.stdout or "").strip()

    def download(self, joint, index, subindex, data_type, value):
        return self.run(
            ["download", "-p", str(joint), index, subindex, "-t", data_type, str(value)]
        )

    def upload(self, joint, index, subindex, data_type):
        return parse_ethercat_value(
            self.run(["upload", "-p", str(joint), index, subindex, "-t", data_type])
        )

    def state(self, joint, state):
        return self.run(["states", "-p", str(joint), state])


class LeftArmJogTest:
    def __init__(
        self,
        runner,
        amplitude=5000,
        tolerance=1000,
        step_timeout=3.0,
        hold=0.3,
        total_timeout=90.0,
        sleep=time.sleep,
    ):
        self.runner = runner
        self.amplitude = int(amplitude)
        self.tolerance = int(tolerance)
        self.step_timeout = float(step_timeout)
        self.hold = float(hold)
        self.total_timeout = float(total_timeout)
        self.sleep = sleep
        self.started = None
        self.original_positions = {}

    def _check_total_timeout(self):
        self.runner.check_cancelled()
        if self.started is not None and time.monotonic() - self.started > self.total_timeout:
            raise EthercatError("测试总超时")

    def _verify_slaves(self):
        output = self.runner.run(["slaves"])
        servo_rows = []
        for line in output.splitlines():
            match = re.match(r"\s*(\d+)\s+\d+:\d+\s+(\w+)\s+\+", line)
            if match and int(match.group(1)) in JOINTS:
                servo_rows.append((int(match.group(1)), match.group(2).upper()))
        found = {joint for joint, _state in servo_rows}
        if found != set(JOINTS):
            raise EthercatError(f"伺服从站不完整，检测到 {sorted(found)}，期望 {list(JOINTS)}")
        emit("progress", stage="slaves_checked", slaves=[j for j, _ in servo_rows])

    def _initialize_joint(self, joint):
        self.runner.state(joint, "INIT")
        self.sleep(0.2)
        self.runner.state(joint, "PREOP")
        self.sleep(0.2)
        # The EYOU SII already assigns RxPDO 0x1600 and TxPDO 0x1a00.
        # Rewriting 0x1c12/0x1c13 is unnecessary and some firmware revisions
        # reject it. Select CSP and use the existing mapping.
        self.runner.download(joint, MODE_OF_OPERATION, "0x00", "int8", MODE_CSP)
        self.runner.state(joint, "OP")
        self.sleep(0.3)
        # CiA 402 fault reset and enable sequence used by the field SOP.
        self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 128)
        self.sleep(0.5)
        self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 0)
        self.sleep(0.5)
        self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 6)
        self.sleep(0.2)
        self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 7)
        self.sleep(0.2)
        self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 15)
        self.sleep(0.2)
        status = self.runner.upload(joint, STATUS_WORD, "0x00", "uint16")
        if status & 0x006F != 0x0027:
            raise EthercatError(f"关节{joint}未进入使能状态，状态字=0x{status:04x}")
        mode_display = self.runner.upload(joint, MODE_DISPLAY, "0x00", "int8")
        if mode_display != MODE_CSP:
            raise EthercatError(
                f"关节{joint}未进入CSP模式，模式显示={mode_display}，期望={MODE_CSP}"
            )
        return status

    def _wait_position(self, joint, target):
        deadline = time.monotonic() + self.step_timeout
        last = None
        while time.monotonic() < deadline:
            self._check_total_timeout()
            # Match the proven dance_flow behavior: in CSP the target is
            # refreshed cyclically instead of being written only once.
            self.runner.download(joint, TARGET_POSITION, "0x00", "int32", target)
            last = self.runner.upload(joint, POSITION_ACTUAL, "0x00", "int32")
            if abs(last - target) <= self.tolerance:
                return last
            self.sleep(0.03)
        raise EthercatError(
            f"关节{joint}位置反馈超时，目标={target}，实际={last}，允许误差={self.tolerance}"
        )

    def _move(self, joint, target):
        reached = self._wait_position(joint, target)
        self.sleep(self.hold)
        return reached

    def _telemetry(self, joint):
        return {
            "position": self.runner.upload(joint, POSITION_ACTUAL, "0x00", "int32"),
            "velocity": self.runner.upload(joint, VELOCITY_ACTUAL, "0x00", "int32"),
            "torque": self.runner.upload(joint, TORQUE_ACTUAL, "0x00", "int16"),
            "mode": self.runner.upload(joint, MODE_DISPLAY, "0x00", "int8"),
            "status_word": f"0x{self.runner.upload(joint, STATUS_WORD, '0x00', 'uint16'):04x}",
            "error_code": f"0x{self.runner.upload(joint, ERROR_CODE, '0x00', 'uint16'):04x}",
        }

    def _disable(self, joint):
        try:
            self.runner.download(joint, CONTROL_WORD, "0x00", "uint16", 0)
        except Exception as exc:
            emit("warning", joint=joint, message=f"失能失败: {exc}")

    def _recover(self, joint):
        original = self.original_positions.get(joint)
        if original is None:
            return None
        try:
            self.runner.download(joint, TARGET_POSITION, "0x00", "int32", original)
            return self._wait_position(joint, original)
        except Exception as exc:
            emit("warning", joint=joint, message=f"恢复原位失败: {exc}")
            return None

    def run(self):
        self.started = time.monotonic()
        results = []
        emit("progress", stage="checking_slaves")
        self._verify_slaves()
        try:
            for joint in JOINTS:
                item_started = time.monotonic()
                item = {"joint": joint, "ok": False}
                emit("progress", stage="initializing", joint=joint)
                try:
                    status = self._initialize_joint(joint)
                    original = self.runner.upload(joint, POSITION_ACTUAL, "0x00", "int32")
                    self.original_positions[joint] = original
                    targets = [original + self.amplitude, original, original - self.amplitude, original]
                    reached = []
                    for index, target in enumerate(targets, 1):
                        emit("progress", stage="jogging", joint=joint, step=index, target=target)
                        reached.append(self._move(joint, target))
                    final = self.runner.upload(joint, POSITION_ACTUAL, "0x00", "int32")
                    telemetry = self._telemetry(joint)
                    item.update(
                        ok=abs(final - original) <= self.tolerance,
                        original_position=original,
                        targets=targets,
                        reached_positions=reached,
                        final_position=final,
                        status_word=telemetry["status_word"],
                        initial_status_word=f"0x{status:04x}",
                        telemetry=telemetry,
                    )
                    if not item["ok"]:
                        item["error"] = "最终位置未回到允许误差范围"
                except Cancelled:
                    item["error"] = "测试已停止"
                    item["cancelled"] = True
                    self._recover(joint)
                    results.append(item)
                    raise
                except Exception as exc:
                    item["error"] = str(exc)
                    self._recover(joint)
                finally:
                    item["duration"] = round(time.monotonic() - item_started, 3)
                    self._disable(joint)
                results.append(item)
                emit("joint_result", **item)
        finally:
            for joint in JOINTS:
                self._disable(joint)

        summary = {
            "target": "left_arm",
            "ok": bool(results) and all(item["ok"] for item in results),
            "joints": results,
            "total": len(results),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
            "duration": round(time.monotonic() - self.started, 3),
        }
        emit("result", **summary)
        return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--amplitude", type=int, default=5000)
    parser.add_argument("--tolerance", type=int, default=1000)
    parser.add_argument("--step-timeout", type=float, default=3.0)
    parser.add_argument("--hold", type=float, default=0.3)
    parser.add_argument("--total-timeout", type=float, default=90.0)
    args = parser.parse_args()
    if os.name != "nt" and os.geteuid() != 0:
        emit("result", target="left_arm", ok=False, error="必须使用 sudo/root 运行")
        return 2
    runner = EthercatRunner()
    signal.signal(signal.SIGINT, runner.cancel)
    signal.signal(signal.SIGTERM, runner.cancel)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, runner.cancel)
    try:
        result = LeftArmJogTest(
            runner,
            amplitude=args.amplitude,
            tolerance=args.tolerance,
            step_timeout=args.step_timeout,
            hold=args.hold,
            total_timeout=args.total_timeout,
        ).run()
        return 0 if result["ok"] else 1
    except Cancelled:
        emit("result", target="left_arm", ok=False, cancelled=True, error="测试已停止")
        return 130
    except Exception as exc:
        emit("result", target="left_arm", ok=False, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
