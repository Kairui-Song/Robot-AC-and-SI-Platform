#!/usr/bin/env python3
"""Run reproducible mock-core validation, preserving failures and raw schedule samples."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_result(result, args):
    """Reject incomplete evidence before it can break or inflate the suite summary."""
    schemas = {
        'endurance': ('accelerated_endurance', ('simulated_seconds', 'cycles_completed', 'tracking_max_rad')),
        'faults': ('randomized_fault_recovery', ('lifecycle_iterations',)),
        'scheduler': ('wall_clock_scheduler', ('samples', 'wall_seconds', 'missed_slots',
                      'wake_lateness_p99_us', 'wake_lateness_max_us', 'execution_p99_us')),
    }
    mode = args[args.index('--mode') + 1] if '--mode' in args else None
    if mode not in schemas:
        raise ValueError('missing or unsupported validation mode')
    scenario, fields = schemas[mode]
    if result.get('scenario') != scenario:
        raise ValueError('result scenario does not match requested mode')

    def numbers(record, keys):
        for key in keys:
            value = record[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'invalid metric: {key}')

    numbers(result, fields)
    if mode == 'faults':
        cases = result['cases']
        if not isinstance(cases, list) or len(cases) != 9:
            raise ValueError('expected nine fault classes')
        for case in cases:
            numbers(case, ('injected', 'detected', 'latch_verified', 'recovery_verified'))
    if mode == 'scheduler' and '--csv' not in args:
        raise ValueError('scheduler evidence requires raw CSV')


def audit_csv(path, result):
    """Independently recompute percentiles and time relationships from raw samples."""
    with Path(path).open(encoding='utf-8', newline='') as stream:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if not rows or len(rows) != result['samples']:
        raise ValueError('raw CSV sample count mismatch')
    previous_actual = previous_schedule = 0.
    for row in rows:
        if not all(math.isfinite(v) and v >= 0 for v in row.values()):
            raise ValueError('invalid raw CSV number')
        if row['scheduled_us'] <= previous_schedule or row['actual_us'] <= previous_actual:
            raise ValueError('non-monotonic raw CSV times')
        if abs(row['actual_us'] - previous_actual - row['interval_us']) > .001:
            raise ValueError('raw interval inconsistent with clock samples')
        if abs(max(0., row['actual_us'] - row['scheduled_us']) - row['wake_lateness_us']) > .001:
            raise ValueError('raw wake lateness inconsistent with scheduled time')
        previous_actual, previous_schedule = row['actual_us'], row['scheduled_us']
    for column, key, fraction in (
        ('wake_lateness_us', 'wake_lateness_p50_us', .5),
        ('wake_lateness_us', 'wake_lateness_p95_us', .95),
        ('wake_lateness_us', 'wake_lateness_p99_us', .99),
        ('wake_lateness_us', 'wake_lateness_max_us', 1.),
        ('execution_us', 'execution_p99_us', .99),
        ('execution_us', 'execution_max_us', 1.),
        ('interval_us', 'interval_p99_us', .99)):
        values = sorted(row[column] for row in rows)
        expected = values[math.ceil(fraction * len(values)) - 1]
        if not math.isclose(expected, result[key], rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(f'raw CSV disagrees with {key}')


def run_case(binary, directory, name, args, timeout):
    command = [str(binary), *args]
    started = time.monotonic()
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        (directory / f'{name}.stdout').write_text(process.stdout, encoding='utf-8')
        (directory / f'{name}.stderr').write_text(process.stderr, encoding='utf-8')
        result = json.loads(process.stdout)
        if not isinstance(result, dict) or not isinstance(result.get('passed'), bool) or (process.returncode == 0) != result['passed']:
            raise ValueError('result/exit-status disagreement')
        # Reject non-standard NaN/Infinity output before saving it as evidence.
        json.dumps(result, allow_nan=False)
        validate_result(result, args)
        if result.get('scenario') == 'wall_clock_scheduler' and '--csv' in args:
            audit_csv(args[args.index('--csv') + 1], result)
            result['raw_csv_verified'] = True
        result.update(case=name, exit_code=process.returncode, command=command)
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError) as exc:
        result = {'case': name, 'passed': False, 'infrastructure_error': str(exc), 'command': command}
        if isinstance(exc, subprocess.TimeoutExpired):
            for extension, value in (('stdout', exc.stdout), ('stderr', exc.stderr)):
                text = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
                (directory / f'{name}.{extension}').write_text(text, encoding='utf-8')
    result['runner_wall_sec'] = time.monotonic() - started
    (directory / f'{name}.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'{name}: {"PASS" if result["passed"] else "FAIL"}', flush=True)
    return result


def summarize(results):
    endurance = [r for r in results if r.get('scenario') == 'accelerated_endurance']
    faults = [r for r in results if r.get('scenario') == 'randomized_fault_recovery']
    schedule = [r for r in results if r.get('scenario') == 'wall_clock_scheduler']
    return {
        'passed': bool(results) and all(r['passed'] for r in results),
        'cases_run': len(results), 'cases_failed': sum(not r['passed'] for r in results),
        'accelerated_simulated_hours': sum(r['simulated_seconds'] for r in endurance) / 3600,
        'accelerated_cycles': sum(r['cycles_completed'] for r in endurance),
        'max_mock_tracking_error_rad': max((r['tracking_max_rad'] for r in endurance), default=None),
        'faults_injected': sum(c['injected'] for r in faults for c in r['cases']),
        'faults_detected': sum(c['detected'] for r in faults for c in r['cases']),
        'fault_latches_verified': sum(c['latch_verified'] for r in faults for c in r['cases']),
        'explicit_recoveries_verified': sum(c['recovery_verified'] for r in faults for c in r['cases']),
        'lifecycle_iterations': sum(r['lifecycle_iterations'] for r in faults),
        'scheduler_samples': sum(r['samples'] for r in schedule),
        'scheduler_wall_seconds': sum(r['wall_seconds'] for r in schedule),
        'scheduler_failures': sum(not r['passed'] for r in schedule),
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sim-hours', type=int, default=24)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--trials', type=int, default=200)
    parser.add_argument('--workers', type=int, default=2)
    options = parser.parse_args()
    if not (1 <= options.sim_hours <= 240 and 1 <= options.repeats <= 10 and
            1 <= options.seconds <= 300 and 1 <= options.trials <= 10000 and 1 <= options.workers <= 8):
        parser.error('test dimensions exceed supported bounds')
    binary = options.binary.resolve(strict=True)
    directory = options.output or ROOT / 'verification' / datetime.now(timezone.utc).strftime('simulation-%Y%m%dT%H%M%S-%fZ')
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / 'src/linglong_control/include/linglong_control/sim_core.hpp',
               ROOT / 'src/linglong_control/test/sim_validation.cpp', Path(__file__).resolve(),
               ROOT / 'src/linglong_control/CMakeLists.txt']
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
                'python': platform.python_version(), 'binary_sha256': sha256(binary),
                'source_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in sources},
                'parameters': {k: str(v) if isinstance(v, Path) else v for k, v in vars(options).items()},
                'limits': 'No ROS/DDS/EtherCAT, no hard real-time guarantee; virtual hours are not wall-clock endurance.',
                'recovery_definition': 'Seven input fault classes reset the same instance; two persistent injection classes recreate a fault-free configuration. Each runs 100 healthy cycles. Not robot MTTR.',
                'build_info': json.loads(subprocess.check_output([str(binary), '--mode', 'build_info'], text=True, timeout=5))}
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    results = []
    results.append(run_case(binary, directory, 'endurance',
                            ['--mode', 'endurance', '--cycles', str(options.sim_hours * 360000)], 180))
    for repeat in range(options.repeats):
        results.append(run_case(binary, directory, f'faults-{repeat + 1}',
            ['--mode', 'faults', '--trials', str(options.trials), '--seed', str(20260925 + repeat)], 60))
        # Alternate order to reduce systematic warm-up/order bias.
        loads = (0, options.workers) if repeat % 2 == 0 else (options.workers, 0)
        for workers in loads:
            name = f'scheduler-{repeat + 1}-load-{workers}'
            results.append(run_case(binary, directory, name,
                ['--mode', 'scheduler', '--seconds', str(options.seconds), '--workers', str(workers),
                 '--csv', str(directory / f'{name}.csv')], options.seconds + 15))
    summary = summarize(results)
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# Simulation validation results', '',
             '**Scope:** mock control core; no ROS, DDS or EtherCAT. Virtual endurance and wall-clock scheduling are separate.', '',
             f'Overall: {"PASS" if summary["passed"] else "FAIL"}; failed cases: {summary["cases_failed"]}/{len(results)}.',
             f'Accelerated simulation: {summary["accelerated_simulated_hours"]:.3f} hours, {summary["accelerated_cycles"]} cycles.',
             f'Fault injection: {summary["faults_detected"]}/{summary["faults_injected"]} detected; '
             f'{summary["fault_latches_verified"]} latches; {summary["explicit_recoveries_verified"]} explicit mock recoveries.',
             f'Controller lifecycle iterations: {summary["lifecycle_iterations"]}.',
             'Seven fault classes recover on the same instance; two recreate a fault-free configuration. Neither measures physical repair or MTTR.', '',
             'Thresholds were set before execution. A failing scheduler case is retained; no thresholds are relaxed after observing results.', '']
    for result in results:
        lines.append(f'- {result["case"]}: {"PASS" if result["passed"] else "FAIL"}')
        if result.get('scenario') == 'wall_clock_scheduler':
            lines.append(f'  Samples={result["samples"]}; p99 wake lateness={result["wake_lateness_p99_us"]:.3f} us; '
                         f'max wake lateness={result["wake_lateness_max_us"]:.3f} us; '
                         f'p99 core+target execution={result["execution_p99_us"]:.3f} us; '
                         f'missed slots={result["missed_slots"]}.')
    (directory / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Results: {directory}', flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
