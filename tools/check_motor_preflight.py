import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ethercat_bridge as bridge


class FakeProcess:
    def __init__(self, *_args, **_kwargs):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            '{"event":"controller_info","hostname":"ep-h507a1",'
            '"os":"Linux","kernel":"5.15-rt","architecture":"aarch64",'
            '"realtime_kernel":true,"cpu_model":"Jetson","cpu_cores":12,'
            '"memory_total_mb":32768,"memory_available_mb":24576,'
            '"load_1m":0.1,"load_5m":0.2,"load_15m":0.3,'
            '"uptime_seconds":3600,"pid":123,"scheduler":"SCHED_OTHER",'
            '"scheduler_priority":0,"igh_master_version":"1.6"}\n'
            '{"event":"inventory","master":0,"slave_count":1,'
            '"link_up":true,"slaves":[]}\n'
            '{"event":"result","target":"single_motor_preflight",'
            '"ok":true,"motion_allowed":false}\n'
        )
        self.stderr = io.StringIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15


def main():
    bridge.load_config = lambda: {
        "mode": "ssh",
        "host": "192.168.1.201",
        "user": "enpht",
        "ssh_key": __file__,
        "remote_preflight": "/opt/linglong/bin/single_motor_preflight",
        "master_index": 0,
        "connect_timeout": 8,
    }
    bridge.build_preflight_command = lambda _config: ["fake"]
    result = bridge.run_motor_preflight(
        "johnson_r90_joint_a1", popen_factory=FakeProcess
    )
    assert result["ok"] is True
    assert result["motion_allowed"] is False
    assert result["inventory"]["slave_count"] == 1
    assert result["controller_info"]["hostname"] == "ep-h507a1"
    assert result["controller_info"]["realtime_kernel"] is True
    print("motor preflight bridge check: OK")


if __name__ == "__main__":
    main()
