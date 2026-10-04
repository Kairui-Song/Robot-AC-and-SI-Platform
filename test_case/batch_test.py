from .single_test import run_single_test


def run_all_tests(targets, imu_port=None, serial_port=None, serial_baud=115200):
    """依次运行 targets 列表中的测试，并汇总结果为报告列表。"""
    report = []
    for t in targets:
        r = run_single_test(
            t,
            imu_port=imu_port,
            serial_port=serial_port,
            serial_baud=serial_baud,
        )
        report.append(r)
    # 汇总
    summary = {'total': len(report), 'ok': sum(1 for r in report if r.get('ok')), 'fail': sum(1 for r in report if not r.get('ok'))}
    return {'summary': summary, 'details': report}
