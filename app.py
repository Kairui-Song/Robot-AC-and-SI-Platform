from flask import Flask, render_template, send_file, abort, request, jsonify
import os
from pathlib import Path
from flask_socketio import SocketIO
from comm_logger import get_entries, get_log_title, get_alerts, build_pdf, record_test_event, register_socketio
from report_store import add_result, get_report_data, get_comm_log_entries, get_latest_result

app = Flask(__name__)
from ros_control_bridge import register as register_ros_control
register_ros_control(app)

# ========== 修改2：配置SocketIO，增加超时和心跳设置 ==========
socketio = SocketIO(
    app, 
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e6,
    cors_allowed_origins=(
        [item.strip() for item in os.environ["LINGLONG_ALLOWED_ORIGINS"].split(",") if item.strip()]
        if os.environ.get("LINGLONG_ALLOWED_ORIGINS") else None
    )
)
register_socketio(socketio)


def _controller_info_log_lines(info):
    uptime = int(info.get('uptime_seconds') or 0)
    return [
        f"处理器: {info.get('cpu_model', '—')} · {info.get('cpu_cores', '—')} 核",
        f"内存: {info.get('memory_available_mb', '—')} / {info.get('memory_total_mb', '—')} MB 可用",
        f"系统负载: {info.get('load_1m', '—')} / {info.get('load_5m', '—')} / {info.get('load_15m', '—')}",
        f"系统运行时间: {uptime} s" if uptime else "系统运行时间: —",
        f"实时内核: {'已启用 PREEMPT_RT' if info.get('realtime_kernel') else '未检测到 PREEMPT_RT'}",
        f"Test Client 调度: {info.get('scheduler', '—')} · 优先级 {info.get('scheduler_priority', '—')}",
        f"Test Client 进程: PID {info.get('pid', '—')}",
    ]


@socketio.on('run_motor_preflight')
def handle_motor_preflight(payload):
    sid = request.sid
    from ros_control_bridge import configured
    if configured():
        socketio.emit('motor_preflight_result', {'ok': False, 'motion_allowed': False,
            'error': 'ROS 控制模式已配置，请使用 ROS 控制页面；直连预检已停用。'}, room=sid)
        return
    profile_id = (payload or {}).get('profile_id')
    controller_profile = (payload or {}).get('controller_profile', 'auto')
    if controller_profile not in {'auto', 'ep_h507a1'}:
        controller_profile = 'auto'

    def _runner():
        from ethercat_bridge import run_motor_preflight

        def progress(data):
            socketio.emit('motor_preflight_progress', data, room=sid)

        try:
            result = run_motor_preflight(
                profile_id,
                controller_profile=controller_profile,
                progress=progress,
                test_id="ethercat-master-0",
            )
        except Exception as exc:
            result = {'target': 'single_motor_preflight', 'ok': False, 'error': str(exc), 'motion_allowed': False}
        record_test_event(
            'single_motor_preflight',
            f"单电机只读预检{'通过' if result.get('ok') else '失败'}: {profile_id}",
            '正常' if result.get('ok') else '严重',
        )
        add_result(result)
        socketio.emit('motor_preflight_result', result, room=sid)

    socketio.start_background_task(_runner)

# ========== 修改3：添加心跳检测 ==========
@socketio.on('ping')
def handle_ping():
    return 'pong'

@socketio.on('run_test')
def handle_run_test(payload):
    socketio.emit('test_result', {
        'target': (payload or {}).get('target', 'legacy_test'), 'ok': False,
        'reason': 'legacy_motion_disabled',
        'error': '历史运动测试接口已由服务端禁用。',
    }, room=request.sid)


@socketio.on('stop_test')
def handle_stop_test(payload):
    payload = payload or {}
    target = payload.get('target')
    from ros_control_bridge import configured, call
    if configured():
        admin_token = os.environ.get('LINGLONG_ADMIN_TOKEN')
        if admin_token and payload.get('admin_token') != admin_token:
            socketio.emit('test_progress', {'target': 'ros_control', 'status': 'rejected',
                'error': '需要管理员令牌，请在 ROS 控制页填写后停用。'}, room=request.sid)
            return
        sid = request.sid
        def stop_ros():
            result, _ = call('disable', {})
            socketio.emit('test_progress', {'target': 'ros_control',
                'status': 'stopping' if result.get('ok') else 'rejected', 'result': result}, room=sid)
        socketio.start_background_task(stop_ros)
        return
    stopped = False
    if target == 'single_motor_preflight':
        from ethercat_bridge import stop_active_test
        stopped = stop_active_test("ethercat-master-0")
    elif target == 'left_arm':
        from ethercat_bridge import stop_active_test
        stopped = stop_active_test(request.sid)
    elif target == 'controller_benchmark':
        from ethercat_bridge import stop_active_test
        stopped = stop_active_test("ethercat-master-0")
    socketio.emit(
        'test_progress',
        {'target': target, 'status': 'stopping' if stopped else 'not_running'},
        room=request.sid,
    )


