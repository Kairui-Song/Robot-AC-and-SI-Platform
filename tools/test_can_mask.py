"""Isolated CAN mask regression tests; never import a deployed CAN driver."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class CanMaskTests(unittest.TestCase):
    def test_mask_cases_are_isolated(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / 'adapter.py').exists():
            root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location('isolated_adapter', root / 'adapter.py')
        adapter = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            'can_control': types.SimpleNamespace(send_test_pulse=Mock(), listen_feedback=Mock()),
            'imu_reader': types.SimpleNamespace(_parse_line=Mock()),
        }):
            spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(adapter, '__file__', str(Path(directory) / 'adapter.py')), \
                patch.object(adapter.importlib.util, 'find_spec') as find, \
                patch.object(adapter.importlib, 'import_module') as load, \
                patch.dict(os.environ, {'LINGLONG_ENABLE_CAN_MASK': ''}):
            self.assertFalse(adapter._mask_other_can('mock'))
            find.assert_not_called()
            os.environ['LINGLONG_ENABLE_CAN_MASK'] = '1'
            find.return_value = None
            self.assertFalse(adapter._mask_other_can('mock'))
            load.assert_not_called()
            find.return_value = object()
            driver = load.return_value
            self.assertTrue(adapter._mask_other_can('mock'))
            driver.disable_all_except.assert_called_once_with('mock')
            driver.disable_all_except.side_effect = RuntimeError('simulated failure')
            self.assertFalse(adapter._mask_other_can('mock'))
            self.assertIn('simulated failure', (Path(directory) / 'logs/can_mask_debug.log').read_text())
            find.side_effect = ValueError('invalid module spec')
            self.assertFalse(adapter._mask_other_can('mock'))


if __name__ == '__main__':
    unittest.main()
