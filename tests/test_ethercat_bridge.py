import ethercat_bridge


def test_master_resource_reservation_is_global():
    ethercat_bridge._active_processes.clear()
    try:
        assert ethercat_bridge._reserve_resource(ethercat_bridge.MASTER_RESOURCE) is True
        assert ethercat_bridge._reserve_resource(ethercat_bridge.MASTER_RESOURCE) is False
    finally:
        ethercat_bridge._active_processes.clear()


def test_benchmark_command_uses_controller_test_client(tmp_path):
    key = tmp_path / "key"
    key.write_text("x", encoding="utf-8")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host", encoding="utf-8")
    config = {
        "mode": "ssh", "host": "192.168.1.201", "user": "enpht",
        "ssh_key": str(key), "remote_script": "/opt/linglong/ethercat_left_arm_test.py",
        "known_hosts": str(known_hosts),
        "connect_timeout": 8,
        "total_timeout": 90,
        "remote_controller_test": "/opt/linglong/bin/je_single_motor_test_v1",
    }
    command = ethercat_bridge.build_benchmark_command(config, {})
    assert "/opt/linglong/bin/je_single_motor_test_v1" in command[-1]
    assert "timeout --signal=TERM --kill-after=5s 90s sudo -n /opt/linglong/bin/je_single_motor_test_v1 --master 0" == command[-1]


def test_benchmark_command_uses_configured_master_index(tmp_path):
    key = tmp_path / "key"
    key.write_text("x", encoding="utf-8")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host", encoding="utf-8")
    config = {
        "mode": "ssh", "host": "192.168.1.201", "user": "enpht",
        "ssh_key": str(key), "known_hosts": str(known_hosts),
        "connect_timeout": 8, "total_timeout": 90,
        "remote_controller_test": "/opt/linglong/bin/je_single_motor_test_v2",
        "master_index": 4,
    }

    command = ethercat_bridge.build_benchmark_command(config, {})

    assert command[-1].endswith("je_single_motor_test_v2 --master 4")


def test_benchmark_timeout_terminates_process_and_reports_reason(monkeypatch):
    config = {
        "mode": "local",
        "host": "localhost",
        "total_timeout": 1,
        "remote_controller_test": "/opt/linglong/bin/je_single_motor_test_v1",
    }
    monkeypatch.setattr(ethercat_bridge, "load_config", lambda: config)

    class Process:
        stdout = []

        def __init__(self):
            self.terminated = False

        def poll(self):
            return -15 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert timeout == 5
            return -15

    process = Process()

    class ImmediateTimer:
        daemon = False

        def __init__(self, seconds, callback):
            assert seconds == 1
            self.callback = callback

        def start(self):
            self.callback()

        def cancel(self):
            pass

    events = []
    result = ethercat_bridge.run_controller_benchmark(
        {}, progress=events.append, popen_factory=lambda *_args, **_kwargs: process,
        timer_factory=ImmediateTimer,
    )

    assert process.terminated is True
    assert result["ok"] is False
    assert result["reason"] == "total_timeout"
    assert result["timeout_seconds"] == 1
    assert any(event["stage"] == "timeout" for event in events)


def test_parse_controller_status_line_extracts_runtime_state():
    status = ethercat_bridge._parse_controller_status_line(
        "SW=0x0231 Pos=123 Vel=0 Torque=0 WC=3 WCstate=2 SlaveOnline=1 SlaveOP=0 AL=0x02 Link=1"
    )

    assert status == {
        "statusword_hex": "0x0231",
        "actual_position": 123,
        "actual_velocity": 0,
        "actual_torque": 0,
        "working_counter": 3,
        "wc_state": 2,
        "slave_online": True,
        "slave_operational": False,
        "al_state_hex": "0x02",
        "link_up": True,
    }


def test_parse_controller_event_line_accepts_json_status():
    event = ethercat_bridge._parse_controller_event_line(
        '{"event":"status","statusword_hex":"0x0231","actual_position":456,'
        '"actual_velocity":0,"actual_torque":0,"working_counter":3,"wc_state":2,'
        '"slave_online":true,"slave_operational":false,"al_state_hex":"0x02","link_up":true}'
    )

    assert event == {
        "kind": "status",
        "payload": {
            "statusword_hex": "0x0231",
            "actual_position": 456,
            "actual_velocity": 0,
            "actual_torque": 0,
            "working_counter": 3,
            "wc_state": 2,
            "slave_online": True,
            "slave_operational": False,
            "al_state_hex": "0x02",
            "link_up": True,
        },
    }
