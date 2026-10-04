from flask import Flask, render_template, send_file, abort, request
import os
from flask_socketio import SocketIO
import threading
from comm_logger import get_entries, get_log_title, get_alerts, build_pdf, record_test_event, register_socketio
from report_store import get_report_data, get_comm_log_entries

# ========== 修改1：添加eventlet并启用monkey_patch ==========
import eventlet
eventlet.monkey_patch()

app = Flask(__name__)

# ========== 修改2：配置SocketIO，增加超时和心跳设置 ==========
socketio = SocketIO(
    app, 
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e6,
    cors_allowed_origins="*"
)
register_socketio(socketio)

# ========== 修改3：添加心跳检测 ==========
@socketio.on('ping')
def handle_ping():
    return 'pong'

# ========== 修改4：使用eventlet.spawn替代threading ==========
from eventlet import spawn, sleep

@socketio.on('run_test')
def handle_run_test(payload):
    payload = payload or {}
    sid = request.sid
    target = payload.get('target')
    channel = payload.get('channel') or 'usb-can0'
    imu_port = payload.get('imu_port')
    serial_port = payload.get('serial_port')
    serial_baud = payload.get('serial_baud', 115200)
    use_pytest = bool(payload.get('use_pytest'))
    
    def _run_test():
        try:
            if use_pytest:
                from pytest_runner import run_pytest_for_target
                run_pytest_for_target(socketio, sid, target)
            else:
                from tester import start_test
                start_test(
                    socketio,
                    sid,
                    target,
                    imu_port=imu_port,
                    serial_port=serial_port,
                    serial_baud=serial_baud,
                    channel=channel,
                )
        except Exception as e:
            record_test_event(target, f'测试启动失败: {e}', '严重')
            socketio.emit('test_result', {'target': target, 'ok': False, 'reason': 'internal_error', 'error': str(e)}, room=sid)
    
    # 使用eventlet的spawn替代threading.Thread
    spawn(_run_test)


@socketio.on('run_batch')
def handle_run_batch(payload):
    payload = payload or {}
    sid = request.sid
    # default targets order
    default_targets = ['left_leg', 'right_leg', 'left_arm', 'right_arm', 'head', 'IMU']
    targets = payload.get('targets') or default_targets
    imu_port = payload.get('imu_port')
    serial_port = payload.get('serial_port')
    serial_baud = payload.get('serial_baud', 115200)
    use_pytest = bool(payload.get('use_pytest'))

    def _runner():
        results = []
        if use_pytest:
            from pytest_runner import run_pytest_blocking
            for t in targets:
                socketio.emit('test_progress', {'target': t, 'status': 'started'}, room=sid)
                sleep(0)  # 让出控制权，避免阻塞
                try:
                    r = run_pytest_blocking(socketio, sid, t)
                    results.append(r)
                except Exception as e:
                    socketio.emit('test_result', {'target': t, 'ok': False, 'reason': 'exception', 'error': str(e)}, room=sid)
                sleep(0)  # 每次循环让出控制权
        else:
            from test_case.single_test import run_single_test
            for t in targets:
                socketio.emit('test_progress', {'target': t, 'status': 'started'}, room=sid)
                sleep(0)  # 让出控制权，避免阻塞
                try:
                    r = run_single_test(
                        t,
                        imu_port=imu_port,
                        serial_port=serial_port,
                        serial_baud=serial_baud,
                    )
                    results.append(r)
                    ok = bool(r.get('ok'))
                    socketio.emit('test_result', {'target': t, 'ok': ok, 'info': r.get('info'), 'detail': r}, room=sid)
                except Exception as e:
                    record_test_event(t, f'批量测试异常: {e}', '严重')
                    socketio.emit('test_result', {'target': t, 'ok': False, 'reason': 'exception', 'error': str(e)}, room=sid)
                sleep(0)  # 每次循环让出控制权

        # summary
        summary = {'total': len(results), 'ok': sum(1 for r in results if r.get('ok')), 'fail': sum(1 for r in results if not r.get('ok'))}
        record_test_event('batch', f'批量测试完成: 总计 {summary["total"]} 项，成功 {summary["ok"]} 项，失败 {summary["fail"]} 项', '正常' if summary['fail'] == 0 else '严重')
        socketio.emit('batch_report', {'summary': summary, 'details': results}, room=sid)

    # 使用eventlet的spawn替代threading.Thread
    spawn(_runner)

# ========== 原有路由保持不变 ==========
@app.route('/')
def index():
    return render_template('index_3.html', page='overview')

@app.route('/single-motor-test')
def single_motor_test():
    return render_template('single_motor_test_3.html', page='single-motor-test')

@app.route('/comm-log')
def comm_log():
    return render_template(
        'comm_log_3.html',
        page='comm-log',
        comm_title=get_log_title(),
        comm_entries=get_entries(),
        comm_alerts=get_alerts(),
    )

@app.route('/comm-log/export-pdf')
def export_comm_log_pdf():
    title = get_log_title()
    entries = get_entries()
    filepath = build_pdf(title, entries)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath), mimetype='application/pdf')

@app.route('/test-report')
def test_report():
    return render_template(
        'test_report_3.html',
        page='test-report',
        report=get_report_data(),
        comm_entries=get_comm_log_entries(),
    )

@app.route('/system-config')
def system_config():
    return render_template('system_config_3.html', page='system-config')

@app.route('/download-log/<path:filename>')
def download_log(filename):
    logs_dir = os.path.join(os.getcwd(), 'logs')
    # security: prevent path traversal
    safe_path = os.path.normpath(os.path.join(logs_dir, filename))
    if not safe_path.startswith(os.path.normpath(logs_dir)) or not os.path.exists(safe_path):
        return abort(404)
    return send_file(safe_path, as_attachment=True, download_name=os.path.basename(safe_path))


if __name__ == '__main__':
    # try to start IMU reader background thread if available
    try:
        from imu_reader import start_imu_thread
        imu_port = os.environ.get('IMU_PORT')  # e.g. COM3 or /dev/ttyUSB0
        imu_baud = int(os.environ.get('IMU_BAUD', '115200'))
        if imu_port:  # 只有设置了端口才启动
            start_imu_thread(socketio, port=imu_port, baud=imu_baud)
    except Exception:
        pass

    socketio.run(app, debug=False)
