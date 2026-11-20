import copy
import os
import tempfile
import unittest
from pathlib import Path

from app.database import Base, DatabaseManager, DEFAULT_PROJECT_ID, ProjectRecord
from app.model_parameters import ModelParameterStore, ModelParameterError, ModelParameterConflict

MODEL = {"modelId": "platform-test", "version": "1.0.0", "labels": ["head"]}


class PlatformParameterTests(unittest.TestCase):
    database = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "parameters.json"
        self.db = None
        if self.database:
            if getattr(self, "postgres", False):
                from postgresql_support import isolated_postgresql_url
                scope = isolated_postgresql_url("platform_parameters")
                url = scope.__enter__()
                self.addCleanup(lambda: scope.__exit__(None, None, None))
            else:
                url = "sqlite:///" + str(Path(self.temp.name) / "test.db")
            self.db = DatabaseManager(url)
            self.addCleanup(self.db.close)
            Base.metadata.create_all(self.db.engine)
            with self.db.session() as session:
                if session.get(ProjectRecord, DEFAULT_PROJECT_ID) is None:
                    session.add(ProjectRecord(project_id=DEFAULT_PROJECT_ID, project_code="default", display_name="Default"))
        self.store = ModelParameterStore(self.path, self.db)

    def test_draft_is_not_runnable_and_publication_is_explicit(self):
        draft = self.store.get(MODEL, "android")
        self.assertIsNone(draft["publishedRevision"])
        with self.assertRaisesRegex(ModelParameterError, "published"):
            self.store.published(MODEL, "android")
        result = self.store.publish(MODEL, "android", "admin", 0, None)
        self.assertEqual("platform", result["source"])
        self.assertEqual(result, ModelParameterStore(self.path, self.db).published(MODEL, "android"))

    def test_edits_reset_and_new_publications_preserve_running_snapshot(self):
        first = self.store.publish(MODEL, "android", "admin", 0, None)
        frozen = copy.deepcopy(first)
        values = self.store.get(MODEL, "android")
        values["detection"]["confidenceThreshold"] = .5
        self.store.save(MODEL, "android", values, "admin", 0)
        self.assertEqual(frozen, self.store.published(MODEL, "android"))
        second = self.store.publish(MODEL, "android", "admin", 1, 0)
        self.assertEqual(.5, second["detection"]["confidenceThreshold"])
        self.assertEqual(frozen, first)
        self.store.reset(MODEL, "android", "admin", expected_revision=1)
        self.assertEqual(second, self.store.published(MODEL, "android"))
        self.assertEqual(1, self.store.get(MODEL, "android")["publishedRevision"])

    def test_project_writes_rejected_and_projects_use_same_values(self):
        values = self.store.get(MODEL, "server")
        for project in ("a", "b", DEFAULT_PROJECT_ID):
            with self.assertRaisesRegex(ModelParameterError, "platform"):
                self.store.save(MODEL, "server", values, "owner", 0, project)
            with self.assertRaisesRegex(ModelParameterError, "platform"):
                self.store.reset(MODEL, "server", "owner", project)
        self.store.publish(MODEL, "server", "admin", 0, None)
        a, b = (self.store.get(MODEL, "server", p) for p in ("a", "b"))
        self.assertEqual(a["detection"], b["detection"])
        self.assertEqual(a["alertRules"], b["alertRules"])

    def test_publication_cas_and_target_version_isolation(self):
        with self.assertRaises(ModelParameterConflict):
            self.store.publish(MODEL, "server", "admin", 1, None)
        first = self.store.publish(MODEL, "server", "admin", 0, None)
        with self.assertRaises(ModelParameterConflict):
            self.store.publish(MODEL, "server", "admin", 0, None)
        self.assertEqual(first, self.store.publish(MODEL, "server", "admin", 0, 0))
        for model, platform in ((MODEL, "android"), ({**MODEL, "version": "2.0.0"}, "server")):
            with self.assertRaises(ModelParameterError):
                self.store.published(model, platform)

    def test_catalog_status_tracks_exact_version_target_and_published_zero(self):
        other = {**MODEL, "version": "2.0.0"}
        key = (MODEL["modelId"], MODEL["version"])
        states = self.store.publication_status([MODEL, other])
        self.assertEqual("unpublished", states[key]["server"]["state"])
        self.assertIsNone(states[key]["server"]["publishedRevision"])
        self.store.publish(MODEL, "server", "admin", 0, None)
        states = self.store.publication_status([MODEL, other])
        self.assertEqual({"state": "published", "publishedRevision": 0, "hasUnpublishedChanges": False}, states[key]["server"])
        self.assertEqual("unpublished", states[key]["android"]["state"])
        self.assertEqual("unpublished", states[(other["modelId"], other["version"])]["server"]["state"])
        draft = self.store.get(MODEL, "server")
        draft["detection"]["confidenceThreshold"] = .5
        self.store.save(MODEL, "server", draft, "admin", 0)
        self.assertEqual({"state": "published", "publishedRevision": 0, "hasUnpublishedChanges": True},
                         self.store.publication_status([MODEL])[key]["server"])
        self.store.publish(MODEL, "server", "admin", 1, 0)
        self.assertEqual({"state": "published", "publishedRevision": 1, "hasUnpublishedChanges": False},
                         self.store.publication_status([MODEL])[key]["server"])

    def test_invalid_publication_is_unavailable_instead_of_unpublished(self):
        self.store.publish(MODEL, "server", "admin", 0, None)
        # A changed class contract makes the existing publication invalid.
        changed = {**MODEL, "labels": ["different-label"]}
        state = self.store.publication_status([changed])[(MODEL["modelId"], MODEL["version"])]["server"]
        self.assertEqual("unavailable", state["state"])
        self.assertIsNone(state["publishedRevision"])


