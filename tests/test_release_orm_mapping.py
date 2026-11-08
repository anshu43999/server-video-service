"""Regression for ORM mappings already defined by committed PostgreSQL migrations."""
import unittest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.database import (AlertDispositionActionRecord, ProjectScenePlanRecord,
                          SystemKnowledgeCatalogRecord, SystemKnowledgeReleaseRecord)


class ReleaseOrmMappingTests(unittest.TestCase):
    def test_disposition_operation_is_a_unique_index_not_constraint(self):
        table = AlertDispositionActionRecord.__table__
        matches = [index for index in table.indexes if index.name == 'uq_alert_disposition_operation']
        self.assertEqual(1, len(matches))
        self.assertTrue(matches[0].unique)
        self.assertEqual(['project_id', 'event_id', 'operation_id'], list(matches[0].columns.keys()))
        self.assertFalse(any(isinstance(value, UniqueConstraint) and value.name == 'uq_alert_disposition_operation'
                             for value in table.constraints))

    def test_catalog_payload_uses_migrated_postgresql_json_type(self):
        self.assertEqual('JSON', SystemKnowledgeCatalogRecord.__table__.c.payload.type.compile(dialect=postgresql.dialect()))

    def test_knowledge_release_uses_migrated_postgresql_json_type(self):
        self.assertEqual('JSON', SystemKnowledgeReleaseRecord.__table__.c.snapshot.type.compile(dialect=postgresql.dialect()))

    def test_scene_camera_policy_uses_migrated_postgresql_json_type(self):
        self.assertEqual('JSON', ProjectScenePlanRecord.__table__.c.camera_policy.type.compile(dialect=postgresql.dialect()))


if __name__ == '__main__':
    unittest.main()
