"""Safety guards for the real local acceptance tool; no app/database imports."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

_source = Path(__file__).resolve().parents[1] / 'tools/accept_m34_local.py'
_spec = importlib.util.spec_from_file_location('m34_acceptance_tool', _source)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class AcceptanceSafetyTests(unittest.TestCase):
    def test_environment_does_not_inherit_database_credentials_or_feature_switches(self):
        with patch.dict(runner.os.environ, {'PATH': 'test', 'DATABASE_URL': 'private',
                        'MINIO_SECRET_KEY': 'private', 'MODEL_SIGNING_PRIVATE_KEY_PATH': 'private',
                        'APP_UPDATES_ENABLED': 'true', 'HTTP_PROXY': 'private'}, clear=True):
            self.assertEqual({'PATH': 'test'}, runner.clean_environment())

    def test_external_connect_is_denied(self):
        with self.assertRaises(RuntimeError):
            runner.loopback_only('socket.connect', (object(), ('192.0.2.1', 5432)))

    def test_external_dns_is_denied(self):
        with self.assertRaises(RuntimeError):
            runner.loopback_only('socket.getaddrinfo', ('example.invalid', 443))

    def test_loopback_connect_is_allowed(self):
        for host in ('127.0.0.1', '::1', 'localhost'):
            runner.loopback_only('socket.connect', (object(), (host, 10000)))
            runner.loopback_only('socket.getaddrinfo', (host, 10000))

    def test_unrelated_audit_events_are_ignored(self):
        runner.loopback_only('open', ('test', 'r', 0))

    def test_workspace_root_is_not_an_owned_runtime(self):
        with self.assertRaises(ValueError):
            runner.owned_work(runner.ROOT)

    def test_other_temporary_task_directory_is_rejected(self):
        with self.assertRaises(ValueError):
            runner.owned_work(runner.ROOT / '.tmp' / 'unrelated-task')

    def test_exact_task_runtime_path_is_accepted(self):
        path = runner.ROOT / '.tmp' / 'm34-real-safety-path-only'
        self.assertEqual(path.resolve(), runner.owned_work(path))


if __name__ == '__main__':
    unittest.main()
