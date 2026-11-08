"""Release build checks independent of retired overlays and review-only K8s files."""
from pathlib import Path
import json
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.check_app_update_runtime import check
from tools.install_android_verifier import SHA256, SIZE, install

ROOT = Path(__file__).resolve().parents[1]


class AppUpdateBuildSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='app-update-source-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {'APP_UPDATES_ENABLED': 'true', 'APP_APK_EXTERNAL_ENABLED': 'true',
                    'APP_APK_WORKER_ENABLED': 'false', 'APP_UPDATE_KEY_ID': 'test-only'}
        for name in ('APP_APK_AAPT2_PATH', 'APP_APK_JAVA_PATH', 'APP_APK_APKSIGNER_JAR_PATH'):
            path = self.root / name
            path.write_bytes(b'synthetic unit test tool; not executable product evidence')
            path.chmod(0o755)
            self.env[name] = str(path)
        for name in ('APP_APK_EVIDENCE_ROOT', 'APP_APK_STAGING_ROOT', 'APP_APK_EXTERNAL_ROOT'):
            path = self.root / name
            path.mkdir()
            self.env[name] = str(path)
        self.write_json('APP_UPDATE_SCOPES_PATH', [{'contractVersion': 'app-update/v1',
            'publisherId': 'test', 'packageName': 'com.aiyolo.inspection',
            'channel': 'test', 'deploymentId': 'test'}])
        self.compatibility = {'server_contract_min': 1, 'server_contract_max': 1,
            'data_schema_version': 1, 'readable_schema_min': 1, 'readable_schema_max': 1,
            'evidence_ref': 'synthetic-test-only'}
        self.write_json('APP_APK_COMPATIBILITY_PATH', self.compatibility)
        for name in ('APP_UPDATE_PRIVATE_KEY_PATH', 'MODEL_SIGNING_PRIVATE_KEY_PATH'):
            path = self.root / name
            path.write_bytes(Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            self.env[name] = str(path)
        self.calls = []

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        self.env[name] = str(path)

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    def failed(self):
        return {item['check'] for item in check(self.env, run=self.runner)['checks'] if not item['ok']}

    def test_preflight_never_claims_production_acceptance(self):
        result = check(self.env, run=self.runner)
        self.assertTrue(result['ok'])
        self.assertFalse(result['production_ready'])
        self.assertIn('client_trust', result['not_checked'])
        self.assertEqual(3, len(self.calls))
        for _, options in self.calls:
            self.assertEqual(subprocess.DEVNULL, options['stdout'])
            self.assertEqual(subprocess.DEVNULL, options['stderr'])
            self.assertEqual(20, options['timeout'])

    def test_runtime_must_enable_both_upgrade_flags(self):
        for name in ('APP_UPDATES_ENABLED', 'APP_APK_EXTERNAL_ENABLED'):
            self.env[name] = 'false'
            self.assertIn(name, self.failed())
            self.env[name] = 'true'

    def test_build_tool_checks_need_no_production_secrets(self):
        env = {key: value for key, value in self.env.items() if key in (
            'APP_APK_AAPT2_PATH', 'APP_APK_JAVA_PATH', 'APP_APK_APKSIGNER_JAR_PATH')}
        result = check(env, tools_only=True, run=self.runner)
        self.assertTrue(result['ok'])
        self.assertEqual(3, len(result['checks']))

    def test_missing_tools_fail(self):
        del self.env['APP_APK_AAPT2_PATH']
        self.assertIn('aapt2_executable', self.failed())

    def test_tool_errors_are_redacted(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired('SENSITIVE', 20)
        for runner in (timeout, lambda *a, **k: SimpleNamespace(returncode=1)):
            result = check(self.env, run=runner)
            self.assertFalse(result['ok'])
            self.assertNotIn('SENSITIVE', json.dumps(result))

    def test_invalid_scopes_fail(self):
        for value in ([], [{'packageName': 'invalid'}], [{'extra': 'field'}]):
            self.write_json('APP_UPDATE_SCOPES_PATH', value)
            self.assertIn('scope_file_schema', self.failed())

    def test_compatibility_rejects_invalid_types_and_ranges(self):
        for change in ({'data_schema_version': True}, {'server_contract_max': 0},
                       {'readable_schema_min': 2}, {'evidence_ref': ''}):
            self.write_json('APP_APK_COMPATIBILITY_PATH', {**self.compatibility, **change})
            self.assertIn('compatibility_file_schema_only', self.failed())

    def test_app_and_model_signing_keys_must_differ(self):
        self.env['MODEL_SIGNING_PRIVATE_KEY_PATH'] = self.env['APP_UPDATE_PRIVATE_KEY_PATH']
        self.assertIn('app_signing_key_and_configured_model_key_separation', self.failed())

    def test_bad_key_is_rejected(self):
        Path(self.env['APP_UPDATE_PRIVATE_KEY_PATH']).write_text('not a key', encoding='utf-8')
        self.env['APP_UPDATE_KEY_ID'] = ''
        self.assertIn('app_signing_key_and_configured_model_key_separation', self.failed())

    def test_sensitive_values_are_not_reported(self):
        self.env['DATABASE_URL'] = 'SENSITIVE-NOT-CONNECTED'
        raw = json.dumps(check(self.env, run=self.runner))
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn('SENSITIVE', raw)
        self.assertNotIn('test-only', raw)

    def test_missing_directory_is_not_created(self):
        path = self.root / 'do-not-create'
        self.env['APP_APK_EXTERNAL_ROOT'] = str(path)
        self.assertIn('APP_APK_EXTERNAL_ROOT_permission_estimate', self.failed())
        self.assertFalse(path.exists())

    def test_direct_upload_directory_is_separately_checked(self):
        self.env['APP_APK_WORKER_ENABLED'] = 'true'
        self.assertIn('APP_APK_UPLOAD_ROOT_permission_estimate', self.failed())

    def test_invalid_tool_archives_fail_before_extraction(self):
        archive = self.root / 'bad.zip'
        archive.write_bytes(b'invalid')
        destination = self.root / 'not-created'
        with self.assertRaisesRegex(ValueError, 'size_mismatch'):
            install(archive, destination)
        with patch('tools.install_android_verifier.SIZE', archive.stat().st_size):
            with self.assertRaisesRegex(ValueError, 'sha256_mismatch'):
                install(archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(64, len(SHA256))
        self.assertEqual(63737259, SIZE)

    def test_canonical_dockerfile_contains_complete_verifier_build(self):
        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('AS apk-tools', dockerfile)
        self.assertIn('openjdk-17-jre-headless', dockerfile)
        self.assertIn('COPY --from=apk-tools /opt/android/build-tools/36.0.0', dockerfile)
        self.assertIn('USER app\nRUN python /app/tools/check_app_update_runtime.py --tools-only', dockerfile)
        self.assertIn('RUN npm run test && npm run build && npm run build:preview', dockerfile)
        self.assertNotIn('COPY .env', dockerfile)
        dockerignore = (ROOT / '.dockerignore').read_text(encoding='utf-8')
        for name in ('install_android_verifier.py', 'check_app_update_runtime.py'):
            self.assertIn('!tools/' + name, dockerignore)
            self.assertTrue((ROOT / 'tools' / name).is_file())


if __name__ == '__main__':
    unittest.main()
