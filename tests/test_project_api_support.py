"""Fixture cleanup must preserve the original startup exception."""
import unittest
from unittest.mock import Mock, patch

import app.auth as auth
from app.config import settings
from project_api_support import ProjectApiSupport


class ProjectApiSupportTests(unittest.TestCase):
    def test_failed_startup_is_not_exited_twice_and_restores_patches(self):
        class Fixture(ProjectApiSupport, unittest.TestCase):
            def runTest(self):
                pass

        fixture = Fixture()
        old_database = auth.database
        old_settings = (settings.deployment_env, settings.admin_token, settings.mobile_token)
        client = Mock()
        client.__enter__ = Mock(side_effect=RuntimeError('startup rejected'))
        client.__exit__ = Mock()
        with patch('project_api_support.TestClient', return_value=client):
            try:
                with self.assertRaisesRegex(RuntimeError, 'startup rejected'):
                    fixture.start_project_api('failure-cleanup')
            finally:
                fixture.stop_project_api()
                self.assertTrue(fixture.doCleanups())
        client.__exit__.assert_not_called()
        self.assertIs(auth.database, old_database)
        self.assertEqual(old_settings, (settings.deployment_env, settings.admin_token, settings.mobile_token))


if __name__ == '__main__':
    unittest.main()
