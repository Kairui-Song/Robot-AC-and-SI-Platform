import threading
import datetime
from comm_logger import get_entries as get_comm_log_entries_raw

_lock = threading.Lock()
_last_results = []


def _clone_result(result):
    return {
        'target': result.get('target'),
        'ok': bool(result.get('ok')),
        'info': result.get('info'),
        'reason': result.get('reason'),
        'detail': result.get('detail'),
        'returncode': result.get('returncode'),
        'logfile': result.get('logfile'),
        'error': result.get('error'),
        'updated': result.get('updated') or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def add_result(result):
    normalized = _clone_result(result)
    with _lock:
        for idx, existing in enumerate(_last_results):
            if existing.get('target') == normalized.get('target'):
                _last_results[idx] = normalized
                break
        else:
            _last_results.append(normalized)


def get_results():
    with _lock:
        return list(_last_results)


def get_comm_log_entries():
    return get_comm_log_entries_raw()


def get_report_data():
    results = get_results()
    total = len(results)
    ok_count = sum(1 for r in results if r.get('ok'))
    fail_count = total - ok_count
    pass_rate = round(ok_count * 100.0 / total, 1) if total else 0.0

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
    avg_response = f"{round(sum(response_samples) / len(response_samples), 1)}" if response_samples else 'N/A'

    health_rating = 'A+' if fail_count == 0 else 'B' if fail_count == 1 else 'C'
    risk = '低' if fail_count == 0 else '中' if fail_count == 1 else '高'

    recommendations = []
    for r in results:
        if not r.get('ok'):
            reason = r.get('reason') or r.get('error') or '测试失败'
            recommendations.append(f"{r.get('target')}: {reason}")
    if not recommendations:
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
        module_rows.append({
            'module': target,
            'test_item': detail.get('test_item') or ('IMU 采样' if target in ('IMU', 'imu') else 'CAN 通信'),
            'result': '通过' if r.get('ok') else '异常',
            'remark': remark or ('正常' if r.get('ok') else '未通过'),
            'status': 'normal' if r.get('ok') else 'warning',
        })

    return {
        'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'summary': {
            'total': total,
            'ok': ok_count,
            'fail': fail_count,
            'pass_rate': pass_rate,
            'avg_response': avg_response,
            'health_rating': health_rating,
            'risk': risk,
            'recommendation': recommendations[0],
            'faults': fail_count,
        },
        'rows': module_rows,
        'recommendations': recommendations,
    }
