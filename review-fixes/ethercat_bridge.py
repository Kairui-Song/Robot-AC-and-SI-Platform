"""Run the bounded left-arm EtherCAT test locally or through SSH."""

import json
import math
import os
import re
import time
import signal
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from pathlib import PurePosixPath

from ethercat_config import load_config


CONTROLLER_SCRIPT = Path(__file__).resolve().parent / "controller" / "ethercat_left_arm_test.py"
BENCHMARK_SCRIPT = Path(__file__).resolve().parent / "controller" / "control_benchmark.py"
PREFLIGHT_BINARY = Path(__file__).resolve().parent / "controller" / "single_motor_preflight"
_active_lock = threading.Lock()
_active_processes = {}
MASTER_RESOURCE = "ethercat-master-0"
STATUS_LINE_RE = re.compile(
    r"SW=0x(?P<statusword>[0-9A-Fa-f]+)\s+"
    r"Pos=(?P<position>-?\d+)\s+"
    r"Vel=(?P<velocity>-?\d+)\s+"
    r"Torque=(?P<torque>-?\d+)\s+"
    r"WC=(?P<working_counter>\d+)\s+"
    r"WCstate=(?P<wc_state>\d+)\s+"
    r"SlaveOnline=(?P<slave_online>\d+)\s+"
    r"SlaveOP=(?P<slave_operational>\d+)\s+"
    r"AL=0x(?P<al_state>[0-9A-Fa-f]+)\s+"
    r"Link=(?P<link_up>\d+)"
)


def _normalize_controller_status(payload):
    if not isinstance(payload, dict):
        return None
    statusword = payload.get("statusword_hex", payload.get("statusword"))
    al_state = payload.get("al_state_hex", payload.get("al_state"))
    return {
        "statusword_hex": str(statusword) if statusword is not None else None,
        "actual_position": payload.get("actual_position"),
        "actual_velocity": payload.get("actual_velocity"),
        "actual_torque": payload.get("actual_torque"),
        "working_counter": payload.get("working_counter"),
        "wc_state": payload.get("wc_state"),
        "slave_online": payload.get("slave_online"),
        "slave_operational": payload.get("slave_operational"),
        "al_state_hex": str(al_state) if al_state is not None else None,
        "link_up": payload.get("link_up"),
    }


def _local_preflight_ready():
    return PREFLIGHT_BINARY.is_file() and os.access(PREFLIGHT_BINARY, os.X_OK)


def _ssh_preflight_ready(config):
    if shutil.which("ssh") is None:
        raise FileNotFoundError("本机未安装 ssh 客户端，无法连接远程主控")
    key_path = os.path.expandvars(os.path.expanduser(config["ssh_key"]))
    if not Path(key_path).is_file():
        raise FileNotFoundError(f"SSH密钥不存在: {key_path}")
    known_hosts = os.path.expandvars(os.path.expanduser(config["known_hosts"]))
    if not Path(known_hosts).is_file():
        raise FileNotFoundError(f"SSH known_hosts不存在: {known_hosts}")
    return key_path, known_hosts


def _preflight_mode_hint(config):
    if config.get("mode") == "local" and not _local_preflight_ready():
        return "本机模式缺少可执行的 single_motor_preflight，已自动回退到 SSH 远程主控模式"
    return None


def build_preflight_command(config):
    args = ["--master", str(config.get("master_index", 0))]
    requested_mode = config["mode"]
    if requested_mode == "local" and _local_preflight_ready():
        if shutil.which("sudo") is None:
            raise FileNotFoundError("本机未安装 sudo，无法执行本机只读预检")
        return ["sudo", "-n", str(PREFLIGHT_BINARY), *args], "local"

    key_path, known_hosts = _ssh_preflight_ready(config)
    remote = ["sudo", "-n", config["remote_preflight"], *args]
    return [
        "ssh", "-i", key_path,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={config['connect_timeout']}",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        f"{config['user']}@{config['host']}",
        " ".join(shlex.quote(part) for part in remote),
    ], "ssh"


