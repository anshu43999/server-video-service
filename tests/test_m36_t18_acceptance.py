"""Local HTTP runner safety, independent of PostgreSQL and model assets."""
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from accept_m36_t18_live import Acceptance


class LiveAcceptanceClientTests(unittest.TestCase):
    def client(self, handler):
        acceptance = Acceptance('http://127.0.0.1:12345', 'unused')
        acceptance.client.close()
        acceptance.client = httpx.Client(base_url='http://127.0.0.1:12345',
                                         transport=httpx.MockTransport(handler))
        self.addCleanup(acceptance.client.close)
        return acceptance

    def test_setup_omits_empty_bearer_and_trace_never_copies_token(self):
        def handler(request):
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, json={'accessToken': 'unit-only-secret'},
                                  headers={'x-request-id': request.headers['x-request-id']})
        acceptance = self.client(handler)
        acceptance.call('admin', 'POST', '/aiyoloapi/auth/setup', {})
        self.assertEqual(1, len(acceptance.trace))
        self.assertNotIn('unit-only-secret', str(acceptance.trace))

    def test_empty_json_204_is_valid_and_authenticated(self):
        def handler(request):
            self.assertEqual('Bearer unit-only-token', request.headers['authorization'])
            return httpx.Response(204, headers={'content-type': 'application/json'})
        acceptance = self.client(handler)
        acceptance.tokens['gly'] = 'unit-only-token'
        self.assertEqual(204, acceptance.call('gly', 'DELETE', '/aiyoloapi/projects/p/members/u',
                                             expected=204).status_code)
        self.assertNotIn('unit-only-token', str(acceptance.trace))

    def test_foreign_urls_rejected_before_credential_transport(self):
        visited = []
        acceptance = self.client(lambda request: visited.append(request) or httpx.Response(200))
        for path in ('https://foreign.example/aiyoloapi/', '//foreign.example/aiyoloapi/', '/admin/'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                acceptance.call('admin', 'GET', path)
        self.assertEqual([], visited)

    def test_unexpected_status_fails_and_retains_safe_error_trace(self):
        acceptance = self.client(lambda request: httpx.Response(403, json={'detail': {'code': 'denied'}}))
        with self.assertRaises(AssertionError):
            acceptance.call('ptcy', 'GET', '/aiyoloapi/projects/p')
        self.assertEqual({'code': 'denied'}, acceptance.trace[0]['error'])