@socketio.on('run_controller_benchmark')
def handle_controller_benchmark(payload):
    sid = request.sid
    from ros_control_bridge import configured
    if configured():
        socketio.emit('benchmark_result', {'ok': False, 'motion_allowed': False,
            'error': 'ROS 控制模式已配置，直连运动基准已停用，避免争用 EtherCAT 主站。'}, room=sid)
        return
    options = payload or {}

    def _runner():
        from ethercat_bridge import run_controller_benchmark
        controller_info_logged = False

        def progress(data):
            nonlocal controller_info_logged
            if data.get('stage') == 'controller_info' and not controller_info_logged:
                controller_info_logged = True
                for line in _controller_info_log_lines(data):
                    record_test_event('controller_benchmark', line, '正常')
            socketio.emit('benchmark_progress', data, room=sid)
            socketio.emit('benchmark_stream', data, room=sid)

        try:
            result = run_controller_benchmark(
                options,
                progress=progress,
                test_id="ethercat-master-0",
            )
        except Exception as exc:
            result = {'target': 'controller_benchmark', 'ok': False, 'error': str(exc), 'motion_allowed': False}
        if result.get('controller_info') and not controller_info_logged:
            for line in _controller_info_log_lines(result['controller_info']):
                record_test_event('controller_benchmark', line, '正常')
        record_test_event(
            "controller_benchmark",
            f"JE 主控测试{'通过' if result.get('ok') else '失败'}: "
            f"status={result.get('statusword_hex') or 'n/a'}",
            "正常" if result.get("ok") else "严重",
        )
        add_result(result)
        socketio.emit('benchmark_result', result, room=sid)
        socketio.emit('benchmark_stream', {'stage': 'result', **result}, room=sid)

    socketio.start_background_task(_runner)


@socketio.on('run_batch')
def handle_run_batch(payload):
    socketio.emit('batch_report', {
        'ok': False, 'reason': 'legacy_motion_disabled',
        'error': '历史批量运动测试接口已由服务端禁用。',
    }, room=request.sid)

# ========== 原有路由保持不变 ==========
@app.route('/')
def index():
    from benchmark_store import get_latest
    return render_template(
        'index.html', page='overview', benchmark=get_latest(),
        controller_test=get_latest_result('single_motor_preflight'),
    )

@app.route('/single-motor-test')
def single_motor_test():
    from motor_profiles import public_profiles
    return render_template('single_motor_test.html', page='single-motor-test', motor_profiles=public_profiles())


@app.route('/controller-benchmark')
def controller_benchmark():
    from benchmark_store import get_latest
    return render_template(
        'controller_benchmark.html',
        page='controller-benchmark',
        benchmark=get_latest(),
    )

@app.route('/comm-log')
def comm_log():
    return render_template(
        'comm_log.html',
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
    from benchmark_store import get_latest
    return render_template(
        'test_report.html',
        page='test-report',
        report=get_report_data(),
        comm_entries=get_comm_log_entries(),
        benchmark=get_latest(),
    )

@app.route('/system-config')
def system_config():
    from ethercat_config import load_config
    return render_template(
        'system_config.html',
        page='system-config',
        ethercat_config=load_config(),
    )


@app.route('/api/ethercat-config', methods=['GET', 'POST'])
def ethercat_config_api():
    from ethercat_config import load_config, save_config
    if request.method == 'GET':
        return jsonify({'ok': True, 'config': load_config()})
    admin_token = os.environ.get('LINGLONG_ADMIN_TOKEN')
    if admin_token and request.headers.get('X-Linglong-Admin-Token') != admin_token:
        return jsonify({'ok': False, 'error': '未授权的配置修改请求'}), 403
    try:
        saved = save_config(request.get_json(silent=True) or {})
        return jsonify({'ok': True, 'config': saved})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

@app.route('/download-log/<path:filename>')
def download_log(filename):
    logs_dir = (Path(__file__).resolve().parent / 'logs').resolve()
    safe_path = (logs_dir / filename).resolve()
    if logs_dir not in safe_path.parents or not safe_path.is_file():
        return abort(404)
    return send_file(safe_path, as_attachment=True, download_name=safe_path.name)


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

    socketio.run(
        app,
        host=os.environ.get('LINGLONG_HOST', '127.0.0.1'),
        port=int(os.environ.get('LINGLONG_PORT', '5000')),
        debug=False,
        allow_unsafe_werkzeug=True,
    )
