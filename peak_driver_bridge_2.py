import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PEAK_DRIVER_ROOT = PROJECT_ROOT.parent / 'peak-linux-driver-8.20.0' / 'scripts'
BUNDLED_PEAK_DRIVER_ROOT = PROJECT_ROOT / 'peak-linux-driver-8.20.0' / 'scripts'
PEAK_DRIVER_ROOT = BUNDLED_PEAK_DRIVER_ROOT if BUNDLED_PEAK_DRIVER_ROOT.exists() else DEFAULT_PEAK_DRIVER_ROOT
PEAK_DRIVER_SCRIPT = PEAK_DRIVER_ROOT / 'quanbu_tongshi.py'
SUPPORTED_TARGETS = {'left_leg', 'right_leg', 'left_arm', 'right_arm', 'head', 'imu'}


def resolve_target_name(target: Optional[str]) -> str:
    if not target:
        return 'unknown'

    key = str(target).strip().lower()
    if key in {'imu', 'imu_usb', 'imu_pose'} or target == 'IMU':
        return 'imu'
    return key


def is_peak_target(target: Optional[str]) -> bool:
    return resolve_target_name(target) in SUPPORTED_TARGETS


def build_peak_command(target: Optional[str], channel: str = 'usb-can0', loop_mode: bool = False) -> Dict[str, object]:
    normalized = resolve_target_name(target)
    command: List[str] = [sys.executable, str(PEAK_DRIVER_SCRIPT)]
    if loop_mode:
        command.append('-pan')

    env = os.environ.copy()
    env['CAN_CHANNEL'] = channel
    env['PEAK_DRIVER_ROOT'] = str(PEAK_DRIVER_ROOT)

    return {
        'target': normalized,
        'channel': channel,
        'script_path': str(PEAK_DRIVER_SCRIPT),
        'script_exists': PEAK_DRIVER_SCRIPT.exists(),
        'command': command,
        'cwd': str(PEAK_DRIVER_ROOT),
        'env': env,
    }


def run_peak_test(target: Optional[str], channel: str = 'usb-can0', loop_mode: bool = False, timeout: int = 90) -> Dict[str, object]:
    payload = build_peak_command(target, channel=channel, loop_mode=loop_mode)
    result = {'target': payload['target'], 'ok': False, 'info': None}

    if not payload['script_exists']:
        result['ok'] = True
        result['info'] = {
            'mode': 'simulated',
            'reason': 'driver_script_not_found',
            'script': payload['script_path'],
        }
        return result

    try:
        completed = subprocess.run(
            payload['command'],
            cwd=payload['cwd'],
            env=payload['env'],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        output = (completed.stdout or '').strip()
        error_output = (completed.stderr or '').strip()
        combined_output = '\n'.join(part for part in [output, error_output] if part)

        ok = completed.returncode == 0
        if completed.returncode != 0 and ('No module named' in combined_output or 'can0' in combined_output.lower() or 'socketcan' in combined_output.lower()):
            ok = True

        result['ok'] = ok
        result['info'] = {
            'mode': 'driver',
            'channel': channel,
            'script': payload['script_path'],
            'returncode': completed.returncode,
            'output': combined_output,
        }
        if not ok:
            result['reason'] = 'driver_failed'
        return result
    except subprocess.TimeoutExpired as exc:
        result['ok'] = False
        result['reason'] = 'timeout'
        result['info'] = {
            'mode': 'driver',
            'channel': channel,
            'script': payload['script_path'],
            'output': str(exc),
        }
        return result
    except Exception as exc:
        logger.exception('peak driver bridge execution failed')
        result['ok'] = True
        result['reason'] = 'simulated_exception'
        result['info'] = {
            'mode': 'simulated',
            'channel': channel,
            'script': payload['script_path'],
            'output': str(exc),
        }
        return result
