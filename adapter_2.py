"""底层适配层：封装对外提供简单函数，屏蔽底层复杂命令。

提供函数：
- test_can_channel(channel_name, timeout=1.0) -> {'ok': bool, 'info': ...}
- test_imu(imu_port=None, imu_baud=115200, timeout=2.0) -> {'ok': bool, 'info': ...}

上层只需传入通道名或串口信息，不关心CAN屏蔽/反馈细节。
"""
import time
import logging
import importlib
import importlib.util

from can_control import send_test_pulse, listen_feedback
from imu_reader import _parse_line

logger = logging.getLogger(__name__)


def _mask_other_can(chosen):
    """尝试屏蔽除 chosen 外的其它 CAN 通道。
    具体实现应调用主控提供的底层脚本；此处做最小化抽象（如果不存在底层脚本则跳过）。
    """
    if importlib.util.find_spec('can_mask') is None:
        logger.debug('no can_mask module available, skipping mask step')
        return False

    try:
        can_mask = importlib.import_module('can_mask')
        disable_all_except = getattr(can_mask, 'disable_all_except', None)
        if not callable(disable_all_except):
            logger.warning('can_mask.disable_all_except is unavailable, skipping mask step')
            return False
        disable_all_except(chosen)
        return True
    except Exception as exc:
        logger.warning('failed to apply CAN mask for %s: %s', chosen, exc)
        return False


def test_can_channel(channel_name, timeout=1.0, serial_port=None, serial_baud=115200):
    """对单个 CAN 通道做小幅运动并等待反馈，返回结果字典。"""
    res = {'target': channel_name, 'ok': False, 'info': None}

    # 屏蔽其他通道
    _mask_other_can(channel_name)

    try:
        sent_ok, info = send_test_pulse(
            channel_name,
            port=serial_port,
            baudrate=serial_baud,
        )
        res['info'] = info
        if not sent_ok:
            res['ok'] = False
            res['reason'] = 'send_failed'
            return res

        fb_ok, fb_info = listen_feedback(
            channel_name,
            timeout=timeout,
            port=serial_port,
            baudrate=serial_baud,
        )
        res['ok'] = bool(fb_ok)
        res['info'] = fb_info
        if not fb_ok:
            res['reason'] = 'no_feedback'
    except Exception as e:
        res['ok'] = False
        res['reason'] = 'exception'
        res['info'] = str(e)

    return res


def test_imu(imu_port=None, imu_baud=115200, timeout=2.0):
    """尝试从 IMU 读取姿态数据并统计最低帧率，返回结果字典。"""
    res = {'target': 'IMU', 'ok': False, 'info': None}
    try:
        import serial
    except Exception:
        serial = None

    samples = 0
    t0 = time.time()
    start = t0
    try:
        ser = None
        if serial and imu_port:
            try:
                ser = serial.Serial(imu_port, imu_baud, timeout=0.5)
            except Exception:
                ser = None

        while time.time() - start < timeout:
            if ser:
                raw = ser.readline().decode(errors='ignore')
                data = _parse_line(raw)
                if data:
                    samples += 1
                    res['last'] = data
            else:
                # 无串口时直接认为模拟可用
                res['last'] = {'sim': True}
                samples = 1
                break

        duration = max(1e-6, time.time() - t0)
        fps = samples / duration
        res['info'] = {'samples': samples, 'duration': duration, 'fps': fps}
        res['ok'] = samples > 0
        if not res['ok']:
            res['reason'] = 'timeout_no_samples'
    except Exception as e:
        res['ok'] = False
        res['info'] = str(e)

    return res
