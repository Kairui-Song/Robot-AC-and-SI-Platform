import threading
import datetime
import json
import sqlite3
from pathlib import Path
from comm_logger import get_entries as get_comm_log_entries_raw

_lock = threading.Lock()
_db_path = Path(__file__).resolve().parent / 'logs' / 'test_results.db'


def _connect():
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_db_path)
    connection.execute('''CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL,
        ok INTEGER NOT NULL,
        updated TEXT NOT NULL,
        payload TEXT NOT NULL
    )''')
    connection.execute(
        'CREATE INDEX IF NOT EXISTS idx_test_results_target_id ON test_results(target, id DESC)'
    )
    return connection


def _clone_result(result):
    normalized = {
        'target': result.get('target'),
        'ok': bool(result.get('ok')),
        'info': result.get('info'),
        'reason': result.get('reason'),
        'detail': result.get('detail'),
        'returncode': result.get('returncode'),
        'logfile': result.get('logfile'),
        'error': result.get('error'),
        'controller_info': result.get('controller_info'),
        'inventory': result.get('inventory'),
        'transport': result.get('transport'),
        'levels': result.get('levels'),
        'assessment': result.get('assessment'),
        'profile_id': result.get('profile_id'),
        'expected_slave_count': result.get('expected_slave_count'),
        'identity_match': result.get('identity_match'),
        'updated': result.get('updated') or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    return normalized


def add_result(result):
    normalized = _clone_result(result)
    with _lock:
        with _connect() as connection:
            connection.execute(
                'INSERT INTO test_results(target, ok, updated, payload) VALUES (?, ?, ?, ?)',
                (normalized.get('target') or 'unknown', int(normalized['ok']), normalized['updated'],
                 json.dumps(normalized, ensure_ascii=False)),
            )


def get_results():
    with _lock:
        with _connect() as connection:
            rows = connection.execute('''SELECT payload FROM test_results r
                WHERE id = (SELECT MAX(id) FROM test_results WHERE target = r.target)
                ORDER BY id''').fetchall()
    return [json.loads(row[0]) for row in rows]


def get_latest_result(target):
    with _lock:
        with _connect() as connection:
            row = connection.execute(
                'SELECT payload FROM test_results WHERE target=? ORDER BY id DESC LIMIT 1', (target,)
            ).fetchone()
    return json.loads(row[0]) if row else None


def get_comm_log_entries():
    return get_comm_log_entries_raw()


def get_report_data():
    results = get_results()
    total = len(results)
    ok_count = sum(1 for r in results if r.get('ok'))
    fail_count = total - ok_count
    pass_rate = round(ok_count * 100.0 / total, 1) if total else None

    # Attempt to derive an average response metric from available info fields.
    response_samples = []
    for r in results:
        info = r.get('info')
        if isinstance(info, dict):
            if 'latency_ms' in info:
                response_samples.append(info['latency_ms'])
            elif 'duration' in info:
                response_samples.append(round(info['duration'] * 1000, 1))
            elif 'fps' in info and info['fps']:
                response_samples.append(round(1000.0 / info['fps'], 1))
    avg_response = f"{round(sum(response_samples) / len(response_samples), 1)}" if response_samples else '—'

    assessment = '未测试' if not total else '通过' if fail_count == 0 else '不通过'
    risk = '未评定' if not total else '需复核' if fail_count == 0 else '存在异常'

    recommendations = []
    for r in results:
        if not r.get('ok'):
            reason = r.get('reason') or r.get('error') or '测试失败'
            recommendations.append(f"{r.get('target')}: {reason}")
    if not total:
        recommendations.append('暂无有效测试数据，请先执行主控测试。')
    elif not recommendations:
        recommendations.append('当前测试通过，无需额外操作。')

    module_rows = []
    for r in results:
        target = r.get('target') or 'unknown'
        detail = r.get('detail') or {}
        info = r.get('info')
        if isinstance(info, dict):
            remark = ', '.join(f"{k}:{v}" for k, v in info.items())
        else:
            remark = str(info or r.get('error') or r.get('reason') or '')
        labels = {
            'single_motor_preflight': ('主控通信链路', '通信与实时控制预检'),
            'controller_benchmark': ('主控闭环控制', '闭环性能基准'),
        }
        module_label, default_item = labels.get(target, (target, '通用功能测试'))
        module_rows.append({
            'module': module_label,
            'test_item': detail.get('test_item') or default_item,
            'result': '通过' if r.get('ok') else '异常',
            'remark': remark or ('正常' if r.get('ok') else '未通过'),
            'status': 'normal' if r.get('ok') else 'warning',
        })

    return {
        'updated': max((r.get('updated') for r in results), default='—'),
        'summary': {
            'total': total,
            'ok': ok_count,
            'fail': fail_count,
            'pass_rate': pass_rate,
            'avg_response': avg_response,
            'health_rating': assessment,
            'risk': risk,
            'recommendation': recommendations[0],
            'faults': fail_count,
        },
        'rows': module_rows,
        'recommendations': recommendations,
    }
