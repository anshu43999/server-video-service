import hashlib
import http.client
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from app.conversion import ConversionConfig, RemoteConversionRunner
from tools import conversion_worker


class ScriptedHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.calls.append((self.command, self.path))
        if self.command == 'POST':
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
        response = self.server.responses.pop(0)
        if response == 'disconnect':
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        status, payload, headers = response
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_POST = do_GET


class RemoteResilienceTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ScriptedHandler)
        self.server.responses = []
        self.server.calls = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = ConversionConfig(mode='remote', remote_endpoint=f'http://127.0.0.1:{self.server.server_port}',
                                       remote_allow_insecure_http=True, python_path=sys.executable,
                                       remote_verifier_mode='local')
        self.runner = RemoteConversionRunner(Mock())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def response(self, value, status=200, headers=None):
        return status, json.dumps(value).encode(), headers or {}

    def poll(self, stopping=None, callback=None):
        return self.runner._poll_status(self.config, 'test-secret', 'remote-1',
                                        stopping or threading.Event(), 100.0, callback)

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_disconnect_then_503_recovers_same_job_without_resubmit(self, clock):
        self.server.responses = ['disconnect', self.response({}, 503),
                                 self.response({'jobId': 'remote-1', 'status': 'running', 'stage': 'exporting'})]
        stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
        progress = []
        result = self.poll(stopping, progress.append)
        self.assertEqual(result['stage'], 'exporting')
        self.assertEqual(self.server.calls, [('GET', '/v1/conversions/remote-1')] * 3)
        self.assertEqual(len(progress), 2)
        self.assertTrue(all(p['stage'] == 'remote_retrying' for p in progress))
        self.assertEqual(stopping.wait.call_count, 2)

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_permanent_http_errors_and_invalid_json_do_not_retry(self, clock):
        for status, payload in [(401, b'{}'), (403, b'{}'), (404, b'{}'), (422, b'{}'),
                                (200, b'not-json test-secret'), (200, b'[]')]:
            with self.subTest(status=status, payload=payload):
                self.server.calls.clear()
                self.server.responses = [(status, payload, {})]
                with self.assertRaises(RuntimeError) as caught:
                    self.poll()
                self.assertNotIn('test-secret', str(caught.exception))
                self.assertEqual(len(self.server.calls), 1)

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_retry_exhaustion_is_bounded_and_does_not_claim_oom(self, clock):
        self.server.responses = ['disconnect'] * 3
        stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'remote_connection_error') as caught:
            self.poll(stopping)
        self.assertEqual(len(self.server.calls), 3)
        self.assertNotIn('OOM', str(caught.exception))
        self.assertNotIn('test-secret', str(caught.exception))

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_retry_after_is_capped(self, clock):
        self.server.responses = [self.response({}, 429, {'Retry-After': '99999'}),
                                 self.response({'jobId': 'remote-1', 'status': 'succeeded'})]
        stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
        self.poll(stopping)
        self.assertLessEqual(stopping.wait.call_args.args[0], 5)

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_stop_during_backoff_cancels_without_second_poll(self, clock):
        self.server.responses = ['disconnect']
        stopping = Mock(); stopping.wait.return_value = True; stopping.is_set.return_value = False
        with patch.object(self.runner, '_cancel') as cancel:
            with self.assertRaisesRegex(RuntimeError, '取消'):
                self.poll(stopping)
            cancel.assert_called_once()
        self.assertEqual(len(self.server.calls), 1)

    @patch('app.conversion.time.monotonic', return_value=101.0)
    def test_deadline_cancels_without_poll(self, clock):
        with patch.object(self.runner, '_cancel') as cancel:
            with self.assertRaisesRegex(RuntimeError, '超时'):
                self.poll()
            cancel.assert_called_once()
        self.assertEqual(self.server.calls, [])

    @patch('app.conversion.time.monotonic', side_effect=[99.9, 99.95, 100.01])
    def test_backoff_cannot_extend_deadline(self, clock):
        self.server.responses = ['disconnect']
        stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
        with patch.object(self.runner, '_cancel') as cancel:
            with self.assertRaisesRegex(RuntimeError, '超时'):
                self.poll(stopping)
            cancel.assert_called_once()
        self.assertLess(stopping.wait.call_args.args[0], 0.1)
        self.assertEqual(len(self.server.calls), 1)

    @patch('app.conversion.time.monotonic', side_effect=[99.0, 100.1])
    def test_response_after_deadline_is_not_accepted(self, clock):
        self.server.responses = [self.response({'jobId': 'remote-1', 'status': 'succeeded'})]
        with patch.object(self.runner, '_cancel') as cancel:
            with self.assertRaisesRegex(RuntimeError, '超时'):
                self.poll()
            cancel.assert_called_once()

    @patch('app.conversion.time.monotonic', return_value=0.0)
    def test_wrong_job_or_unknown_status_is_protocol_failure(self, clock):
        for data in [{'jobId': 'different', 'status': 'running'},
                     {'jobId': 'remote-1', 'status': 'bogus'},
                     {'jobId': 'remote-1', 'status': []}]:
            self.server.responses = [self.response(data)]
            with self.assertRaisesRegex(RuntimeError, 'remote_invalid_response'):
                self.poll()

    def test_post_disconnect_is_not_retried(self):
        self.server.responses = ['disconnect']
        with self.assertRaisesRegex(RuntimeError, 'remote_connection_error'):
            self.runner._json_request(self.config, 'test-secret', 'POST', '/v1/conversions')
        self.assertEqual(len(self.server.calls), 1)

    def test_connection_timeout_is_distinct_and_redacted(self):
        conn = Mock(); conn.request.side_effect = TimeoutError('test-secret internal-host')
        with patch.object(self.runner, '_connection', return_value=(conn, '')):
            with self.assertRaisesRegex(RuntimeError, 'remote_timeout') as caught:
                self.runner._json_request(self.config, 'test-secret', 'GET', '/v1/health')
        self.assertNotIn('test-secret', str(caught.exception))
        conn.close.assert_called_once()

    def test_authentication_response_body_disconnect_does_not_retry(self):
        response = Mock(status=401)
        response.read.side_effect = http.client.IncompleteRead(b'private')
        conn = Mock(); conn.getresponse.return_value = response
        with patch.object(self.runner, '_connection', return_value=(conn, '')):
            with self.assertRaises(RuntimeError) as caught:
                self.runner._json_request(self.config, 'test-secret', 'GET', '/v1/conversions/remote-1')
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn('private', str(caught.exception))

    def test_tls_and_malformed_protocol_are_not_retryable(self):
        for error, code in [(ssl.SSLError('private-host'), 'remote_tls_error'),
                            (http.client.BadStatusLine('test-secret'), 'remote_invalid_response')]:
            conn = Mock(); conn.request.side_effect = error
            with patch.object(self.runner, '_connection', return_value=(conn, '')):
                with self.assertRaisesRegex(RuntimeError, code) as caught:
                    self.runner._json_request(self.config, 'test-secret', 'GET', '/v1/health')
            self.assertFalse(caught.exception.retryable)
            self.assertNotIn('test-secret', str(caught.exception))

    @patch.dict(os.environ, {'AIYOLO_REMOTE_CONVERSION_TOKEN': 'test-secret'})
    def test_full_mobile_flow_recovers_read_and_still_locally_verifies(self):
        artifact = b'test-model'
        self.server.responses = [
            self.response({'jobId': 'remote-1', 'status': 'running'}, 202), 'disconnect',
            self.response({'jobId': 'remote-1', 'status': 'succeeded',
                           'result': {'labels': ['helmet'], 'sizeBytes': len(artifact),
                                      'sha256': hashlib.sha256(artifact).hexdigest(),
                                      'artifactUrl': '/v1/conversions/remote-1/artifact'}}),
            (200, artifact, {}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'source.pt').write_bytes(b'weights')
            def verify(config, action, folder, stopping, request=None):
                self.assertEqual(action, 'verify')
                self.assertEqual((folder / 'android.tflite').read_bytes(), artifact)
                return {'ok': True, 'labels': request['expected_labels']}
            self.runner.local_runner.run_worker.side_effect = verify
            stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
            result = self.runner.run(self.config, 'mobile', directory, stopping)
        self.assertEqual(result['remote_job_id'], 'remote-1')
        self.assertEqual([method for method, _ in self.server.calls], ['POST', 'GET', 'GET', 'GET'])
        self.runner.local_runner.run_worker.assert_called_once()

    @patch.dict(os.environ, {'AIYOLO_REMOTE_CONVERSION_TOKEN': 'test-secret'})
    def test_remote_terminal_failure_is_not_retried_or_verified(self):
        self.server.responses = [self.response({'jobId': 'remote-1', 'status': 'running'}, 202),
                                 self.response({'jobId': 'remote-1', 'status': 'failed',
                                                'error': {'code': 'worker_result_missing'}})]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'source.pt').write_bytes(b'weights')
            stopping = Mock(); stopping.wait.return_value = False; stopping.is_set.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'worker_result_missing'):
                self.runner.run(self.config, 'mobile', directory, stopping)
        self.assertEqual(len(self.server.calls), 2)
        self.runner.local_runner.run_worker.assert_not_called()

    @patch.dict(os.environ, {'AIYOLO_REMOTE_CONVERSION_TOKEN': 'test-secret'})
    def test_remote_check_uses_verifier_not_local_exporter(self):
        self.server.responses = [self.response({'status': 'ok', 'protocolVersion': 1,
                                                'capabilities': ['yolo-detect-to-tflite-int8']})]
        self.runner.local_runner.run_worker.return_value = {'ok': True, 'mobile_available': False,
                                                            'verifier_available': True}
        with tempfile.TemporaryDirectory() as temporary:
            result = self.runner.run(self.config, 'check', Path(temporary), threading.Event())
        self.assertTrue(result['mobile_available'])
        self.assertTrue(result['verifier_available'])
        self.assertFalse(result['verifier']['mobile_available'])

    @patch.dict(os.environ, {'AIYOLO_REMOTE_CONVERSION_TOKEN': 'test-secret'})
    def test_remote_check_missing_verifier_or_capability_stays_unavailable(self):
        for verifier, capabilities in [(False, ['yolo-detect-to-tflite-int8']), (True, [])]:
            self.server.responses = [self.response({'status': 'ok', 'protocolVersion': 1, 'capabilities': capabilities})]
            self.runner.local_runner.run_worker.return_value = {'ok': True, 'mobile_available': True,
                                                                'verifier_available': verifier}
            with tempfile.TemporaryDirectory() as temporary:
                result = self.runner.run(self.config, 'check', Path(temporary), threading.Event())
            self.assertFalse(result['mobile_available'])


