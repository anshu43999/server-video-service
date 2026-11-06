import json
import unittest
from unittest.mock import patch

from tools.accept_local_project_baseline import ROOT, isolated_environment


class LocalProjectBaselineSafetyTest(unittest.TestCase):
    def test_no_inherited_deployment_credentials(self):
        with patch.dict('os.environ', {'PATH': 'system-tools', 'DATABASE_URL': 'must-not-use',
                                      'MINIO_ENDPOINT': 'must-not-use', 'PYTHONPATH': 'must-not-use',
                                      'PGSERVICE': 'must-not-use'}, clear=True):
            self.assertEqual(isolated_environment(), {'PATH': 'system-tools'})

    def test_local_gate_precedes_deployment_without_cycle(self):
        state = json.loads((ROOT / 'harness/task-state.json').read_text(encoding='utf-8'))
        tasks = {task['id']: task for major in state['majorTasks'] for task in major['subtasks']}
        self.assertEqual(tasks['M33-T18']['dependsOn'], ['M33-T14', 'M33-T15', 'M33-T16', 'M33-T22'])
        self.assertEqual(tasks['M33-T20']['dependsOn'], ['M33-T19'])
        self.assertEqual(tasks['M33-T22']['dependsOn'], ['M33-T20', 'M33-T21'])
        for task_id in ('M33-T19', 'M33-T20', 'M33-T21', 'M33-T22'):
            self.assertNotIn('M33-T17', tasks[task_id]['dependsOn'])
            self.assertTrue(all(dep.startswith('M33-') for dep in tasks[task_id]['dependsOn']))
        self.assertIn('M33-T18', tasks['M33-T17']['dependsOn'])
        self.assertIn('Android', tasks['M33-T18']['acceptance'])
        self.assertIn('回滚', tasks['M33-T17']['acceptance'])
