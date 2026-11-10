"""Measure real ASGI routes with temporary model files and in-memory auth only."""
import os
os.environ['DATABASE_URL'] = ''
os.environ['RUN_POSTGRES_TESTS'] = '0'
os.environ['APP_APK_WORKER_ENABLED'] = 'false'
os.environ['APP_APK_EXTERNAL_ENABLED'] = 'false'

import asyncio
import hashlib
import json
import statistics
import sys
import time
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'tests')]
import httpx
import app.main as main
from test_project_model_assignments import ModelApiFixture


class Fixture(ModelApiFixture, unittest.TestCase):
    pass


async def measure(fixture):
    results = []
    hashes = 0
    original_hash = main.model_catalog.sha256
    def counted(path):
        nonlocal hashes
        hashes += 1
        return original_hash(path)
    # The fixture owns this catalog; no process-global production object changes.
    main.model_catalog.sha256 = counted
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://local-test') as client:
        for _ in range(5):
            before_hashes = hashes
            started = time.perf_counter()
            async def catalog():
                response = await client.get('/aiyoloapi/models', headers=fixture.headers)
                assert response.status_code == 200, response.status_code
                assert response.json()['models'][0]['hashValid']
                return (time.perf_counter() - started) * 1000
            async def unrelated():
                await asyncio.sleep(.005)
                response = await client.get('/aiyoloapi/auth/status')
                assert response.status_code == 200
                return (time.perf_counter() - started) * 1000
            catalog_ms, unrelated_ms = await asyncio.gather(catalog(), unrelated())
            results.append(dict(catalogMs=round(catalog_ms, 3), unrelatedCompletionMs=round(unrelated_ms, 3),
                                hashCalls=hashes-before_hashes))
    return dict(environment='local actual ASGI routes, temporary 64 MiB synthetic artifact, memory auth; no network/NFS/database', samples=results,
                medianCatalogMs=round(statistics.median(r['catalogMs'] for r in results), 3),
                medianUnrelatedCompletionMs=round(statistics.median(r['unrelatedCompletionMs'] for r in results), 3))


if __name__ == '__main__':
    fixture = Fixture()
    try:
        fixture.setUp()
        catalog = main.model_catalog
        entry = fixture.entries[0]
        path = catalog.project_root / entry['path']
        block = bytes(range(256)) * 4096
        digest = hashlib.sha256()
        with path.open('wb') as handle:
            for _ in range(64):
                handle.write(block); digest.update(block)
        entry.update(sizeBytes=path.stat().st_size, sha256=digest.hexdigest())
        entry['artifacts'] = [dict(entry['artifacts'][0], sizeBytes=entry['sizeBytes'], sha256=entry['sha256'])]
        catalog.registry_path.write_text(json.dumps({'models': [entry]}), encoding='utf-8')
        print(json.dumps(asyncio.run(measure(fixture)), indent=2))
    finally:
        fixture.doCleanups()
