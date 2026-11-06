import os
from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


class LifecycleMigrationTests(unittest.TestCase):
    def setUp(self):
        if getattr(self,'use_postgresql',False):
            from postgresql_support import isolated_postgresql_url
            pg=isolated_postgresql_url('m112_migration',revision='20261022_21')
            self.url=pg.__enter__();self.addCleanup(lambda:pg.__exit__(None,None,None))
        else:
            temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
            self.url=f'sqlite:///{(Path(temp.name)/"migration.db").as_posix()}'
        self.config=Config('alembic.ini')
        self.config.set_main_option('sqlalchemy.url',self.url.replace('%','%%'))
        command.upgrade(self.config,'20261022_21')
        self.engine=create_engine(self.url);self.addCleanup(self.engine.dispose)

    def test_additive_upgrade_empty_downgrade_and_reupgrade(self):
        command.upgrade(self.config,'head')
        self.assertIn('deleted_at',{col['name'] for col in inspect(self.engine).get_columns('project_scenes')})
        self.assertIn('resource_lifecycle_operations',inspect(self.engine).get_table_names())
        command.downgrade(self.config,'20261022_21')
        self.assertNotIn('resource_lifecycle_operations',inspect(self.engine).get_table_names())
        command.upgrade(self.config,'head')

    def test_downgrade_refuses_durable_event_and_preserves_it(self):
        command.upgrade(self.config,'head')
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO resource_lifecycle_events "
                "(event_id,scope_key,lifecycle_revision,payload) VALUES ('test','scene:test/s',2,'{}')"))
        with self.assertRaisesRegex(RuntimeError,'durable facts'):
            command.downgrade(self.config,'20261022_21')
        with self.engine.connect() as connection:
            self.assertEqual(1,connection.execute(text('SELECT COUNT(*) FROM resource_lifecycle_events')).scalar_one())


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','requires isolated PostgreSQL')
class LifecyclePostgreSqlMigrationTests(LifecycleMigrationTests):
    use_postgresql=True
