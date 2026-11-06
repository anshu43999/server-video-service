"""Identity registration tests use memory-only SQLite, never application data."""
import unittest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.app_updates.models import AppIdentity
from app.app_updates.contract import PACKAGE_NAME
from tools.init_app_update_identity import ensure_identity


class IdentityBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        AppIdentity.__table__.create(self.engine)
        self.args = dict(publisher_id='unit-test', signer_sha256='a' * 64, metadata_key_id='unit-key')

    def tearDown(self):
        self.engine.dispose()

    def test_default_is_read_only(self):
        with Session(self.engine) as s, s.begin():
            self.assertEqual(ensure_identity(s, **self.args)['result'], 'would_create')
            self.assertIsNone(s.get(AppIdentity, PACKAGE_NAME))

    def test_apply_creates_first_identity(self):
        with Session(self.engine) as s, s.begin():
            self.assertEqual(ensure_identity(s, **self.args, apply=True)['result'], 'created')
            row = s.get(AppIdentity, PACKAGE_NAME)
            self.assertEqual(row.first_version_code, 1)
            self.assertEqual(row.version_high_water, 0)

    def test_reapply_preserves_version_watermark(self):
        with Session(self.engine) as s, s.begin():
            ensure_identity(s, **self.args, apply=True)
            s.get(AppIdentity, PACKAGE_NAME).version_high_water = 12
        with Session(self.engine) as s, s.begin():
            self.assertEqual(ensure_identity(s, **self.args, apply=True),
                dict(result='unchanged', packageName=PACKAGE_NAME, versionHighWater=12))
            self.assertEqual(len(s.scalars(select(AppIdentity)).all()), 1)

    def test_conflicts_do_not_overwrite(self):
        with Session(self.engine) as s, s.begin():
            ensure_identity(s, **self.args, apply=True)
        for field, value in [('publisher_id', 'other'), ('signer_sha256', 'b' * 64), ('metadata_key_id', 'other-key')]:
            with self.subTest(field=field), Session(self.engine) as s, s.begin():
                with self.assertRaisesRegex(ValueError, 'conflicts'):
                    ensure_identity(s, **(self.args | {field: value}), apply=True)
                self.assertEqual(getattr(s.get(AppIdentity, PACKAGE_NAME),
                    {'signer_sha256':'approved_signer_sha256','metadata_key_id':'metadata_key_config_ref'}.get(field, field)), self.args[field])

    def test_dry_run_preserves_existing_identity(self):
        with Session(self.engine) as s, s.begin():
            ensure_identity(s, **self.args, apply=True)
            s.get(AppIdentity, PACKAGE_NAME).version_high_water = 7
        with Session(self.engine) as s, s.begin():
            self.assertEqual(ensure_identity(s, **self.args),
                dict(result='unchanged', packageName=PACKAGE_NAME, versionHighWater=7))
            self.assertEqual(len(s.scalars(select(AppIdentity)).all()), 1)

    def test_transaction_failure_rolls_back_creation(self):
        with self.assertRaisesRegex(RuntimeError, 'operator abort'):
            with Session(self.engine) as s, s.begin():
                ensure_identity(s, **self.args, apply=True)
                raise RuntimeError('operator abort')
        with Session(self.engine) as s:
            self.assertIsNone(s.get(AppIdentity, PACKAGE_NAME))


if __name__ == '__main__':
    unittest.main()
