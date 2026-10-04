import json
from pathlib import Path

import pytest

from controller.ethercat_left_arm_test import (
    EthercatError,
    LeftArmJogTest,
    parse_ethercat_value,
)


class FakeEthercatRunner:
    def __init__(self, fail_joint=None):
        self.cancelled = False
        self.positions = {joint: joint * 100000 for joint in (1, 2, 3, 5)}
        self.commands = []
        self.fail_joint = fail_joint

    def check_cancelled(self):
        if self.cancelled:
            raise RuntimeError("cancelled")

    def run(self, args, timeout=8):
        self.commands.append(tuple(args))
        if args == ["slaves"]:
            return "\n".join(
                ["0  0:0 PREOP + CU1124"] +
                [f"{joint}  0:{joint} PREOP + EYOU_ServoModule" for joint in (1, 2, 3, 5)]
            )
        return ""

    def state(self, joint, state):
        self.commands.append(("state", joint, state))

    def download(self, joint, index, subindex, data_type, value):
        self.commands.append(("download", joint, index, value))
        if index == "0x607a":
            if joint == self.fail_joint:
                return
            self.positions[joint] = int(value)

    def upload(self, joint, index, subindex, data_type):
        self.commands.append(("upload", joint, index))
        if index == "0x6041":
            return 0x1237
        if index == "0x6061":
            return 8
        if index in {"0x606c", "0x6077", "0x603f"}:
            return 0
        return self.positions[joint]


def test_parse_ethercat_value_accepts_hex_and_decimal():
    assert parse_ethercat_value("0x00001237 4663") == 4663
    assert parse_ethercat_value("-123") == -123


def test_deployed_joints_jog_relative_and_disable(capsys):
    runner = FakeEthercatRunner()
    result = LeftArmJogTest(
        runner,
        amplitude=5000,
        tolerance=100,
        step_timeout=0.01,
        hold=0,
        sleep=lambda _seconds: None,
    ).run()

    assert result["ok"] is True
    assert [item["joint"] for item in result["joints"]] == [1, 2, 3, 5]
    assert result["joints"][0]["targets"] == [105000, 100000, 95000, 100000]
    for joint in (1, 2, 3, 5):
        assert ("download", joint, "0x6040", 0) in runner.commands
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "result"


def test_initialization_uses_existing_pdo_and_cia402_enable_sequence():
    runner = FakeEthercatRunner()
    test = LeftArmJogTest(runner, hold=0, sleep=lambda _seconds: None)

    test._initialize_joint(1)

    commands = runner.commands
    assert not any(command[:3] == ("download", 1, "0x1c12") for command in commands)
    assert not any(command[:3] == ("download", 1, "0x1c13") for command in commands)
    assert ("download", 1, "0x6060", 8) in commands
    control_words = [
        command[3]
        for command in commands
        if command[:3] == ("download", 1, "0x6040")
    ]
    assert control_words == [128, 0, 6, 7, 15]


def test_joint_failure_is_real_and_next_joint_continues():
    runner = FakeEthercatRunner(fail_joint=2)
    result = LeftArmJogTest(
        runner,
        amplitude=5000,
        tolerance=100,
        step_timeout=0.01,
        hold=0,
        sleep=lambda _seconds: None,
    ).run()

    assert result["ok"] is False
    assert result["joints"][1]["ok"] is False
    assert result["joints"][3]["joint"] == 5
    assert result["joints"][3]["ok"] is True


def test_missing_slave_fails_instead_of_simulating_success():
    runner = FakeEthercatRunner()
    runner.run = lambda args, timeout=8: "0  0:0 PREOP + CU1124\n1  0:1 PREOP + Servo"
    with pytest.raises(EthercatError, match="伺服从站不完整"):
        LeftArmJogTest(runner, sleep=lambda _seconds: None).run()