class PlatformParameterDatabaseTests(PlatformParameterTests):
    database = True

    def test_catalog_status_batches_database_reads_and_excludes_project_overrides(self):
        from sqlalchemy import event
        from app.database import ModelParameterProfileRecord
        self.store._import_legacy_once()
        with self.db.session() as session:
            session.add(ProjectRecord(project_id="private", project_code="private", display_name="Private"))
            session.flush()
            session.add(ModelParameterProfileRecord(project_id="private", scope="PROJECT",
                profile_key=self.store._database_key_for_model(MODEL, "server"),
                model_id=MODEL["modelId"], model_version=MODEL["version"], platform="server",
                revision=20, payload=self.store.default_profile(MODEL, "server")))
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(self.db.engine, "before_cursor_execute", capture)
        try:
            states = self.store.publication_status([{**MODEL, "version": str(i)} for i in range(30)] + [MODEL])
        finally:
            event.remove(self.db.engine, "before_cursor_execute", capture)
        self.assertEqual(2, len(statements), statements)
        self.assertEqual("unpublished", states[(MODEL["modelId"], MODEL["version"])]["server"]["state"])

    def test_difference_report_preserves_legacy_override(self):
        from tools.audit_platform_model_parameters import differences
        from app.database import ModelParameterProfileRecord
        legacy = self.store.default_profile(MODEL, 'server')
        legacy['detection']['confidenceThreshold'] = .21
        with self.db.session() as session:
            session.add(ProjectRecord(project_id='legacy-project', project_code='legacy-project', display_name='Legacy'))
            session.flush()
            session.add(ModelParameterProfileRecord(project_id='legacy-project', scope='PROJECT', profile_key='legacy',
                model_id=MODEL['modelId'], model_version=MODEL['version'], platform='server', revision=8, payload=legacy))
        self.store.publish(MODEL, 'server', 'admin', 0, None)
        with self.db.session() as session:
            report = differences(session)
            row = next(row for row in report['rows'] if row['kind'] == 'project_override')
            self.assertEqual(['detection'], row['differentFields'])
            self.assertFalse(row['missingPublication'])
            stored = session.get(ModelParameterProfileRecord, ('legacy-project', 'legacy'))
            self.assertEqual((8, legacy), (stored.revision, stored.payload))

    def test_publication_audit_failure_rolls_back(self):
        from unittest.mock import patch
        with patch('app.model_parameters.audit_change', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.store.publish(MODEL, 'server', 'admin', 0, None)
        with self.assertRaises(ModelParameterError):
            self.store.published(MODEL, 'server')

    def test_revoked_platform_admin_cannot_publish(self):
        from app.auth import Principal
        from app.database import AccountRecord
        with self.db.session() as session:
            session.add(AccountRecord(account_id='publisher', username='publisher', password_hash='not-a-login',
                role='admin', platform_role='NORMAL_USER', enabled=True))
        principal = Principal('publisher', 'publisher', 'admin', 'PLATFORM_ADMIN')
        with self.assertRaises(ModelParameterError):
            self.store.publish(MODEL, 'server', 'publisher', 0, None, context=principal)
        with self.assertRaises(ModelParameterError):
            self.store.published(MODEL, 'server')


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1', 'isolated PostgreSQL required')
class PlatformParameterPostgresTests(PlatformParameterDatabaseTests):
    postgres = True

    def test_independent_workers_publish_only_one_cas_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        writers = [ModelParameterStore(self.path, self.db) for _ in range(2)]
        for writer in writers:
            writer._import_legacy_once()
        barrier = Barrier(2)
        def publish(writer):
            barrier.wait(timeout=10)
            try:
                writer.publish(MODEL, 'server', 'admin', 0, None)
                return 'published'
            except ModelParameterConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(['published', 'conflict'], list(pool.map(publish, writers)))
