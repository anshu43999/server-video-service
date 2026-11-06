import os
from pathlib import Path
import tempfile
import unittest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, MetaData, Table, select


class UpdateMigrationTests(unittest.TestCase):
    def setUp(self):
        if getattr(self, 'use_postgresql', False):
            from postgresql_support import isolated_postgresql_url
            pg = isolated_postgresql_url('m111_migration', revision='20261025_22')
            self.url = pg.__enter__(); self.addCleanup(lambda: pg.__exit__(None,None,None))
        else:
            temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
            self.url = 'sqlite:///' + (Path(temp.name)/'migration.db').as_posix()
        self.config = Config('alembic.ini')
        self.config.set_main_option('sqlalchemy.url', self.url.replace('%','%%'))
        command.upgrade(self.config,'20261025_22')
        self.engine = create_engine(self.url); self.addCleanup(self.engine.dispose)

    def test_upgrade_empty_safe_downgrade_and_reupgrade(self):
        command.upgrade(self.config,'head')
        names = inspect(self.engine).get_table_names()
        for table in ('targets','devices','inbox','reports','changes','push_outbox','snapshots','tickets','domain_outbox','rate_buckets','metrics'):
            self.assertIn('model_update_' + table, names)
        command.downgrade(self.config,'20261025_22')
        self.assertNotIn('model_update_devices',inspect(self.engine).get_table_names())
        command.upgrade(self.config,'head')

    def test_durable_facts_prevent_downgrade(self):
        command.upgrade(self.config,'head')
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO model_update_installations (installation_id,epoch) VALUES ('test',1)"))
        with self.assertRaisesRegex(RuntimeError,'durable facts'):
            command.downgrade(self.config,'20261025_22')
        with self.engine.connect() as connection:
            self.assertEqual(1,connection.execute(text('SELECT count(*) FROM model_update_installations')).scalar_one())

    def test_lifecycle_upgrade_preserves_existing_m111_device_and_changes(self):
        command.upgrade(self.config, '20261025_23')
        metadata = MetaData()
        installation = Table('model_update_installations', metadata, autoload_with=self.engine)
        device = Table('model_update_devices', metadata, autoload_with=self.engine)
        changes = Table('model_update_changes', metadata, autoload_with=self.engine)
        with self.engine.begin() as c:
            c.execute(installation.insert().values(installation_id='old-install', epoch=3, device_id='old-device'))
            c.execute(device.insert().values(device_id='old-device', installation_id='old-install',
                account_id='old-account', origin='https://test.example', epoch=3, revoked=False,
                capabilities={'contractVersions': [1]}, push_provider='none', token_generation=0,
                notification_permission='denied', inventory_revision=7, inventory=[{'entryId': 'retained'}],
                source_epochs={'old-source': {'epoch': 2, 'retired': True}}, sequence=4, cursor_floor=1))
            c.execute(changes.insert().values(device_id='old-device', sequence=4, update_id='old-update', payload={'old': 'fact'}))
        command.upgrade(self.config, 'head')
        device = Table('model_update_devices', MetaData(), autoload_with=self.engine)
        changes = Table('model_update_changes', MetaData(), autoload_with=self.engine)
        with self.engine.connect() as c:
            row = c.execute(select(device)).mappings().one()
            self.assertEqual((3, 7, 4, 1), tuple(row[k] for k in ('epoch', 'inventory_revision', 'sequence', 'cursor_floor')))
            self.assertEqual([{'entryId': 'retained'}], row['inventory'])
            self.assertEqual({'old-source': {'epoch': 2, 'retired': True}}, row['source_epochs'])
            self.assertEqual({}, row['lifecycle_facts']); self.assertEqual([], row['lifecycle_inventory'])
            old = c.execute(select(changes)).mappings().one()
            self.assertEqual('old-update', old['update_id']); self.assertEqual({'old': 'fact'}, old['payload'])
        self.assertTrue(changes.c.update_id.nullable)


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS') == '1','requires isolated PostgreSQL')
class UpdatePostgreSqlMigrationTests(UpdateMigrationTests):
    use_postgresql = True
