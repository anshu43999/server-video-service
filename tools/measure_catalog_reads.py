"""Local synthetic-file benchmark; never imports app.main or opens a database."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.model_catalog import ModelCatalog


async def measure(mode: str, size_mb: int, rounds: int, reuse_hashes: bool = False):
    reader = None
    if mode == 'bounded':
        from app.catalog_reads import CatalogReads
        reader = CatalogReads()
    with tempfile.TemporaryDirectory(prefix='m32-t27-catalog-') as directory:
        root = Path(directory)
        models = root / 'models'
        models.mkdir()
        artifact = models / 'fixture.bin'
        block = bytes(range(256)) * 4096
        digest = hashlib.sha256()
        with artifact.open('wb') as handle:
            for _ in range(size_mb):
                handle.write(block)
                digest.update(block)
        sha = digest.hexdigest()
        entry = dict(modelId='local-measurement', name='Local measurement', version='1.0.0',
                     scenario='test', runtime='server-pt', format='pt', path='models/fixture.bin',
                     sizeBytes=artifact.stat().st_size, sha256=sha, labels=['test'],
                     status='READY', releaseEligible=False, artifacts=[dict(artifactId='pc',
                     platform='server', format='pt', path='models/fixture.bin',
                     sizeBytes=artifact.stat().st_size, sha256=sha)])
        registry = models / 'registry.json'
        registry.write_text(json.dumps({'models': [entry]}), encoding='utf-8')
        catalog = ModelCatalog(registry)
        original_hash = catalog.sha256
        calls = 0
        def counted(path):
            nonlocal calls
            calls += 1
            return original_hash(path)
        catalog.sha256 = counted
        def inspect():
            if not reuse_hashes:
                return catalog.list_models()
            with catalog.list_read_hashes():
                return catalog.list_models()
        samples = []
        try:
            for _ in range(rounds):
                pulse = []
                stop = False
                async def heartbeat():
                    while not stop:
                        before = time.perf_counter()
                        await asyncio.sleep(.005)
                        pulse.append((time.perf_counter() - before) * 1000)
                heartbeat_task = asyncio.create_task(heartbeat())
                await asyncio.sleep(.01)
                started = time.perf_counter()
                before_calls = calls
                rows = inspect() if reader is None else await reader.run(inspect)
                duration = (time.perf_counter() - started) * 1000
                await asyncio.sleep(.01)
                stop = True
                await heartbeat_task
                assert rows[0]['hashValid'] and rows[0]['artifacts'][0]['hashValid']
                samples.append(dict(durationMs=round(duration, 3), hashCalls=calls-before_calls,
                                    maxHeartbeatGapMs=round(max(pulse), 3)))
        finally:
            if reader:
                reader.close()
        return dict(mode=mode, reuseHashes=reuse_hashes, fileMiB=size_mb, rounds=rounds, environment='local temporary synthetic bytes; OS cache not cleared; no NFS/database/camera',
                    samples=samples, medianDurationMs=round(statistics.median(s['durationMs'] for s in samples), 3),
                    maxHeartbeatGapMs=max(s['maxHeartbeatGapMs'] for s in samples))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['baseline', 'bounded'], required=True)
    parser.add_argument('--size-mb', type=int, default=64)
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--reuse-hashes', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.size_mb <= 256 or not 1 <= args.rounds <= 20:
        parser.error('bounded local benchmark: size 1..256 MiB, rounds 1..20')
    print(json.dumps(asyncio.run(measure(args.mode, args.size_mb, args.rounds, args.reuse_hashes)), indent=2))
