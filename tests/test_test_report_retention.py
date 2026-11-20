import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('retention', Path(__file__).resolve().parents[1] / 'tools/test_report_retention.py')
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)


class TestReportRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / '.tmp/m111-updates-owned'
        self.runtime.mkdir(parents=True)
        self.log = self.runtime / 'test_example.py.log'
        self.log.write_text('test_ok (Example) ... ok\nRan 1 test in 0.1s\n\nOK\n', encoding='utf-8')
        self.report = self.root / 'evidence/TEST_REPORT.md'
        self.result = {'runtime': str(self.runtime), 'passed': True, 'resourcesStopped': True,
                       'tests': [{'pattern': 'test_example.py', 'exitCode': 0, 'log': str(self.log)}]}

    def finish(self):
        return retention.finalize_run(self.root, self.runtime, 'm111-updates-', self.report, 'Regression', self.result)

    def test_success_writes_only_md_and_removes_owned_runtime(self):
        self.assertTrue(self.finish())
        self.assertFalse(self.runtime.exists())
        self.assertEqual(list(self.report.parent.iterdir()), [self.report])
        self.assertIn('完成：', self.report.read_text(encoding='utf-8'))

    def test_failure_summary_survives_cleanup(self):
        self.log.write_text('FAIL: test_bad (Example)\nAssertionError: expected 2 got 1\nRan 2 tests in 0.1s\n\nFAILED (failures=1, skipped=1)\n', encoding='utf-8')
        self.result['passed'] = False
        self.result['tests'][0]['exitCode'] = 1
        self.assertTrue(self.finish())
        content = self.report.read_text(encoding='utf-8')
        self.assertIn('expected 2 got 1', content)
        self.assertIn('FAIL: test_bad', content)
        self.assertIn('False', content)
        self.assertNotIn('Traceback', content)

    def test_empty_test_suite_not_passed(self):
        self.log.write_text('Ran 0 tests in 0.0s\n\nOK\n', encoding='utf-8')
        self.finish()
        self.assertFalse(self.result['passed'])

    def test_all_skipped_not_passed(self):
        self.log.write_text("test_skip (Example) ... skipped 'requires PG'\nRan 1 test in 0.0s\n\nOK (skipped=1)\n", encoding='utf-8')
        self.finish()
        self.assertFalse(self.result['passed'])
        self.assertIn('requires PG', self.report.read_text(encoding='utf-8'))

    def test_missing_log_not_passed(self):
        self.log.unlink()
        self.finish()
        self.assertFalse(self.result['passed'])

    def test_report_write_failure_keeps_logs(self):
        with patch.object(retention, 'atomic_markdown', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.finish()
        self.assertTrue(self.log.exists())

    def test_unstopped_resources_kept_and_reported(self):
        self.result['resourcesStopped'] = False
        self.assertFalse(self.finish())
        self.assertTrue(self.log.exists())
        self.assertIn('未完成', self.report.read_text(encoding='utf-8'))

    def test_pid_file_keeps_runtime(self):
        (self.runtime / 'pg-data').mkdir()
        (self.runtime / 'pg-data/postmaster.pid').write_text('123')
        self.assertFalse(self.finish())
        self.assertTrue(self.log.exists())

    def test_wrong_parent_or_prefix_rejected(self):
        with self.assertRaises(ValueError):
            retention.check_owned_runtime(self.root, self.root, 'm111-updates-')
        with self.assertRaises(ValueError):
            retention.check_owned_runtime(self.root, self.runtime, 'other-')

    def test_cleanup_failure_preserves_report_and_logs(self):
        with patch.object(retention.shutil, 'rmtree', side_effect=PermissionError('locked')):
            self.assertFalse(self.finish())
        self.assertTrue(self.log.exists())
        self.assertIn('locked', self.report.read_text(encoding='utf-8'))

    def test_temporary_root_reparse_point_rejected(self):
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_file_attributes=0x400, st_mode=0)):
            with self.assertRaises(ValueError):
                retention.check_owned_runtime(self.root, self.runtime, 'm111-updates-')
        self.assertTrue(self.log.exists())

    def test_directory_scan_error_never_deletes(self):
        def broken_walk(*args, **kwargs):
            kwargs['onerror'](PermissionError('cannot inspect'))
        with patch.object(retention.os, 'walk', side_effect=broken_walk):
            self.assertFalse(self.finish())
        self.assertTrue(self.log.exists())

    def test_repeated_run_updates_same_block(self):
        retention.upsert_run(self.report, 'Regression', self.result, {})
        self.result['passed'] = False
        retention.upsert_run(self.report, 'Regression', self.result, {})
        content = self.report.read_text(encoding='utf-8')
        self.assertEqual(content.count('## 运行 '), 1)
        self.assertIn('False', content)

    def test_distinct_runs_preserve_previous_failure(self):
        self.result['passed'] = False
        retention.upsert_run(self.report, 'Regression', self.result, {})
        self.result['runtime'] = str(self.root / '.tmp/m111-updates-second')
        self.result['passed'] = True
        retention.upsert_run(self.report, 'Regression', self.result, {})
        content = self.report.read_text(encoding='utf-8')
        self.assertEqual(content.count('## 运行 '), 2)
        self.assertIn('False', content)
        self.assertIn('True', content)

    def test_redacts_credentials(self):
        output = retention.safe_text('password=hidden postgresql://user:secret@localhost/db token=abcdef')
        self.assertNotIn('hidden', output)
        self.assertNotIn('abcdef', output)
        self.assertNotIn('user:secret', output)

    def test_atomic_replace_failure_keeps_old_report(self):
        self.report.parent.mkdir()
        self.report.write_text('existing', encoding='utf-8')
        with patch.object(retention.os, 'replace', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                retention.atomic_markdown(self.report, 'replacement')
        self.assertEqual(self.report.read_text(encoding='utf-8'), 'existing')
        self.assertEqual(list(self.report.parent.iterdir()), [self.report])


if __name__ == '__main__':
    unittest.main()
