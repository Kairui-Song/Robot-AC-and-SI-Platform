import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "mode": "local",
    "host": "192.168.1.201",
    "user": "enpht",
    "ssh_key": str(Path.home() / ".ssh" / "id_ed25519"),
    "known_hosts": str(Path.home() / ".ssh" / "known_hosts"),
    "remote_script": "/opt/linglong/ethercat_left_arm_test.py",
    "remote_dance_script": "/opt/linglong/dance_flow.sh",
    "remote_preflight": "/opt/linglong/bin/controller_test_client",
    "remote_controller_test": "/opt/linglong/bin/je_single_motor_test_v2",
    "master_index": 0,
    "expected_slave_count": 1,
    "connect_timeout": 8,
    "total_timeout": 90,
}


def runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = Path(os.environ.get("LINGLONG_CONFIG_PATH", runtime_dir() / "linglong_config.json"))


def load_config():
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config.update({
            key: value
            for key, value in data.items()
            if key in DEFAULTS
        })
    return config


def save_config(payload):
    if "sudo_password" in payload or "sudo_password_encrypted" in payload:
        raise ValueError("不再支持保存 sudo 密码；请为固定只读命令配置 NOPASSWD 规则")
    mode = str(payload.get("mode", DEFAULTS["mode"]))
    if mode not in {"ssh", "local"}:
        raise ValueError("mode 必须是 ssh 或 local")
    data = {
        "mode": mode,
        "host": str(payload.get("host", DEFAULTS["host"])).strip(),
        "user": str(payload.get("user", DEFAULTS["user"])).strip(),
        "ssh_key": str(payload.get("ssh_key", DEFAULTS["ssh_key"])).strip(),
        "known_hosts": str(payload.get("known_hosts", DEFAULTS["known_hosts"])).strip(),
        "remote_script": str(payload.get("remote_script", DEFAULTS["remote_script"])).strip(),
        "remote_dance_script": str(
            payload.get("remote_dance_script", DEFAULTS["remote_dance_script"])
        ).strip(),
        "remote_preflight": str(
            payload.get("remote_preflight", DEFAULTS["remote_preflight"])
        ).strip(),
        "remote_controller_test": str(
            payload.get("remote_controller_test", DEFAULTS["remote_controller_test"])
        ).strip(),
        "master_index": max(0, min(int(payload.get("master_index", 0)), 255)),
        "expected_slave_count": max(1, min(int(payload.get("expected_slave_count", 1)), 255)),
        "connect_timeout": max(1, int(payload.get("connect_timeout", 8))),
        "total_timeout": max(10, int(payload.get("total_timeout", 90))),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        CONFIG_PATH.chmod(0o600)
    return load_config()
