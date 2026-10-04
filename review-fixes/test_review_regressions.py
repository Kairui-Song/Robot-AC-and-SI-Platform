"""No hardware or network: regressions for freshness and complete source comparison."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'ethercat_bridge.py').exists():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import ethercat_bridge as bridge


class Timer:
    def __init__(self, *args): pass
    def start(self): pass
    def cancel(self): pass


class ReviewTests(unittest.TestCase):
    def run_benchmark(self, age, threshold='2', structured=True):
        lines = [json.dumps(dict(event='status', actual_position=123, link_up=True,
                                slave_online=True, working_counter=3))]
        if structured:
            lines.append(json.dumps(dict(event='result', ok=True, status_fresh=True,
                                        actual_position=999)))
        process = type('Process', (), {'stdout': lines, 'wait': lambda self, **kw: 0,
                                      'poll': lambda self: 0})()
        events = []
        with patch.object(bridge, 'load_config', return_value=dict(mode='local', host='', total_timeout=10)), \
                patch.object(bridge, 'build_benchmark_command', return_value=['fake']), \
                patch.object(bridge.time, 'monotonic', side_effect=[10., 10. + age]), \
                patch.dict(os.environ, {'LINGLONG_STATUS_FRESH_SECONDS': threshold}):
            result = bridge.run_controller_benchmark({}, progress=events.append,
                popen_factory=lambda *a, **kw: process, timer_factory=Timer)
        return result, events

    def test_stale_result_cannot_restore_old_telemetry(self):
        for structured in (True, False):
            result, _ = self.run_benchmark(3, structured=structured)
            self.assertFalse(result['status_fresh'])
            for field in ('actual_position', 'link_up', 'slave_online', 'working_counter'):
                self.assertIsNone(result[field])
            self.assertEqual(result['status_samples'][0]['actual_position'], 123)

    def test_fresh_stream_includes_deadline(self):
        result, events = self.run_benchmark(1)
        self.assertTrue(result['status_fresh'])
        self.assertEqual(result['actual_position'], 123)
        status = next(e for e in events if e['stage'] == 'status')
        self.assertTrue(status['status_fresh'])
        self.assertEqual(status['status_fresh_seconds'], 2)

    def test_invalid_thresholds_use_finite_default(self):
        for threshold in ('nan', 'inf', '-1', '0', 'invalid'):
            result, _ = self.run_benchmark(3, threshold)
            self.assertFalse(result['status_fresh'])
            self.assertEqual(result['status_fresh_seconds'], 2)

    def test_comparison_checks_beyond_200_files(self):
        path = ROOT / 'tools/compare_vm_sources.py'
        if not path.exists(): path = ROOT / 'compare_vm_sources.py'
        spec = importlib.util.spec_from_file_location('compare_under_test', path)
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a', Path(directory) / 'b'
            a.mkdir(); b.mkdir()
            for i in range(205):
                (a / f'{i:03}.py').write_text('same')
                (b / f'{i:03}.py').write_text('same')
            with patch.object(sys, 'argv', ['compare', str(a), str(b)]):
                self.assertEqual(compare.main(), 0)
                (b / '204.py').write_text('different')
                self.assertEqual(compare.main(), 1)


if __name__ == '__main__':
    unittest.main()
