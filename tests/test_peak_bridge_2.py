from pathlib import Path

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