class WorkerCapabilityTests(unittest.TestCase):
    def environment(self, *, interpreter=True, exporter=False):
        fake_interpreter = ModuleType('ai_edge_litert.interpreter')
        fake_interpreter.Interpreter = Mock()
        modules = {'torch': ModuleType('torch'), 'ultralytics': ModuleType('ultralytics'),
                   'numpy': ModuleType('numpy'), 'ai_edge_litert': ModuleType('ai_edge_litert'),
                   'ai_edge_litert.interpreter': fake_interpreter if interpreter else None}
        def version(name):
            if name == 'litert-torch' and not exporter:
                raise conversion_worker.importlib.metadata.PackageNotFoundError(name)
            return 'test-version'
        with patch.dict(sys.modules, modules), patch.dict(os.environ), \
                patch('tools.conversion_worker.platform.system', return_value='Linux'), \
                patch('tools.conversion_worker.importlib.metadata.version', side_effect=version):
            return conversion_worker.environment()

    def test_verifier_only_image_does_not_require_export_packages(self):
        result = self.environment()
        self.assertTrue(result['verifier_available'])
        self.assertFalse(result['mobile_available'])
        self.assertIn('ai-edge-litert', result['packages'])

    def test_missing_interpreter_is_not_marked_ready(self):
        result = self.environment(interpreter=False, exporter=True)
        self.assertFalse(result['verifier_available'])
        self.assertFalse(result['mobile_available'])

    def test_full_export_environment_keeps_existing_capability(self):
        result = self.environment(exporter=True)
        self.assertTrue(result['verifier_available'])
        self.assertTrue(result['mobile_available'])


if __name__ == '__main__':
    unittest.main()
