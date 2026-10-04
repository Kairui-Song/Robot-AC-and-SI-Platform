import threading
import subprocess
import sys
import os
import datetime
from comm_logger import record_test_event

LOG_DIR = os.path.join(os.getcwd(), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)


def _run_and_stream(socketio, sid, target):
    """Run pytest for a single target test file and stream stdout/stderr via socketio."""
    record_test_event(target, f'Running pytest for {target}...', '正常')
    socketio.emit('pytest_output', {'target': target, 'line': f'Running pytest for {target}...'}, room=sid)
    # map target to test file
    test_file = os.path.join(os.getcwd(), 'tests', f'test_{target}.py')
    if not os.path.exists(test_file):
        record_test_event(target, f'test file not found: {test_file}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': 'test file not found', 'path': test_file}, room=sid)
        return

    # Use same Python interpreter to run pytest
    cmd = [sys.executable, '-m', 'pytest', '-q', test_file]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        record_test_event(target, f'failed to start pytest: {e}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': f'failed to start pytest: {e}'}, room=sid)
        return
    # stream lines and save to log
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    logfile = os.path.join(LOG_DIR, f'{target}_{ts}.log')
    try:
        with open(logfile, 'w', encoding='utf-8') as f:
            for line in proc.stdout:
                txt = line.rstrip()
                f.write(txt + "\n")
                f.flush()
                level = '严重' if any(marker in txt.upper() for marker in ('FAILED', 'ERROR', 'CRITICAL')) else '正常'
                record_test_event(target, txt, level)
                socketio.emit('pytest_output', {'target': target, 'line': txt}, room=sid)

        proc.wait()
        code = proc.returncode
        ok = (code == 0)
        result = {'target': target, 'ok': ok, 'returncode': code, 'logfile': os.path.basename(logfile)}
        record_test_event(target, f'pytest finished with returncode={code}', '正常' if ok else '严重')
        socketio.emit('pytest_result', result, room=sid)
        try:
            from report_store import add_result
            add_result(result)
        except Exception:
            pass
    except Exception as e:
        record_test_event(target, f'pytest execution error: {e}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': str(e)}, room=sid)


def run_pytest_for_target(socketio, sid, target):
    t = threading.Thread(target=_run_and_stream, args=(socketio, sid, target), daemon=True)
    t.start()
    return t


def run_pytest_blocking(socketio, sid, target):
    """Run pytest for target, stream output, and return result dict."""
    record_test_event(target, f'Running pytest for {target}...', '正常')
    socketio.emit('pytest_output', {'target': target, 'line': f'Running pytest for {target}...'}, room=sid)
    test_file = os.path.join(os.getcwd(), 'tests', f'test_{target}.py')
    if not os.path.exists(test_file):
        record_test_event(target, f'test file not found: {test_file}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': 'test file not found', 'path': test_file}, room=sid)
        return {'target': target, 'ok': False, 'returncode': 1}

    cmd = [sys.executable, '-m', 'pytest', '-q', test_file]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        record_test_event(target, f'failed to start pytest: {e}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': f'failed to start pytest: {e}'}, room=sid)
        return {'target': target, 'ok': False, 'returncode': 1}

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    logfile = os.path.join(LOG_DIR, f'{target}_{ts}.log')
    try:
        with open(logfile, 'w', encoding='utf-8') as f:
            for line in proc.stdout:
                txt = line.rstrip()
                f.write(txt + "\n")
                f.flush()
                level = '严重' if any(marker in txt.upper() for marker in ('FAILED', 'ERROR', 'CRITICAL')) else '正常'
                record_test_event(target, txt, level)
                socketio.emit('pytest_output', {'target': target, 'line': txt}, room=sid)

        proc.wait()
        code = proc.returncode
        ok = (code == 0)
        result = {'target': target, 'ok': ok, 'returncode': code, 'logfile': os.path.basename(logfile)}
        record_test_event(target, f'pytest finished with returncode={code}', '正常' if ok else '严重')
        socketio.emit('pytest_result', result, room=sid)
        try:
            from report_store import add_result
            add_result(result)
        except Exception:
            pass
        return result
    except Exception as e:
        record_test_event(target, f'pytest execution error: {e}', '严重')
        socketio.emit('pytest_result', {'target': target, 'ok': False, 'error': str(e)}, room=sid)
        return {'target': target, 'ok': False, 'returncode': 1}
