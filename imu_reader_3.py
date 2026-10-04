import threading
import time
import json
import os

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
    # Lazy import of serial to avoid import error if not installed
    try:
        import serial
    except Exception:
        serial = None

    if port and serial:
        try:
            ser = serial.Serial(port, baud, timeout=1)
        except Exception:
            ser = None
    else:
        ser = None

    while not stop_event.is_set():
        try:
            if ser and ser.in_waiting:
                raw = ser.readline().decode(errors='ignore')
                data = _parse_line(raw)
                socketio.emit('imu_data', data)
            else:
                # if no serial, emit simulated data periodically
                simulated = {
                    'timestamp': time.time(),
                    'yaw': (time.time() * 30) % 360,
                    'pitch': (time.time() * 10) % 90,
                    'roll': (time.time() * 5) % 45
                }
                socketio.emit('imu_data', simulated)
                time.sleep(0.2)
        except Exception:
            time.sleep(0.5)


def start_imu_thread(socketio, port=None, baud=115200):
    stop_event = threading.Event()
    t = threading.Thread(target=_imu_loop, args=(socketio, port, baud, stop_event), daemon=True)
    t.start()
    return stop_event
