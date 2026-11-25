"""The retired registry has no public management routes."""
import unittest
from project_api_support import ProjectApiSupport


class AdminOperationsApiTests(ProjectApiSupport, unittest.TestCase):
    def test_retired_registry_has_no_routes(self):
        self.start_project_api('operations-project')
        self.addCleanup(self.stop_project_api)
        for prefix in (self.project_path, '/aiyoloapi'):
            for method, suffix in [('GET', ''), ('POST', ''), ('GET', '/audit'), ('PUT', '/example'),
                                   ('DELETE', '/example'), ('POST', '/example/bindings'), ('POST', '/example/validate')]:
                with self.subTest(prefix=prefix, method=method, suffix=suffix):
                    self.assertEqual(self.client.request(method, prefix + '/rules' + suffix).status_code, 404)
