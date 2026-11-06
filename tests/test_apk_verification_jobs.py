"""Worker transactions, reruns, failure audit and package-wide version CAS."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from alembic import command
from sqlalchemy import select

from apk_test_support import ApkFixtures
from app.app_updates.apk_verifier import ApkVerifier, VerifiedApk, VerificationError
from app.app_updates.models import AppArtifact, AppAudit, AppIdentity
from app.app_updates.verification_jobs import BuildCompatibility, VerificationJobs
from app.database import DatabaseManager
from postgresql_support import isolated_postgresql_url
from test_app_update_storage import migration_config

ROOT = Path(__file__).resolve().parents[1]
COMPAT = BuildCompatibility(1, 1, 19, 18, 19, "ci/test/compatibility.json")
PACKAGE = "com.aiyolo.inspection"


class ResultVerifier:
    """Transaction unit fixture; real-tool integration is tested separately."""
    def __init__(self, root, *, version=1, barrier=None):
        self.root, self.version, self.barrier = root, version, barrier

    def verify(self, stream, **kwargs):
        if self.barrier:
            self.barrier.wait(timeout=10)
        raw = stream.read()
        if raw == b"bad":
            raise VerificationError("apk_signature_invalid")
        if self.version == 3:
            digest = "c" * 64
        else:
            digest = "a" * 64
        return VerifiedApk(PACKAGE, self.version, "test", 27, ("arm64-v8a",), len(raw), digest,
                           "b" * 64, str(self.root / "test-report.json"))


class WorkerAssertions:
    def setup_records(self):
        self.file = self.root / "input.apk"
        self.file.write_bytes(b"fixture")
        with self.db.session() as session:
            session.add(AppIdentity(package_name=PACKAGE, publisher_id="test", approved_signer_sha256="b" * 64))
        self.add_artifact("one")

    def add_artifact(self, identity):
        with self.db.session() as session:
            session.add(AppArtifact(artifact_id=identity, package_name=PACKAGE, publisher_id="test", created_by="admin"))

    def worker(self, verifier=None):
        return VerificationJobs(self.db, verifier or ResultVerifier(self.root))

    def test_verified_state_high_water_and_duplicate_same_bytes(self):
        self.setup_records()
        self.assertEqual("one", self.worker().verify_file("one", self.file, actor_id="admin", compatibility=COMPAT))
        self.add_artifact("duplicate")
        self.assertEqual("one", self.worker().verify_file("duplicate", self.file, actor_id="admin", compatibility=COMPAT))
        with self.db.session() as session:
            artifact = session.get(AppArtifact, "one")
            self.assertEqual("verified", artifact.state)
            self.assertEqual(19, artifact.data_schema_version)
            self.assertEqual(1, session.get(AppIdentity, PACKAGE).version_high_water)
            self.assertEqual("duplicate_existing_artifact", session.get(AppArtifact, "duplicate").error_code)
            self.assertEqual(2, len(session.scalars(select(AppAudit)).all()))
        with self.assertRaisesRegex(VerificationError, "artifact_verification_conflict"):
            self.worker().verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)

    def test_failed_verification_does_not_reserve_version_and_can_retry(self):
        self.setup_records()
        self.file.write_bytes(b"bad")
        with self.assertRaisesRegex(VerificationError, "apk_signature_invalid"):
            self.worker().verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)
        with self.db.session() as session:
            artifact = session.get(AppArtifact, "one")
            self.assertEqual("failed", artifact.state)
            self.assertIsNone(artifact.version_code)
            self.assertEqual(0, session.get(AppIdentity, PACKAGE).version_high_water)
            self.assertEqual("failed", session.scalar(select(AppAudit)).result)
        self.file.write_bytes(b"fixture")
        self.worker().verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)

    def test_compatibility_and_first_version_guard(self):
        self.setup_records()
        with self.assertRaisesRegex(VerificationError, "build_compatibility_missing"):
            self.worker().verify_file("one", self.file, actor_id="admin",
                compatibility=BuildCompatibility(1, 1, 19, 1, 18, "ci/test"))
        with self.assertRaisesRegex(VerificationError, "version_not_increasing"):
            self.worker(ResultVerifier(self.root, version=3)).verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)
        with self.db.session() as session:
            self.assertEqual(0, session.get(AppIdentity, PACKAGE).version_high_water)
            self.assertEqual("failed", session.get(AppArtifact, "one").state)

    def test_revoked_certificate_during_verification_is_rechecked(self):
        self.setup_records()
        original = ResultVerifier(self.root)
        database = self.db
        class Revoke:
            def verify(self, stream, **kwargs):
                result = original.verify(stream, **kwargs)
                with database.session() as session:
                    session.get(AppIdentity, PACKAGE).approved_signer_sha256 = "c" * 64
                return result
        with self.assertRaisesRegex(VerificationError, "signer_not_approved"):
            self.worker(Revoke()).verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)
        with self.db.session() as session:
            self.assertEqual(0, session.get(AppIdentity, PACKAGE).version_high_water)

    def test_unexpected_worker_failure_becomes_failed_with_audit(self):
        self.setup_records()
        class Broken:
            def verify(self, stream, **kwargs):
                raise RuntimeError("do not expose internal paths")
        with self.assertRaisesRegex(VerificationError, "verification_internal_error"):
            self.worker(Broken()).verify_file("one", self.file, actor_id="admin", compatibility=COMPAT)
        with self.db.session() as session:
            self.assertEqual("failed", session.get(AppArtifact, "one").state)
            self.assertNotIn("internal paths", str(session.scalar(select(AppAudit)).details))


class SQLiteVerificationJobsTests(WorkerAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-jobs-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        url = "sqlite+pysqlite:///" + (self.root / "test.db").as_posix()
        command.upgrade(migration_config(url), "head")
        self.db = DatabaseManager(url)
        self.addCleanup(self.db.close)


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "requires isolated PostgreSQL")
class PostgreSQLVerificationJobsTests(WorkerAssertions, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-jobs-pg-", dir=ROOT / ".tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cluster = isolated_postgresql_url("apk_verification")
        url = self.cluster.__enter__()
        self.addCleanup(lambda: self.cluster.__exit__(None, None, None))
        self.db = DatabaseManager(url)
        self.addCleanup(self.db.close)

    def test_concurrent_same_version_keeps_one_artifact_and_both_audits(self):
        self.setup_records()
        self.add_artifact("two")
        barrier = threading.Barrier(2)
        worker = self.worker(ResultVerifier(self.root, barrier=barrier))
        def verify(identity):
            return worker.verify_file(identity, self.file, actor_id="admin", compatibility=COMPAT)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(verify, ("one", "two")))
        self.assertEqual(results[0], results[1])
        with self.db.session() as session:
            self.assertEqual(1, session.get(AppIdentity, PACKAGE).version_high_water)
            self.assertEqual(1, len(session.scalars(select(AppArtifact).where(AppArtifact.state == "verified")).all()))
            self.assertEqual(2, len(session.scalars(select(AppAudit)).all()))

    @unittest.skipUnless(os.environ.get("RUN_APK_TOOL_TESTS") == "1", "requires real SDK tools")
    def test_real_signed_apk_persists_verified_metadata_and_audit(self):
        fixtures = ApkFixtures(self.root)
        apk = fixtures.apk("real-worker", native_abi="arm64-v8a")
        signer = fixtures.signer(apk)
        self.setup_records()
        with self.db.session() as session:
            session.get(AppIdentity, PACKAGE).approved_signer_sha256 = signer
        self.worker(ApkVerifier(fixtures.tools)).verify_file("one", apk, actor_id="admin", compatibility=COMPAT)
        with self.db.session() as session:
            artifact = session.get(AppArtifact, "one")
            self.assertEqual("verified", artifact.state)
            self.assertEqual(signer, artifact.signer_sha256)
            self.assertEqual(["arm64-v8a"], artifact.abis)
            self.assertEqual("succeeded", session.scalar(select(AppAudit)).result)
            report = json.loads(Path(artifact.verification_evidence_ref).read_text())
            self.assertEqual(artifact.sha256, report["sha256"])
