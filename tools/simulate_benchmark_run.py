"""Simulate a controller benchmark run by providing a fake subprocess
that emits JSON status/progress/result lines. Used to validate
`ethercat_bridge.run_controller_benchmark` parsing and freshness logic.
"""
import time
import json
from ethercat_bridge import run_controller_benchmark, BENCHMARK_SCRIPT, load_config

class FakeProcess:
    def __init__(self, lines, returncode=0):
        # lines should be an iterable of strings (each ending with \n or not)
        self._lines = list(lines)
        self.stdout = iter(self._lines)
        self._returncode = returncode
    def poll(self):
        return None if self._returncode is None else self._returncode
    def wait(self, timeout=None):
        return 0 if self._returncode is not None else 0


def popen_factory(command, stdin=None, stdout=None, stderr=None, text=None, encoding=None, errors=None, bufsize=None, creationflags=None, start_new_session=None):
    # Build a sequence of lines emulating the child test program
    now = time.time()
    lines = []
    # inventory
    lines.append(json.dumps({"event": "inventory", "slaves": [{"id":1},{"id":2}], "slave_count":2}))
    # controller_info
    lines.append(json.dumps({"event": "controller_info", "uptime_seconds": 123, "pid": 9999}))
    # a few status samples
    status1 = {
        "event": "status",
        "statusword_hex": "0x0027",
        "actual_position": 1000,
        "actual_velocity": 0,
        "actual_torque": 0,
        "working_counter": 10,
        "wc_state": 1,
        "slave_online": True,
        "slave_operational": True,
        "al_state_hex": "0x08",
        "link_up": True,
    }
    status2 = dict(status1, actual_position=1100)
    lines.append(json.dumps(status1))
    time.sleep(0.01)
    lines.append(json.dumps(status2))
    # final result
    result = {
        "event": "result",
        "target": "controller_benchmark",
        "ok": True,
        "statusword_hex": "0x0027",
        "actual_position": 1100,
    }
    lines.append(json.dumps(result))
    return FakeProcess(lines, returncode=0)


if __name__ == '__main__':
    print('Starting simulated benchmark run...')
    # Monkeypatch load_config to force a local mode that uses the packaged benchmark script
    def _local_config():
        return {
            "mode": "local",
            "remote_controller_test": str(BENCHMARK_SCRIPT),
            "connect_timeout": 5,
            "total_timeout": 30,
            "ssh_key": "",
            "known_hosts": "",
            "user": "",
            "host": "",
            "master_index": 0,
        }

    # replace at runtime
    try:
        import ethercat_bridge as _eb
        _eb.load_config = _local_config
    except Exception:
        pass

    res = run_controller_benchmark({}, progress=print, popen_factory=popen_factory)
    print('\nSimulation result:')
    print(json.dumps(res, ensure_ascii=False, indent=2))
