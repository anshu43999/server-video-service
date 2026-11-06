import importlib.util
import pathlib
import unittest
from unittest.mock import patch


class MobileDispositionMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_are_symmetric(self):
        path = pathlib.Path("alembic/versions/20261019_15_mobile_disposition_idempotency.py")
        spec = importlib.util.spec_from_file_location("mobile_disposition_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        class Inspector:
            def __init__(self):
                self.columns = set()
                self.indexes = set()
            def get_columns(self, table): return [{"name": name} for name in self.columns]
            def get_indexes(self, table): return [{"name": name} for name in self.indexes]
            def get_unique_constraints(self, table): return []
        inspector = Inspector()
        def add_column(table, column):
            calls.append(("add", table, column.name))
            inspector.columns.add(column.name)
        def create_index(name, table, columns, unique):
            calls.append(("unique-index", name, table, tuple(columns), unique))
            inspector.indexes.add(name)
        def drop_index(name, table_name):
            calls.append(("drop-index", name, table_name))
            inspector.indexes.remove(name)
        with (
            patch.object(module.op, "get_bind", return_value=object()),
            patch.object(module.sa, "inspect", return_value=inspector),
            patch.object(module.op, "add_column", side_effect=add_column),
            patch.object(module.op, "create_index", side_effect=create_index),
            patch.object(module.op, "drop_index", side_effect=drop_index),
            patch.object(module.op, "drop_column", side_effect=lambda table, name: calls.append(("drop", table, name))),
        ):
            module.upgrade()
            module.downgrade()
        self.assertIn(("add", "alert_disposition_actions", "operation_id"), calls)
        self.assertIn(("add", "alert_disposition_actions", "request_digest"), calls)
        self.assertIn(("unique-index", "uq_alert_disposition_operation", "alert_disposition_actions",
                       ("project_id", "event_id", "operation_id"), True), calls)
        self.assertIn(("drop-index", "uq_alert_disposition_operation", "alert_disposition_actions"), calls)
        self.assertIn(("drop", "alert_disposition_actions", "operation_id"), calls)


if __name__ == "__main__":
    unittest.main()
