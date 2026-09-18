import os
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path

from sqlalchemy import delete

from app.conversion import ConversionConfig, ConversionService
from app.database import ConversionConfigRecord, ConversionJobRecord, DatabaseManager
from app.config import settings


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "set RUN_POSTGRES_TESTS=1 for PostgreSQL integration")
class ConversionPostgreSqlTests(unittest.TestCase):
    def test_config_and_job_survive_service_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = DatabaseManager(settings.database_url)
            with database.session() as session:
                previous = session.get(ConversionConfigRecord, "default")
                previous_state = None if previous is None else {
                    "payload": deepcopy(previous.payload),
                }
            service = ConversionService(root, database_manager=database)
            config = ConversionConfig(mode="local", python_path=sys.executable, input_size=416)
            service.configure(config)
            service.handler = lambda job, directory, saved_config: {"ok": True, "input_size": saved_config.input_size}
            service.start()
            job = None
            try:
                job = service.submit("inspect", {"source": "postgresql-test"})
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    current = service.get(job["id"])
                    if current["status"] == "succeeded":
                        break
                    time.sleep(0.01)
                self.assertEqual(current["status"], "succeeded")
                service.close()
                restarted = ConversionService(root, database_manager=database)
                self.assertEqual(restarted.config().input_size, 416)
                self.assertEqual(restarted.get(job["id"])["result"]["input_size"], 416)
                restarted.close()
            finally:
                if service._thread is not None:
                    service.close()
                with database.session() as session:
                    if job is not None:
                        session.execute(delete(ConversionJobRecord).where(ConversionJobRecord.job_id == job["id"]))
                    config_row = session.get(ConversionConfigRecord, "default")
                    if previous_state is None:
                        if config_row is not None:
                            session.delete(config_row)
                    elif config_row is not None:
                        config_row.payload = previous_state["payload"]
                database.close()


if __name__ == "__main__":
    unittest.main()
