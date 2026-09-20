import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.model_catalog import ModelCatalog
from app.model_seed import ModelSeedError, seed_model_catalog


def _artifact(model_id: str, filename: str, content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest().upper()
    return {
        "modelId": model_id,
        "name": model_id,
        "version": "1.0.0",
        "scenario": "test",
        "purpose": "development",
        "format": "onnx",
        "path": f"models/{filename}",
        "sizeBytes": len(content),
        "sha256": digest,
        "runtime": "server-onnx",
        "labels": ["object"],
        "compatibleDevices": [],
        "artifacts": [{
            "artifactId": "server-onnx",
            "format": "onnx",
            "platform": "server",
            "path": f"models/{filename}",
            "sizeBytes": len(content),
            "sha256": digest,
            "contentType": "application/octet-stream",
        }],
    }


def _write_registry(models_root: Path, models: list[dict], active: str | None = None) -> None:
    models_root.mkdir(parents=True, exist_ok=True)
    (models_root / "registry.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "registryType": "server-video-service-models",
            "updatedAt": None,
            "activeServerModel": active,
            "models": models,
        }),
        encoding="utf-8",
    )


class ModelSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.seed = root / "seed" / "models"
        self.target = root / "runtime" / "models"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_imports_seed_and_does_not_activate_it(self) -> None:
        content = b"checked-in-model"
        self.seed.mkdir(parents=True)
        (self.seed / "seed.onnx").write_bytes(content)
        _write_registry(self.seed, [_artifact("seed-v1", "seed.onnx", content)], "seed-v1")
        _write_registry(self.target, [])

        result = seed_model_catalog(self.seed, self.target)

        self.assertEqual((1, 0, 1), (result.imported_models, result.preserved_models, result.copied_files))
        self.assertEqual(content, (self.target / "seed.onnx").read_bytes())
        registry = json.loads((self.target / "registry.json").read_text(encoding="utf-8"))
        self.assertIsNone(registry["activeServerModel"])
        self.assertEqual(["seed-v1"], [item["modelId"] for item in registry["models"]])
        ModelCatalog(self.target / "registry.json").validate_startup()

    def test_repeat_import_preserves_existing_models_and_active_selection(self) -> None:
        seed_content = b"seed"
        user_content = b"user"
        self.seed.mkdir(parents=True)
        (self.seed / "seed.onnx").write_bytes(seed_content)
        _write_registry(self.seed, [_artifact("seed-v1", "seed.onnx", seed_content)])
        self.target.mkdir(parents=True)
        (self.target / "user.onnx").write_bytes(user_content)
        _write_registry(
            self.target,
            [_artifact("user-v1", "user.onnx", user_content)],
            "user-v1",
        )

        first = seed_model_catalog(self.seed, self.target)
        second = seed_model_catalog(self.seed, self.target)

        self.assertEqual(1, first.imported_models)
        self.assertEqual(0, second.imported_models)
        self.assertEqual(2, second.preserved_models)
        registry = json.loads((self.target / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual("user-v1", registry["activeServerModel"])
        self.assertEqual({"user-v1", "seed-v1"}, {item["modelId"] for item in registry["models"]})

    def test_new_seed_version_is_added_without_replacing_existing_version(self) -> None:
        original = b"original"
        updated = b"updated"
        self.seed.mkdir(parents=True)
        (self.seed / "v1.onnx").write_bytes(original)
        _write_registry(self.seed, [_artifact("seed-v1", "v1.onnx", original)])
        seed_model_catalog(self.seed, self.target)

        (self.seed / "v1.onnx").write_bytes(b"changed seed file")
        (self.seed / "v2.onnx").write_bytes(updated)
        _write_registry(self.seed, [
            _artifact("seed-v1", "v1.onnx", b"changed seed file"),
            _artifact("seed-v2", "v2.onnx", updated),
        ])

        result = seed_model_catalog(self.seed, self.target)

        self.assertEqual(1, result.imported_models)
        self.assertEqual(original, (self.target / "v1.onnx").read_bytes())
        self.assertEqual(updated, (self.target / "v2.onnx").read_bytes())
        self.assertEqual(
            {"seed-v1", "seed-v2"},
            {item["modelId"] for item in ModelCatalog(self.target / "registry.json").list_models()},
        )

    def test_model_mount_without_registry_is_optional(self) -> None:
        self.seed.mkdir(parents=True)
        (self.seed / "custom.onnx").write_bytes(b"custom")

        result = seed_model_catalog(self.seed, self.target)

        self.assertEqual((0, 0), (result.imported_models, result.copied_files))
        self.assertFalse((self.target / "registry.json").exists())

    def test_refuses_to_overwrite_different_existing_file(self) -> None:
        seed_content = b"seed"
        self.seed.mkdir(parents=True)
        (self.seed / "shared.onnx").write_bytes(seed_content)
        _write_registry(self.seed, [_artifact("seed-v1", "shared.onnx", seed_content)])
        self.target.mkdir(parents=True)
        (self.target / "shared.onnx").write_bytes(b"different")
        _write_registry(self.target, [])

        with self.assertRaisesRegex(ModelSeedError, "different data"):
            seed_model_catalog(self.seed, self.target)
        self.assertEqual([], json.loads((self.target / "registry.json").read_text())["models"])

    def test_rejects_invalid_seed_before_copying(self) -> None:
        content = b"seed"
        self.seed.mkdir(parents=True)
        (self.seed / "seed.onnx").write_bytes(content)
        model = _artifact("seed-v1", "seed.onnx", content)
        model["artifacts"][0]["sha256"] = "0" * 64
        _write_registry(self.seed, [model])
        _write_registry(self.target, [])

        with self.assertRaisesRegex(ModelSeedError, "validation failed"):
            seed_model_catalog(self.seed, self.target)
        self.assertFalse((self.target / "seed.onnx").exists())

    def test_rejects_primary_hash_mismatch_even_if_artifact_is_valid(self) -> None:
        content = b"seed"
        self.seed.mkdir(parents=True)
        (self.seed / "seed.onnx").write_bytes(content)
        model = _artifact("seed-v1", "seed.onnx", content)
        model["sha256"] = "0" * 64
        _write_registry(self.seed, [model])

        with self.assertRaisesRegex(ModelSeedError, "invalid primary hash"):
            seed_model_catalog(self.seed, self.target)
        self.assertFalse((self.target / "seed.onnx").exists())


if __name__ == "__main__":
    unittest.main()
