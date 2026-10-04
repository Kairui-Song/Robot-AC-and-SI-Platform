"""Failure accounting and report integrity tests; do not measure scheduler performance."""
import importlib.util
import csv
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS

import pytest

spec = importlib.util.spec_from_file_location('sim_runner', Path(__file__).with_name('run_sim_validation.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_failed_result_stays_failed_in_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: NS(
        stdout=json.dumps({'scenario': 'wall_clock_scheduler', 'passed': False}), stderr='late', returncode=1))
    result = runner.run_case(Path('mock'), tmp_path, 'failed', [], 1)
    assert not result['passed']
    assert (tmp_path / 'failed.stderr').read_text() == 'late'


@pytest.mark.parametrize('stdout,code', [
    ('not json', 0), ('{"passed":true}', 1), ('{"passed":"true"}', 0),
    ('[]', 0), ('{"passed":true,"metric":NaN}', 0),
])
def test_invalid_output_cannot_pass(tmp_path, monkeypatch, stdout, code):
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: NS(stdout=stdout, stderr='', returncode=code))
    result = runner.run_case(Path('mock'), tmp_path, 'bad', [], 1)
    assert not result['passed'] and 'infrastructure_error' in result


def test_timeout_is_recorded_instead_of_aborting_remaining_suite(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['mock'], 1)
    monkeypatch.setattr(runner.subprocess, 'run', timeout)
    result = runner.run_case(Path('mock'), tmp_path, 'timeout', [], 1)
    assert not result['passed']
    assert (tmp_path / 'timeout.json').exists()


def test_empty_suite_is_not_success():
    assert not runner.summarize([])['passed']


def test_infrastructure_failure_is_included_in_overall_count():
    summary = runner.summarize([{'passed': False, 'infrastructure_error': 'missing binary'}])
    assert summary['cases_run'] == 1 and summary['cases_failed'] == 1
    assert not summary['passed']


def raw_fixture(tmp_path):
    path = tmp_path / 'raw.csv'
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['scheduled_us', 'actual_us', 'interval_us', 'wake_lateness_us', 'execution_us'])
        writer.writerows([[10000, 10010, 10010, 10, 1], [20000, 20020, 10010, 20, 2]])
    result = dict(samples=2, wake_lateness_p50_us=10, wake_lateness_p95_us=20,
                  wake_lateness_p99_us=20, wake_lateness_max_us=20,
                  execution_p99_us=2, execution_max_us=2, interval_p99_us=10010)
    return path, result


def test_raw_csv_recomputes_percentiles(tmp_path):
    path, result = raw_fixture(tmp_path)
    runner.audit_csv(path, result)


@pytest.mark.parametrize('key,value', [('samples', 3), ('wake_lateness_p99_us', 1), ('execution_p99_us', .1)])
def test_inconsistent_metrics_are_rejected(tmp_path, key, value):
    path, result = raw_fixture(tmp_path)
    result[key] = value
    with pytest.raises(ValueError):
        runner.audit_csv(path, result)


def test_corrupt_clock_relationship_is_rejected(tmp_path):
    path, result = raw_fixture(tmp_path)
    path.write_text(path.read_text().replace('10010,10,1', '10000,10,1'))
    with pytest.raises(ValueError, match='interval'):
        runner.audit_csv(path, result)


@pytest.mark.parametrize('payload,mode', [
    ({'scenario': 'accelerated_endurance', 'passed': True}, 'endurance'),
    ({'scenario': 'wall_clock_scheduler', 'passed': True}, 'endurance'),
    ({'scenario': 'randomized_fault_recovery', 'passed': True,
      'lifecycle_iterations': 10, 'cases': []}, 'faults'),
    ({'scenario': 'accelerated_endurance', 'passed': True,
      'simulated_seconds': True, 'cycles_completed': 10, 'tracking_max_rad': 0}, 'endurance'),
])
def test_bad_evidence_becomes_failed_case_and_summary_survives(tmp_path, monkeypatch, payload, mode):
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: NS(
        stdout=json.dumps(payload), stderr='', returncode=0))
    result = runner.run_case(Path('mock'), tmp_path, 'bad-schema', ['--mode', mode], 1)
    assert 'infrastructure_error' in result
    assert runner.summarize([result])['cases_failed'] == 1


def test_valid_failed_measurement_keeps_metrics(tmp_path, monkeypatch):
    payload = dict(scenario='accelerated_endurance', passed=False,
                   simulated_seconds=1, cycles_completed=100, tracking_max_rad=.1)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: NS(
        stdout=json.dumps(payload), stderr='', returncode=1))
    result = runner.run_case(Path('mock'), tmp_path, 'measurement-failure', ['--mode', 'endurance'], 1)
    assert 'infrastructure_error' not in result
    assert runner.summarize([result])['max_mock_tracking_error_rad'] == .1
