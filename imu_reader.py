import threading
import time
import json
import os


def _simulation_enabled():
    return os.getenv('LINGLONG_SIMULATION_MODE', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _emit_status(socketio, mode, reason=None):
    payload = {'mode': mode}
    if reason:
        payload['reason'] = reason
    socketio.emit('imu_status', payload)

def _parse_line(line):
    line = line.strip()
    if not line:
        return None
    # try JSON first
    try:
        return json.loads(line)
    except Exception:
        pass

    # try CSV floats
    try:
        parts = [p for p in line.replace('\r', '').split(',') if p!='']
        vals = [float(p) for p in parts]
        # map common lengths
        if len(vals) >= 3:
            return {'ax': vals[0], 'ay': vals[1], 'az': vals[2], 'raw': line}
    except Exception:
        pass

    return {'raw': line}


def _imu_loop(socketio, port, baud, stop_event):
    """Read IMU data with bounded reconnects; never fabricate production telemetry."""
    try:
        import serial
    except Exception as exc:
        serial = None
        serial_error = str(exc)
    else:
        serial_error = None

    ser = None
    retry_delay = 1.0
    next_retry = 0.0
    last_data_at = None
    last_status = None

    while not stop_event.is_set():
        try:
            now = time.monotonic()
            if ser is None and now >= next_retry:
                if not port:
                    reason = '未配置 IMU_PORT'
                elif serial is None:
                    reason = f'pyserial 不可用: {serial_error}'
                else:
                    try:
                        ser = serial.Serial(port, baud, timeout=1)
                        last_data_at = time.monotonic()
                        retry_delay = 1.0
                        if last_status != 'online':
                            _emit_status(socketio, 'online')
                            last_status = 'online'
                        continue
                    except Exception as exc:
                        reason = f'无法打开 {port}: {exc}'
                if _simulation_enabled():
                    if last_status != 'simulated':
                        _emit_status(socketio, 'simulated', reason)
                        last_status = 'simulated'
                    simulated = {
                        'timestamp': time.time(), 'simulated': True,
                        'yaw': (time.time() * 30) % 360,
                        'pitch': (time.time() * 10) % 90,
                        'roll': (time.time() * 5) % 45,
                    }
                    socketio.emit('imu_data', simulated)
                    stop_event.wait(0.2)
                    continue
                if last_status != 'offline':
                    _emit_status(socketio, 'offline', reason)
                    last_status = 'offline'
                next_retry = now + retry_delay
                retry_delay = min(retry_delay * 2, 10.0)
                stop_event.wait(0.2)
                continue

            if ser is not None:
                raw = ser.readline().decode(errors='ignore')
                data = _parse_line(raw)
                if data:
                    last_data_at = time.monotonic()
                    socketio.emit('imu_data', data)
                elif last_data_at and time.monotonic() - last_data_at >= 5.0:
                    raise TimeoutError('连续 5 秒未收到 IMU 数据')
        except Exception as exc:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
            next_retry = time.monotonic() + retry_delay
            retry_delay = min(retry_delay * 2, 10.0)
            if last_status != 'offline':
                _emit_status(socketio, 'offline', str(exc))
                last_status = 'offline'
            stop_event.wait(0.2)


def start_imu_thread(socketio, port=None, baud=115200):
    stop_event = threading.Event()
    t = threading.Thread(target=_imu_loop, args=(socketio, port, baud, stop_event), daemon=True)
    t.start()
    return stop_event