def _humanize_preflight_error(exc, mode):
    text = str(exc)
    if isinstance(exc, PermissionError):
        missing = getattr(exc, "filename", "") or text
        if "ssh" in missing:
            return "当前后端进程无权执行 ssh。请在普通终端启动 app.py，或切换到本机 local 模式。"
        if "sudo" in missing:
            return "当前后端进程无权执行 sudo。请在普通终端启动 app.py。"
    if "sudo: 需要密码" in text:
        return "sudo 仍要求密码。请为只读预检程序配置 NOPASSWD 规则。"
    if "找不到命令" in text and "single_motor_preflight" in text:
        return "本机缺少 single_motor_preflight 可执行文件。请编译本机预检程序，或切换到 SSH 远程主控模式。"
    if mode == "local" and not _local_preflight_ready():
        return "本机模式缺少可执行的 single_motor_preflight。请切换到 SSH 远程主控模式，或先编译本机预检程序。"
    return text


def _reserve_resource(test_id):
    """Reserve a physical resource before launching a child process."""
    with _active_lock:
        if test_id in _active_processes:
            return False
        _active_processes[test_id] = None
    return True


def run_motor_preflight(profile_id, controller_profile="auto", progress=None, test_id=MASTER_RESOURCE, popen_factory=subprocess.Popen):
    from motor_profiles import get_profile

    profile = get_profile(profile_id)
    config = load_config()
    try:
        command, effective_mode = build_preflight_command(config)
    except Exception as exc:
        return {"target": "single_motor_preflight", "ok": False, "error": _humanize_preflight_error(exc, config.get("mode", "ssh"))}
    if progress:
        progress({"stage": "connecting", "mode": effective_mode, "host": config["host"] if effective_mode == "ssh" else "本机"})
        mode_hint = _preflight_mode_hint(config)
        if mode_hint:
            progress({"stage": "mode_fallback", "message": mode_hint, "mode": effective_mode, "host": config["host"]})
    if not _reserve_resource(test_id):
        return {"target": "single_motor_preflight", "ok": False, "error": "EtherCAT Master0 已被其他测试占用"}
    process = None
    result = None
    inventory = None
    controller_info = None
    diagnostic_lines = []
    timed_out = threading.Event()
    watchdog = None
    try:
        process = popen_factory(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        with _active_lock:
            _active_processes[test_id] = process
        def _timeout_process():
            timed_out.set()
            if process.poll() is None:
                process.terminate()
        watchdog = threading.Timer(config["connect_timeout"] + 20, _timeout_process)
        watchdog.daemon = True
        watchdog.start()
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    diagnostic_lines.append(line.strip())
                continue
            event_type = event.pop("event", "")
            if event_type == "progress" and progress:
                progress(event)
            elif event_type == "inventory":
                inventory = event
                if progress:
                    progress({"stage": "inventory", **event})
            elif event_type == "controller_info":
                controller_info = event
                if progress:
                    progress({"stage": "controller_info", **event})
            elif event_type == "result":
                result = event
        returncode = process.wait(timeout=2)
        if result is None:
            result = {"target": "single_motor_preflight", "ok": False,
                      "error": "只读预检超时" if timed_out.is_set() else
                      "；".join(diagnostic_lines[-3:]) or f"只读预检异常退出，返回码 {returncode}"}
        result.update(returncode=returncode, mode=effective_mode, configured_mode=config["mode"], profile_id=profile_id,
                      profile=profile, inventory=inventory, controller_info=controller_info,
                      controller_profile=controller_profile, motion_allowed=False)
        inventory_slaves = (inventory or {}).get("slaves") or []
        expected_count = config.get("expected_slave_count", 1)
        identity_known = profile.get("vendor_id") is not None and profile.get("product_code") is not None
        identity_match = any(
            slave.get("vendor_id") == profile.get("vendor_id") and
            slave.get("product_code") == profile.get("product_code")
            for slave in inventory_slaves
        ) if identity_known else None
        levels = {
            "L1_test_client": controller_info is not None,
            "L2_master": inventory is not None,
            "L3_link": bool((inventory or {}).get("link_up")),
            "L4_topology": (inventory or {}).get("slave_count") == expected_count,
            "L5_identity": identity_match,
        }
        result.update(levels=levels, expected_slave_count=expected_count,
                      identity_known=identity_known, identity_match=identity_match)
        result["ok"] = all(levels[key] for key in ("L1_test_client", "L2_master", "L3_link", "L4_topology"))
        result["assessment"] = "通信基础通过，设备身份待确认" if result["ok"] and identity_match is None else "身份匹配" if result["ok"] and identity_match else "预检未通过"
        return result
    except Exception as exc:
        return {"target": "single_motor_preflight", "ok": False, "error": _humanize_preflight_error(exc, effective_mode),
                "profile_id": profile_id, "profile": profile, "motion_allowed": False, "mode": effective_mode,
                "configured_mode": config["mode"]}
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if process is not None and process.poll() is None:
            process.terminate()
        with _active_lock:
            if _active_processes.get(test_id) is process:
                _active_processes.pop(test_id, None)


def build_benchmark_command(config, options):
    timeout_seconds = max(1, int(config.get("total_timeout", 90)))
    master_index = max(0, min(int(config.get("master_index", 0)), 255))
    timeout_prefix = ["timeout", "--signal=TERM", "--kill-after=5s", f"{timeout_seconds}s"]
    if config["mode"] == "local":
        return [
            *timeout_prefix,
            "sudo", "-n", str(Path(config.get("remote_controller_test", BENCHMARK_SCRIPT))),
            "--master", str(master_index),
        ]
    key_path = os.path.expandvars(os.path.expanduser(config["ssh_key"]))
    if not Path(key_path).is_file():
        raise FileNotFoundError(f"SSH密钥不存在: {key_path}")
    known_hosts = os.path.expandvars(os.path.expanduser(config["known_hosts"]))
    if not Path(known_hosts).is_file():
        raise FileNotFoundError(f"SSH known_hosts不存在: {known_hosts}")
    # The remote watchdog remains effective even when the SSH client is killed
    # or stops receiving output.  It bounds the process that owns Master0.
    remote = [
        *timeout_prefix,
        "sudo", "-n", config["remote_controller_test"], "--master", str(master_index),
    ]
    return [
        "ssh", "-i", key_path,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={config['connect_timeout']}",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        f"{config['user']}@{config['host']}",
        " ".join(shlex.quote(part) for part in remote),
    ]


def _parse_controller_status_line(line):
    match = STATUS_LINE_RE.search(line.strip())
    if not match:
        return None
    groups = match.groupdict()
    return {
        "statusword_hex": f"0x{groups['statusword'].upper().zfill(4)}",
        "actual_position": int(groups["position"]),
        "actual_velocity": int(groups["velocity"]),
        "actual_torque": int(groups["torque"]),
        "working_counter": int(groups["working_counter"]),
        "wc_state": int(groups["wc_state"]),
        "slave_online": bool(int(groups["slave_online"])),
        "slave_operational": bool(int(groups["slave_operational"])),
        "al_state_hex": f"0x{groups['al_state'].upper().zfill(2)}",
        "link_up": bool(int(groups["link_up"])),
    }


def _parse_controller_event_line(line):
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    event_type = payload.get("event")
    if event_type == "status":
        status = _normalize_controller_status(payload)
        return {"kind": "status", "payload": status} if status else None
    if event_type == "progress":
        return {
            "kind": "progress",
            "payload": {
                "stage": payload.get("stage", "progress"),
                "level": payload.get("level"),
                "message": payload.get("message"),
            },
        }
    if event_type == "controller_info":
        info = dict(payload)
        info.pop("event", None)
        return {"kind": "controller_info", "payload": info}
    if event_type == "result":
        result = dict(payload)
        result.pop("event", None)
        status = _normalize_controller_status(result)
        if status:
            result.update(status)
        return {"kind": "result", "payload": result}
    return {"kind": "log", "payload": {"message": text}}


def _humanize_benchmark_error(text):
    message = str(text or "")
    if "Device or resource busy" in message or "Failed to reserve master" in message:
        return "EtherCAT Master0 当前被其他进程占用。请先释放远端 /dev/EtherCAT0，再重新启动 JE 主控测试。"
    if "Failed to request EtherCAT Master0" in message:
        return "远端 JE 测试程序未能申请 Master0。通常是 /dev/EtherCAT0 已被旧测试进程或常驻服务占用。"
    return message


def stop_active_test(test_id):
    with _active_lock:
        process = _active_processes.get(test_id)
    if process is None or process.poll() is not None:
        return False
    _terminate_process(process)
    return True


def _terminate_process(process):
    """Terminate the launched command and its local POSIX process group."""
    if process is None or process.poll() is not None:
        return
    if os.name != "nt":
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    else:
        process.terminate()


def run_controller_benchmark(
    options,
    progress=None,
    test_id=MASTER_RESOURCE,
    popen_factory=subprocess.Popen,
    timer_factory=threading.Timer,
):
    config = load_config()
    try:
        command = build_benchmark_command(config, options or {})
    except Exception as exc:
        return {"target": "controller_benchmark", "ok": False, "error": _humanize_benchmark_error(exc)}
    if progress:
        progress({"stage": "connecting", "mode": config["mode"], "host": config["host"]})
    if not _reserve_resource(test_id):
        return {"target": "controller_benchmark", "ok": False, "error": "EtherCAT Master0 已被其他测试占用"}
    process = None
    result = None
    status_samples = []
    last_status_received = None
    try:
        fresh_threshold = float(os.environ.get("LINGLONG_STATUS_FRESH_SECONDS", "2.0"))
        if not math.isfinite(fresh_threshold) or fresh_threshold <= 0:
            fresh_threshold = 2.0
    except (TypeError, ValueError):
        fresh_threshold = 2.0
    diagnostic_lines = []
    controller_info = None
    timed_out = threading.Event()
    watchdog = None
    try:
        process = popen_factory(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        with _active_lock:
            _active_processes[test_id] = process

        def _timeout_process():
            timed_out.set()
            _terminate_process(process)
            if progress:
                progress({
                    "stage": "timeout",
                    "reason": "total_timeout",
                    "timeout_seconds": config["total_timeout"],
                })

        # Do not rely on Popen.wait(timeout=...) here: stdout iteration can
        # block forever before wait is reached when the child becomes silent.
        watchdog = timer_factory(config["total_timeout"], _timeout_process)
        watchdog.daemon = True
        watchdog.start()
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            diagnostic_lines.append(text)
            structured = _parse_controller_event_line(text)
            if structured:
                if structured["kind"] == "status":
                    status = structured["payload"]
                    # 标记状态样本的采样时间，便于判断是否为过期/陈旧数据
                    status["ts"] = time.time()
                    last_status_received = time.monotonic()
                    status_samples.append(status)
                    if progress:
                        progress({**status, "stage": "status", "status_fresh": True,
                                  "status_age_seconds": 0.0, "status_fresh_seconds": fresh_threshold})
                    continue
                if structured["kind"] == "progress":
                    event = structured["payload"]
                    if progress:
                        progress({
                            "stage": event.get("stage") or "info",
                            "level": event.get("level"),
                            "message": event.get("message"),
                        })
                    continue
                if structured["kind"] == "controller_info":
                    controller_info = structured["payload"]
                    if progress:
                        progress({"stage": "controller_info", **controller_info})
                    continue
                if structured["kind"] == "result":
                    result = structured["payload"]
                    continue
                if structured["kind"] == "log" and progress:
                    progress({"stage": "log", "message": structured["payload"]["message"]})
                    continue
            status = _parse_controller_status_line(text)
            if status:
                # 标记通过解析行得到的状态样本的时间戳
                status["ts"] = time.time()
                last_status_received = time.monotonic()
                status_samples.append(status)
                if progress:
                    progress({**status, "stage": "status", "status_fresh": True,
                                  "status_age_seconds": 0.0, "status_fresh_seconds": fresh_threshold})
                continue
            if text.startswith("[OK]") and progress:
                progress({"stage": "info", "level": "ok", "message": text[4:].strip()})
            elif text.startswith("[WARN]") and progress:
                progress({"stage": "info", "level": "warn", "message": text[6:].strip()})
            elif text.startswith("[INFO]") and progress:
                progress({"stage": "info", "level": "info", "message": text[6:].strip()})
            elif progress:
                progress({"stage": "log", "message": text})
        returncode = process.wait(timeout=5)
        last_status = status_samples[-1] if status_samples else {}
        status_age = (None if last_status_received is None else
                      max(0.0, time.monotonic() - last_status_received))
        status_fresh = status_age is not None and status_age <= fresh_threshold
        default_result = {
            "target": "controller_benchmark",
            "ok": returncode == 0 and bool(status_samples),
            "returncode": returncode,
            "mode": config["mode"],
            "program_type": "je_single_motor_test",
            "transport": "igh_ecrt",
            "motion_allowed": False,
            "remote_controller_test": config.get("remote_controller_test"),
            "master_index": config.get("master_index", 0),
            "sample_count": len(status_samples),
            "status_samples": status_samples[-20:],
            "controller_info": controller_info,
            "statusword_hex": last_status.get("statusword_hex") if status_fresh else None,
            "actual_position": last_status.get("actual_position") if status_fresh else None,
            "actual_velocity": last_status.get("actual_velocity") if status_fresh else None,
            "actual_torque": last_status.get("actual_torque") if status_fresh else None,
            "working_counter": last_status.get("working_counter"),
            "wc_state": last_status.get("wc_state"),
            "slave_online": last_status.get("slave_online"),
            "slave_operational": last_status.get("slave_operational"),
            "al_state_hex": last_status.get("al_state_hex"),
            "link_up": last_status.get("link_up") if status_fresh else None,
            "status_fresh": status_fresh,
            "status_age_seconds": round(status_age, 3) if status_age is not None else None,
            "info": diagnostic_lines[-1] if diagnostic_lines else None,
        }
        if timed_out.is_set():
            result = {
                **default_result,
                "ok": False,
                "reason": "total_timeout",
                "timeout_seconds": config["total_timeout"],
                "error": f"JE 主控测试超过 {config['total_timeout']} 秒，已终止测试进程。",
            }
        elif isinstance(result, dict):
            result = {**default_result, **result}
            if status_samples:
                result.update(last_status)
            if "ok" not in result:
                result["ok"] = returncode == 0 and bool(status_samples)
        else:
            result = default_result
        # Child result payloads must not override the bridge's freshness decision.
        result.update(status_fresh=status_fresh, status_age_seconds=status_age,
                      status_fresh_seconds=fresh_threshold)
        if not status_fresh:
            for field in ("statusword_hex", "actual_position", "actual_velocity",
                          "actual_torque", "working_counter", "wc_state", "slave_online",
                          "slave_operational", "al_state_hex", "link_up"):
                result[field] = None
        if not result["ok"]:
            result["error"] = _humanize_benchmark_error(
                "；".join(diagnostic_lines[-5:]) or f"测试程序异常退出，返回码{returncode}"
            )
        return result
    except Exception as exc:
        if timed_out.is_set():
            return {
                "target": "controller_benchmark",
                "ok": False,
                "reason": "total_timeout",
                "timeout_seconds": config["total_timeout"],
                "error": f"JE 主控测试超过 {config['total_timeout']} 秒，已终止测试进程。",
                "mode": config["mode"],
            }
        return {"target": "controller_benchmark", "ok": False, "error": _humanize_benchmark_error(exc), "mode": config["mode"]}
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if process is not None and process.poll() is None:
            _terminate_process(process)
        with _active_lock:
            if _active_processes.get(test_id) is process:
                _active_processes.pop(test_id, None)
