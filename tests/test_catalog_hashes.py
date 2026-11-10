import hashlib
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.catalog_hashes import CatalogFileChanged, CatalogFileHashes
from app.model_catalog import ModelCatalog


class CatalogHashesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='m32-t28-hashes-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        models = self.root / 'models'
        models.mkdir()
        self.path = models / 'fixture.pt'
        self.path.write_bytes(b'original model bytes')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.entry = dict(modelId='fixture', name='Fixture', version='1.0.0',
                          format='pt', path='models/fixture.pt', sha256=digest,
                          sizeBytes=self.path.stat().st_size, status='READY',
                          artifacts=[dict(artifactId='server', platform='server',
                              format='pt', path='models/fixture.pt', sha256=digest,
                              sizeBytes=self.path.stat().st_size)])
        registry = models / 'registry.json'
        registry.write_text(json.dumps({'models': [self.entry]}), encoding='utf-8')
        self.catalog = ModelCatalog(registry)

    def test_one_full_hash_per_file_and_new_scope_rehashes(self):
        with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
            for count in (1, 2):
                with self.catalog.list_read_hashes():
                    result = self.catalog.list_models()[0]
                    self.assertTrue(result['hashValid'])
                    self.assertTrue(result['artifacts'][0]['hashValid'])
                self.assertEqual(count, compute.call_count)

    def test_opt_in_does_not_change_unscoped_inspections_or_response(self):
        with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
            original = self.catalog.list_models()
            self.assertEqual(2, compute.call_count)
            with self.catalog.list_read_hashes():
                self.assertEqual(original, self.catalog.list_models())
            self.assertEqual(3, compute.call_count)
            self.catalog.get('fixture')
            self.assertEqual(5, compute.call_count)

    def test_scope_reuses_digest_across_entries_but_not_validation_decisions(self):
        second = json.loads(json.dumps(self.entry))
        second.update(modelId='other-reference', sha256='0' * 64)
        self.catalog.registry_path.write_text(
            json.dumps({'models': [self.entry, second]}), encoding='utf-8')
        with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
            with self.catalog.list_read_hashes():
                rows = self.catalog.list_models()
            self.assertEqual(1, compute.call_count)
            self.assertTrue(rows[0]['hashValid'])
            self.assertFalse(rows[1]['hashValid'])
            self.assertTrue(rows[1]['artifacts'][0]['hashValid'])

    def test_startup_and_publication_rehash_after_successful_list_scope(self):
        entry = self.entry
        entry.update(scenario='fixture', runtime='server-pt', labels=['test'],
                     supportedTargets=['pc'], sourceSha256=entry['sha256'],
                     serverValidated=True, serverValidationSha256=entry['sha256'])
        self.catalog.registry_path.write_text(json.dumps({'models': [entry]}), encoding='utf-8')
        self.catalog.validate_startup()
        with self.catalog.list_read_hashes():
            self.assertTrue(self.catalog.list_models()[0]['serverReady'])
        info = self.path.stat()
        self.path.write_bytes(b'x' * info.st_size)
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.catalog.validate_startup()
        with self.assertRaisesRegex(ValueError, 'model_target_not_ready'):
            self.catalog.publish_release('fixture', '1.0.0', ['pc'],
                license_approved=True, reason='local integrity test', actor='fixture')
        with self.assertRaises(ValueError):
            self.catalog.resolve_server_model('fixture', '1.0.0')

    def test_each_reference_checks_its_own_expected_hash_and_size(self):
        for field, value in (('sha256', '0' * 64), ('sizeBytes', 1)):
            with self.subTest(field=field):
                item = json.loads(json.dumps(self.entry))
                item['artifacts'][0][field] = value
                with self.catalog.list_read_hashes():
                    result = self.catalog.inspect(item)
                self.assertTrue(result['hashValid'])
                self.assertFalse(result['artifacts'][0]['hashValid'])
                item = json.loads(json.dumps(self.entry))
                item[field] = value
                with self.catalog.list_read_hashes():
                    result = self.catalog.inspect(item)
                self.assertFalse(result['hashValid'])
                self.assertTrue(result['artifacts'][0]['hashValid'])

    def test_different_files_with_same_content_are_independently_hashed(self):
        second = self.path.with_name('other.pt')
        second.write_bytes(self.path.read_bytes())
        item = json.loads(json.dumps(self.entry))
        item['artifacts'][0]['path'] = 'models/other.pt'
        with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
            with self.catalog.list_read_hashes():
                self.catalog.inspect(item)
            self.assertEqual(2, compute.call_count)

    def test_missing_file_remains_invalid_without_cached_success(self):
        with self.catalog.list_read_hashes():
            self.assertTrue(self.catalog.inspect(self.entry)['hashValid'])
        self.path.unlink()
        with self.catalog.list_read_hashes():
            result = self.catalog.inspect(self.entry)
        self.assertFalse(result['exists'])
        self.assertFalse(result['hashValid'])

    def test_same_size_tamper_with_restored_mtime_is_rejected_before_reuse(self):
        with self.assertRaises(CatalogFileChanged):
            with self.catalog.list_read_hashes():
                self.catalog.inspect(self.entry)
                info = self.path.stat()
                self.path.write_bytes(b'x' * info.st_size)
                os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
                self.catalog.inspect(self.entry)

    def test_next_request_rehashes_same_size_tamper_with_restored_mtime(self):
        with self.catalog.list_read_hashes():
            self.catalog.inspect(self.entry)
        info = self.path.stat()
        self.path.write_bytes(b'x' * info.st_size)
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.catalog.list_read_hashes():
            result = self.catalog.inspect(self.entry)
        self.assertFalse(result['hashValid'])
        self.assertFalse(result['artifacts'][0]['hashValid'])

    def test_file_replacement_with_same_size_and_mtime_is_rejected(self):
        with self.assertRaises(CatalogFileChanged):
            with self.catalog.list_read_hashes():
                self.catalog.inspect(self.entry)
                info = self.path.stat()
                replacement = self.path.with_name('replacement.pt')
                replacement.write_bytes(b'x' * info.st_size)
                os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
                os.replace(replacement, self.path)
                self.catalog.inspect(self.entry)

    def test_change_during_hash_is_rejected(self):
        original = self.catalog.sha256
        def mutate(path):
            digest = original(path)
            path.write_bytes(b'x' * path.stat().st_size)
            return digest
        with patch.object(self.catalog, 'sha256', mutate):
            with self.assertRaises(CatalogFileChanged):
                with self.catalog.list_read_hashes():
                    self.catalog.inspect(self.entry)

    def test_final_guard_rejects_changes_after_last_digest(self):
        for change in ('delete', 'tamper'):
            with self.subTest(change=change):
                self.path.write_bytes(b'original model bytes')
                with self.assertRaises(CatalogFileChanged):
                    with self.catalog.list_read_hashes():
                        self.catalog.inspect(self.entry)
                        if change == 'delete':
                            self.path.unlink()
                        else:
                            self.path.write_bytes(b'x' * self.path.stat().st_size)

    def test_exception_clears_scope_and_next_read_hashes_again(self):
        with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
            with self.assertRaisesRegex(ValueError, 'fixture'):
                with self.catalog.list_read_hashes():
                    self.catalog.inspect(self.entry)
                    raise ValueError('fixture')
            self.catalog.inspect(self.entry)
            self.assertEqual(3, compute.call_count)

    def test_overlapping_worker_scopes_do_not_share_digests(self):
        barrier = threading.Barrier(2)
        original = self.catalog.sha256
        def compute(path):
            barrier.wait(timeout=3)
            return original(path)
        def inspect():
            with self.catalog.list_read_hashes():
                return self.catalog.inspect(self.entry)['hashValid']
        with patch.object(self.catalog, 'sha256', side_effect=compute) as counted:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: inspect(), range(2)))
            self.assertEqual([True, True], results)
            self.assertEqual(2, counted.call_count)

    def test_unknown_change_time_falls_back_to_full_hashes(self):
        with patch('app.catalog_hashes._change_time', return_value=None):
            with patch.object(self.catalog, 'sha256', wraps=self.catalog.sha256) as compute:
                with self.catalog.list_read_hashes():
                    self.assertTrue(self.catalog.inspect(self.entry)['hashValid'])
                self.assertEqual(3, compute.call_count)

    def test_failed_hash_is_not_cached(self):
        with patch.object(self.catalog, 'sha256', side_effect=[OSError('fixture'), 'digest']) as compute:
            hashes = CatalogFileHashes(compute)
            with self.assertRaises(CatalogFileChanged):
                hashes.digest(self.path)
            self.assertEqual('digest', hashes.digest(self.path))
            self.assertEqual(2, compute.call_count)
