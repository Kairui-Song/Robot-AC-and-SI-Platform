import subprocess
from unittest.mock import patch

import pytest
from arm_control.backend import (
    Calibration, EthercatBackend, MockBackend, NAMES, parse_value, validate_command,
)


@pytest.fixture
def calibration():
    return Calibration([1000., -2000., 3000., 4000.], [100., 200., 300., 400.],
                       [-1.] * 4, [1.] * 4)


def test_signed_calibration_roundtrip(calibration):
    for i in range(4):
        assert calibration.decode(i, calibration.encode(i, .25)) == .25


def test_reorder_and_invalid_commands(calibration):
    assert validate_command(NAMES[::-1], [.04, .03, .02, .01], [0.] * 4,
                            calibration, .05) == [.01, .02, .03, .04]
    for names, values in [(['joint_1'] * 4, [0.] * 4),
                          (NAMES, [float('nan')] * 4),
                          (NAMES, [float('inf')] * 4),
                          (NAMES, [2.] * 4), (NAMES, [.1] * 4),
                          (NAMES, [0.])]:
        with pytest.raises(ValueError):
            validate_command(names, values, [0.] * 4, calibration, .05)


def test_bad_calibration():
    for scales in ([0.] * 4, [float('nan')] * 4, [1.], [1e20] * 4):
        with pytest.raises(ValueError):
            Calibration(scales, [0.] * 4, [-1.] * 4, [1.] * 4)


def test_cli_mapping_and_feedback(calibration):
    backend = EthercatBackend(calibration)
    with patch('arm_control.backend.subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, '0x00000064 100', '')
        backend.write([0.] * 4)
        calls = [call.args[0] for call in run.call_args_list]
        assert [args[5] for args in calls] == ['1', '2', '3', '5']
        assert calls[0] == ['ethercat', '-m', '0', 'download', '-p', '1',
                            '0x607a', '0x00', '-t', 'int32', '100']
        assert backend.read() == [0., .05, -200 / 3000, -.075]
        assert run.call_args.args[0][6] == '0x6064'
        assert run.call_args.kwargs['timeout'] == .5
        run.return_value = subprocess.CompletedProcess([], 1, '', 'SDO failed')
        with pytest.raises(RuntimeError, match='SDO failed'):
            backend.read()


def test_parse_and_sign(calibration):
    assert parse_value('0xfffffff6 -10\n') == -10
    with pytest.raises(RuntimeError):
        parse_value('SDO error')
    backend = EthercatBackend(calibration)
    with patch.object(backend, 'run', return_value='0xfffffff6'):
        assert backend.upload(1, '0x6064', 'int32') == -10


def test_stop_attempts_all_slaves(calibration):
    backend = EthercatBackend(calibration)
    with patch.object(backend, 'download', side_effect=[RuntimeError('offline'), None, None, None]) as write:
        with pytest.raises(RuntimeError, match='p1: offline'):
            backend.stop()
        assert [call.args[0] for call in write.call_args_list] == [1, 2, 3, 5]


def test_ready_checks_mode(calibration):
    backend = EthercatBackend(calibration)
    with patch.object(backend, 'upload', side_effect=[0x27, 8] * 4):
        backend.check_ready()
    with patch.object(backend, 'upload', side_effect=[0x27, 1]):
        with pytest.raises(RuntimeError, match='CSP'):
            backend.check_ready()


def test_mock_feedback_is_separate_copy():
    backend = MockBackend()
    command = [.01] * 4
    backend.write(command)
    command[0] = 1.
    assert backend.read() == [.01] * 4
