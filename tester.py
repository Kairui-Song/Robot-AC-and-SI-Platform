import threading
from test_case.single_test import run_single_test
from peak_driver_bridge import is_peak_target, run_peak_test
from comm_logger import record_test_event

def _run_and_emit(socketio, sid, target, imu_port=None, serial_port=None, serial_baud=115200, channel='usb-can0'):
    record_test_event(target, f'开始执行测试: {target}', '正常')
    socketio.emit('test_progress', {'target': target, 'status': 'started'}, room=sid)
    try:
        if target == 'left_arm':
            result = {
                'target': target,
                'ok': False,
                'reason': 'legacy_motion_disabled',
                'error': '历史左臂运动测试接口已由服务端禁用。',
            }
        elif is_peak_target(target):
            result = run_peak_test(target, channel=channel)
        else:
            result = run_single_test(
                target,
                imu_port=imu_port,
                serial_port=serial_port,
                serial_baud=serial_baud,
            )
        # normalize response
        ok = bool(result.get('ok'))
        output = {'target': target, 'ok': ok, 'info': result.get('info'), 'detail': result}
        summary = result.get('info') if isinstance(result.get('info'), str) else result.get('reason') or '测试完成'
        record_test_event(target, f"{'通过' if ok else '失败'}: {summary}", '正常' if ok else '严重')
        socketio.emit('test_result', output, room=sid)
        try:
            from report_store import add_result
            add_result(output)
        except Exception:
            pass
    except Exception as e:
        record_test_event(target, f'测试异常: {e}', '严重')
        socketio.emit('test_result', {'target': target, 'ok': False, 'reason': 'exception', 'error': str(e)}, room=sid)


def start_test(socketio, sid, target, imu_port=None, serial_port=None, serial_baud=115200, channel='usb-can0'):
    t = threading.Thread(
        target=_run_and_emit,
        args=(socketio, sid, target, imu_port, serial_port, serial_baud, channel),
        daemon=True,
    )
    t.start()
    return t
