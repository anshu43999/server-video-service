from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


class ModelCatalog:
    def __init__(self, registry_path: Path | None = None):
        self.registry_path = registry_path or Path(__file__).resolve().parents[1] / "models" / "registry.json"

    def _load(self) -> dict[str, Any]:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save(self, registry: dict[str, Any]) -> None:
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def project_root(self) -> Path:
        return self.registry_path.parents[1]

    def register_manifest(self, manifest_path: str | Path) -> list[dict[str, Any]]:
        """Register conversion artifacts after validating their manifest hashes.

        Only manifests and artifacts under the project models directory are accepted;
        this prevents the admin endpoint from turning into an arbitrary file scanner.
        """
        candidate = Path(manifest_path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        candidate = candidate.resolve()
        models_root = (self.project_root / "models").resolve()
        if models_root not in candidate.parents or candidate.suffix.lower() != ".json":
            raise ValueError("manifest must be a JSON file under the models directory")
        if not candidate.is_file():
            raise ValueError("manifest file does not exist")
        manifest = json.loads(candidate.read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("manifest contains no artifacts")
        registry = self._load()
        existing = registry.setdefault("models", [])
        registered: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("format") not in {"pt", "onnx", "tflite"}:
                continue
            artifact_path = Path(str(artifact.get("path", "")))
            if not artifact_path.is_absolute():
                artifact_path = self.project_root / artifact_path
            artifact_path = artifact_path.resolve()
            if models_root not in artifact_path.parents or not artifact_path.is_file():
                raise ValueError(f"artifact is missing or outside models directory: {artifact_path}")
            actual_hash = self.sha256(artifact_path)
            if actual_hash != str(artifact.get("sha256", "")).upper():
                raise ValueError(f"artifact SHA-256 mismatch: {artifact_path.name}")
            relative_path = artifact_path.relative_to(self.project_root).as_posix()
            stem = re.sub(r"[^A-Za-z0-9]+", "-", artifact_path.stem).strip("-").lower() or "model"
            model_id = f"converted-{stem}-{artifact['format']}"
            item = {
                "modelId": model_id,
                "name": f"Converted {artifact_path.stem}",
                "purpose": manifest.get("purpose", "development"),
                "format": artifact["format"],
                "path": relative_path,
                "sizeBytes": artifact_path.stat().st_size,
                "sha256": actual_hash,
                "inputSize": manifest.get("conversion", {}).get("imgsz"),
                "classCount": manifest.get("classCount"),
                "labelsPath": manifest.get("labelsPath"),
                "source": manifest.get("sourceWeights", {}).get("path"),
                "sourceSha256": manifest.get("sourceWeights", {}).get("sha256"),
                "manifestPath": candidate.relative_to(self.project_root).as_posix(),
                "releaseEligible": bool(manifest.get("releaseEligible", False)),
                "licenseStatus": manifest.get("licenseStatus", "requires-review"),
            }
            old = next((entry for entry in existing if entry.get("modelId") == model_id), None)
            if old is None:
                existing.append(item)
            else:
                old.update(item)
            registered.append(self.inspect(item, registry.get("activeServerModel")))
        if not registered:
            raise ValueError("manifest has no supported model artifacts")
        registry["updatedAt"] = date.today().isoformat()
        self._save(registry)
        return registered

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()

    def inspect(self, item: dict[str, Any], active_name: str | None = None) -> dict[str, Any]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = self.registry_path.parents[1] / path
        exists = path.is_file()
        actual_hash = self.sha256(path) if exists else None
        return {
            **item,
            "path": str(path),
            "exists": exists,
            "hashValid": exists and actual_hash == item.get("sha256"),
            "actualSha256": actual_hash,
            "active": active_name == path.name,
        }

    def list_models(self) -> list[dict[str, Any]]:
        registry = self._load()
        return [self.inspect(item, registry.get("activeServerModel")) for item in registry.get("models", [])]

    def get(self, model_id: str) -> dict[str, Any]:
        registry = self._load()
        for item in registry.get("models", []):
            if item.get("modelId") == model_id:
                return self.inspect(item, registry.get("activeServerModel"))
        raise KeyError(model_id)

    def activate(self, model_id: str) -> dict[str, Any]:
        registry = self._load()
        target = next((item for item in registry.get("models", []) if item.get("modelId") == model_id), None)
        if target is None:
            raise KeyError(model_id)
        inspected = self.inspect(target, registry.get("activeServerModel"))
        if not inspected["exists"]:
            raise ValueError("model file does not exist")
        if not inspected["hashValid"]:
            raise ValueError("model SHA-256 does not match registry")
        if target.get("format") not in {"pt", "onnx"}:
            raise ValueError("only server model formats pt and onnx can be activated")
        registry["activeServerModel"] = Path(target["path"]).name
        self._save(registry)
        return self.inspect(target, registry["activeServerModel"])

    def active_server_path(self) -> str:
        registry = self._load()
        active = registry.get("activeServerModel")
        for item in registry.get("models", []):
            if item.get("path", "").endswith(str(active)) and item.get("format") in {"pt", "onnx"}:
                return str((self.registry_path.parents[1] / item["path"]).resolve())
        return str((self.registry_path.parents[1] / "models" / "yolo11n.pt").resolve())
