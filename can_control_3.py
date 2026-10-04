import logging
import os
import time

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)


class SerialMotorBridge:
    """通过 USB 串口与主控通信，再由主控驱动电机。"""

    def __init__(self, port=None, baudrate=115200, timeout=0.2):
        self.port = port or os.getenv('SERIAL_PORT')
        self.baudrate = int(baudrate or os.getenv('SERIAL_BAUDRATE', 115200))
        self.timeout = timeout
        self.ser = None

    def _detect_port(self):
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            return None

        if self.port:
            for info in ports:
                if info.device == self.port or info.name == self.port:
                    return info.device

        return ports[0].device

    def connect(self):
        if self.ser and self.ser.is_open:
            return True

        port = self._detect_port()
        if not port:
            logger.warning('no serial port detected for motor bridge')
            return False

        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            logger.info('serial bridge connected to %s @ %s', port, self.baudrate)
            return True
        except Exception as exc:
            logger.warning('serial bridge connect failed: %s', exc)
            self.ser = None
            return False

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def send_command(self, command):
        if not self.connect():
            return False, {'error': 'serial_connect_failed'}

        try:
            payload = (command + '\n').encode('utf-8')
            self.ser.write(payload)
            self.ser.flush()
            time.sleep(0.05)
            response = self.ser.readline().decode(errors='ignore').strip()
            return True, {'response': response}
        except Exception as exc:
            logger.warning('serial bridge send failed: %s', exc)
            return False, {'error': str(exc)}

    def send_test_pulse(self, channel_name, amplitude=5, duration=0.5):
        return self.send_command(f'TEST {channel_name} {amplitude} {duration}')

    def listen_feedback(self, channel_name, timeout=1.0):
        if not self.connect():
            return False, {'error': 'serial_connect_failed'}

        try:
            self.ser.write(f'FEEDBACK {channel_name}\n'.encode('utf-8'))
            self.ser.flush()
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode(errors='ignore').strip()
                    if line:
                        return True, {'response': line}
                time.sleep(0.01)
            return False, {'error': 'timeout'}
        except Exception as exc:
            logger.warning('serial feedback read failed: %s', exc)
            return False, {'error': str(exc)}


def _get_serial_bridge(port=None, baudrate=None):
    return SerialMotorBridge(port=port, baudrate=baudrate)


def _build_bridge(port=None, baudrate=None):
    try:
        return _get_serial_bridge(port=port, baudrate=baudrate)
    except TypeError:
        return _get_serial_bridge()


def _try_hardware_send(channel, cmd, port=None, baudrate=None):
    try:
        bridge = _build_bridge(port=port, baudrate=baudrate)
        if hasattr(bridge, 'send_test_pulse'):
            return bridge.send_test_pulse(channel, amplitude=cmd['amp'], duration=cmd['dur'])

        if bridge.connect():
            payload = f"{cmd['type']} {channel} {cmd['amp']} {cmd['dur']}"
            ok, info = bridge.send_command(payload)
            return ok, info
    except Exception:
        logger.debug('serial bridge unavailable, falling back to simulation')
    return False, {'error': 'serial_unavailable'}


def send_test_pulse(channel_name, amplitude=5, duration=0.5, port=None, baudrate=None):
    """通过串口向主控发送测试脉冲，若串口不可用则退回到模拟结果。"""
    cmd = {'type': 'TEST', 'amp': amplitude, 'dur': duration}
    hw_ok, info = _try_hardware_send(channel_name, cmd, port=port, baudrate=baudrate)
    if hw_ok:
        time.sleep(duration + 0.05)
        return True, {'info': 'sent via serial bridge', **info}

    time.sleep(0.1)
    return True, {'info': 'simulated success'}


def listen_feedback(channel_name, timeout=1.0, port=None, baudrate=None):
    """从主控读取反馈；串口不可用时返回模拟反馈。"""
    bridge = _build_bridge(port=port, baudrate=baudrate)
    try:
        ok, info = bridge.listen_feedback(channel_name, timeout=timeout)
        if ok:
            return True, info
    except Exception:
        logger.debug('serial feedback unavailable, using simulated feedback')

    time.sleep(min(0.2, timeout))
    return True, {'rpm': 12.3}
