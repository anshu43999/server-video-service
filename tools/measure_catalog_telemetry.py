"""Local logging microbenchmark, not a production log collector benchmark."""
import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.catalog_telemetry as telemetry_module
from app.catalog_hashes import CatalogFileHashes
from app.model_catalog import ModelCatalog


def measure(rounds=1000):
    with tempfile.TemporaryDirectory(prefix='m32-t29-logs-') as directory:
        root = Path(directory)
        model = root / 'fixture.pt'
        model.write_bytes(b'temporary local hash fixture')
        hashes = CatalogFileHashes(ModelCatalog.sha256)
        hashes.digest(model)
        hashes.digest(model)
        hashes.verify()
        hashes.clear()
        logger = logging.Logger('local-catalog-measurement', logging.INFO)
        path = root / 'measurement.jsonl'
        samples = []
        with path.open('w', encoding='utf-8') as output:
            handler = logging.StreamHandler(output)
            logger.addHandler(handler)
            try:
                with patch.object(telemetry_module, 'logger', logger):
                    for index in range(rounds + 10):
                        request_id = str(uuid4())
                        started = time.perf_counter()
                        telemetry = telemetry_module.CatalogTelemetry(request_id, '/aiyoloapi/models')
                        telemetry.worker_finished('ok', .01, hashes)
                        telemetry.read_finished('ok')
                        elapsed = (time.perf_counter() - started) * 1000
                        if index >= 10:
                            samples.append(elapsed)
            finally:
                logger.removeHandler(handler)
                handler.close()
        return dict(environment='local temporary file; synchronous StreamHandler flush; no database/network/NFS',
                    rounds=rounds, warmupPairs=10, eventsPerPair=2,
                    medianPairMs=round(statistics.median(samples), 6),
                    p95PairMs=round(sorted(samples)[int(.95 * (len(samples) - 1))], 6),
                    maxPairMs=round(max(samples), 6), bytesWritten=path.stat().st_size,
                    includes='UUID validation, construction, JSON, logging and two flushes; UUID creation and hash calculation excluded')


if __name__ == '__main__':
    print(json.dumps(measure(), indent=2))
