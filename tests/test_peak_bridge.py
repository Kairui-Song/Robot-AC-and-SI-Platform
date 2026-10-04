from pathlib import Path

import peak_driver_bridge
from peak_driver_bridge import build_peak_command, is_peak_target, resolve_target_name


def test_peak_target_mapping():
    assert resolve_target_name('left_leg') == 'left_leg'
    assert resolve_target_name('IMU') == 'imu'
    assert is_peak_target('head') is True
    assert is_peak_target('custom_target') is False


def test_peak_command_points_to_driver_script():
    payload = build_peak_command('left_leg', channel='can0')
    assert payload['channel'] == 'can0'
    assert Path(payload['script_path']).name == 'quanbu_tongshi.py'
    assert payload['command'][0].endswith(('python', 'python.exe'))


def test_missing_peak_driver_fails_without_simulation(monkeypatch):
    monkeypatch.delenv('LINGLONG_SIMULATION_MODE', raising=False)
    monkeypatch.setattr(peak_driver_bridge, 'PEAK_DRIVER_SCRIPT', Path('does-not-exist.py'))

    result = peak_driver_bridge.run_peak_test('head')

    assert result['ok'] is False
    assert result['reason'] == 'driver_script_not_found'


def test_missing_peak_driver_can_be_explicitly_simulated(monkeypatch):
    monkeypatch.setenv('LINGLONG_SIMULATION_MODE', 'true')
    monkeypatch.setattr(peak_driver_bridge, 'PEAK_DRIVER_SCRIPT', Path('does-not-exist.py'))

    result = peak_driver_bridge.run_peak_test('head')

    assert result['ok'] is True
    assert result['info']['simulated'] is True
