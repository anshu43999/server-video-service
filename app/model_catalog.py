from __future__ import annotations

import hashlib
import json
import re
import threading
from functools import wraps
from datetime import date
from pathlib import Path
from typing import Any

from .conversion import atomic_json

_mutation_lock = threading.RLock()


def serialized_mutation(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        with _mutation_lock:
            return method(*args, **kwargs)
    return wrapper


class ModelCatalogValidationError(ValueError):
    """Raised when the catalog cannot be safely used by the service."""


class ModelCatalog:
    def __init__(self, registry_path: Path | None = None):
        self.registry_path = registry_path or Path(__file__).resolve().parents[1] / "models" / "registry.json"

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ModelCatalogValidationError(
                f"model catalog unavailable: {self.registry_path.name}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ModelCatalogValidationError(
                f"model catalog contains invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ModelCatalogValidationError("model catalog root must be an object")
        return payload

    def _save(self, registry: dict[str, Any]) -> None:
        atomic_json(self.registry_path, registry)

    @property
    def project_root(self) -> Path:
        return self.registry_path.parents[1]

    def _artifact_path(self, artifact: dict[str, Any]) -> Path:
        raw_path = artifact.get("path") or artifact.get("repositoryPath")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ModelCatalogValidationError("artifact path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.project_root / path
        resolved = path.resolve()
        models_root = (self.project_root / "models").resolve()
        if models_root != resolved and models_root not in resolved.parents:
            raise ModelCatalogValidationError("artifact path must stay under the models directory")
        return resolved

    def validate_startup(self) -> None:
        """Fail fast if any registered model artifact is missing or altered.

        Startup validation deliberately raises instead of dropping invalid entries or
        falling back to a default model. This keeps the single registry authoritative.
        """
        registry = self._load()
        models = registry.get("models")
        if not isinstance(models, list):
            raise ModelCatalogValidationError("model catalog field 'models' must be an array")
        errors: list[str] = []
        seen: set[str] = set()
        for index, model in enumerate(models):
            prefix = f"models[{index}]"
            if not isinstance(model, dict):
                errors.append(f"{prefix} must be an object")
                continue
            model_id = model.get("modelId")
            if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model_id):
                errors.append(f"{prefix}.modelId is invalid")
            elif model_id in seen:
                errors.append(f"duplicate modelId: {model_id}")
            else:
                seen.add(model_id)
            for field in ("version", "scenario", "runtime", "labels"):
                value = model.get(field)
                if field == "labels":
                    valid = isinstance(value, list) and all(isinstance(label, str) and label for label in value)
                else:
                    valid = isinstance(value, str) and bool(value.strip())
                if not valid:
                    errors.append(f"{prefix}.{field} is required")
            artifacts = model.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                errors.append(f"{prefix}.artifacts must contain at least one artifact")
                continue
            artifact_ids: set[str] = set()
            for artifact_index, artifact in enumerate(artifacts):
                aprefix = f"{prefix}.artifacts[{artifact_index}]"
                if not isinstance(artifact, dict):
                    errors.append(f"{aprefix} must be an object")
                    continue
                artifact_id = artifact.get("artifactId")
                if not isinstance(artifact_id, str) or not artifact_id:
                    errors.append(f"{aprefix}.artifactId is required")
                elif artifact_id in artifact_ids:
                    errors.append(f"duplicate artifactId in {model_id}: {artifact_id}")
                else:
                    artifact_ids.add(artifact_id)
                declared_size = artifact.get("sizeBytes")
                declared_hash = str(artifact.get("sha256", ""))
                if not isinstance(declared_size, int) or declared_size < 0:
                    errors.append(f"{aprefix}.sizeBytes is invalid")
                if not re.fullmatch(r"[0-9A-Fa-f]{64}", declared_hash):
                    errors.append(f"{aprefix}.sha256 is invalid")
                try:
                    path = self._artifact_path(artifact)
                    if not path.is_file():
                        errors.append(f"{aprefix} artifact missing: {artifact.get('path', artifact.get('repositoryPath'))}")
                        continue
                    if isinstance(declared_size, int) and path.stat().st_size != declared_size:
                        errors.append(f"{aprefix} size mismatch: expected {declared_size}, actual {path.stat().st_size}")
                    if re.fullmatch(r"[0-9A-Fa-f]{64}", declared_hash):
                        actual_hash = self.sha256(path)
                        if actual_hash.lower() != declared_hash.lower():
                            errors.append(f"{aprefix} SHA-256 mismatch: expected {declared_hash}, actual {actual_hash}")
                except OSError as exc:
                    errors.append(f"{aprefix} cannot be checked: {exc}")
        if errors:
            raise ModelCatalogValidationError("model catalog validation failed: " + "; ".join(errors))

    @serialized_mutation
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
                "version": manifest.get("version", "dev"),
                "scenario": manifest.get("scenario", "general-detection"),
                "runtime": "android-tflite" if artifact["format"] == "tflite" else f"server-{artifact['format']}",
                "labels": manifest.get("labels", []),
                "compatibleDevices": manifest.get("compatibleDevices", []),
                "artifacts": [{
                    "artifactId": artifact.get("artifactId", f"{artifact['format']}-artifact"),
                    "format": artifact["format"],
                    "platform": "android" if artifact["format"] == "tflite" else "server",
                    "path": relative_path,
                    "sizeBytes": artifact_path.stat().st_size,
                    "sha256": actual_hash,
                    "contentType": "application/octet-stream",
                }],
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
        inspected_artifacts = []
        for artifact in item.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_copy = dict(artifact)
            artifact_path = self._artifact_path(artifact)
            artifact_copy["url"] = f"/api/models/{item.get('modelId')}/artifacts/{artifact.get('artifactId')}/download"
            artifact_copy["exists"] = artifact_path.is_file()
            artifact_copy["hashValid"] = artifact_copy["exists"] and self.sha256(artifact_path).lower() == str(artifact.get("sha256", "")).lower()
            artifact_copy.pop("path", None)
            inspected_artifacts.append(artifact_copy)
        result = {
            **item,
            "path": str(path),
            "exists": exists,
            "hashValid": exists and actual_hash == item.get("sha256"),
            "actualSha256": actual_hash,
            "active": active_name == path.name,
        }
        if inspected_artifacts:
            result["artifacts"] = inspected_artifacts
        return result

    def list_models(self) -> list[dict[str, Any]]:
        registry = self._load()
        return [self.public_inspect(item, registry.get("activeServerModel")) for item in registry.get("models", [])]

    def get(self, model_id: str) -> dict[str, Any]:
        registry = self._load()
        for item in registry.get("models", []):
            if item.get("modelId") == model_id:
                return self.public_inspect(item, registry.get("activeServerModel"))
        raise KeyError(model_id)

    def get_artifact(self, model_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        """Resolve a registered artifact for download without exposing its path.

        The returned file is revalidated immediately before serving.  A changed
        or missing artifact is rejected rather than streaming bytes that cannot
        satisfy the catalog's advertised size/hash contract.
        """
        registry = self._load()
        model = next((entry for entry in registry.get("models", []) if entry.get("modelId") == model_id), None)
        if model is None:
            raise KeyError(model_id)
        artifact = next((item for item in model.get("artifacts", []) if isinstance(item, dict) and item.get("artifactId") == artifact_id), None)
        if artifact is None:
            raise KeyError(f"{model_id}/{artifact_id}")
        path = self._artifact_path(artifact)
        if not path.is_file():
            raise ValueError("artifact is not available")
        expected_size = artifact.get("sizeBytes")
        expected_hash = str(artifact.get("sha256", ""))
        actual_size = path.stat().st_size
        actual_hash = self.sha256(path)
        if actual_size != expected_size or actual_hash.lower() != expected_hash.lower():
            raise ValueError("artifact integrity check failed")
        return artifact, path

    def public_inspect(self, item: dict[str, Any], active_name: str | None = None) -> dict[str, Any]:
        """Return the API-safe representation of a catalog entry.

        Registry paths are implementation details and must never cross the API
        boundary.  This method deliberately projects the internal inspection
        result to the frozen M09-T01 contract and retains only URL-based artifact
        references.  ``exists`` and ``hashValid`` are useful operational status
        fields and do not expose filesystem locations.
        """
        inspected = self.inspect(item, active_name)
        artifacts = inspected.get("artifacts", [])
        public_artifacts: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            allowed = {
                key: artifact[key]
                for key in ("artifactId", "format", "platform", "url", "sizeBytes", "sha256", "contentType", "exists", "hashValid")
                if key in artifact
            }
            public_artifacts.append(allowed)
        primary = public_artifacts[0] if public_artifacts else {}
        result: dict[str, Any] = {
            "modelId": inspected.get("modelId"),
            "name": inspected.get("name", inspected.get("modelId")),
            "version": inspected.get("version"),
            "scenario": inspected.get("scenario"),
            "purpose": inspected.get("purpose"),
            "runtime": inspected.get("runtime"),
            "labels": inspected.get("labels", []),
            "compatibleDevices": inspected.get("compatibleDevices", []),
            "license": inspected.get("license", {}),
            "artifacts": public_artifacts,
            "releaseEligible": bool(inspected.get("releaseEligible", False)),
            "exists": bool(inspected.get("exists", False)),
            "hashValid": bool(inspected.get("hashValid", False)),
            "active": bool(inspected.get("active", False)),
            "inputSize": inspected.get("inputSize"),
            "serverReady": inspected.get("serverReady", False),
            "androidReady": inspected.get("androidReady", False),
            "androidConverted": inspected.get("androidConverted", inspected.get("androidReady", False)),
            "signatureStatus": inspected.get("signatureStatus", "unsigned"),
            "androidContract": inspected.get("androidContract"),
            "placeholder": bool(inspected.get("placeholder", False)),
        }
        # Android M14 clients consume these aliases while newer clients use the
        # complete artifacts array.  Keep them aligned with the first artifact.
        for key in ("format", "sizeBytes", "sha256"):
            if key in primary:
                result[key] = primary[key]
        if "url" in primary:
            result["downloadUrl"] = primary["url"]
        return result

    @serialized_mutation
    def activate(self, model_id: str) -> dict[str, Any]:
        registry = self._load()
        target = next((item for item in registry.get("models", []) if item.get("modelId") == model_id), None)
        if target is None:
            raise KeyError(model_id)
        if target.get("placeholder"):
            raise ValueError("placeholder models cannot be activated")
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

    def resolve_server_model(self, model_id: str) -> tuple[dict[str, Any], Path]:
        """Resolve a registered, hash-valid PT/ONNX model for a stream binding.

        TFLite/mobile-only entries are deliberately rejected so a stream can never
        switch to an artifact that the server detector cannot load.
        """
        registry = self._load()
        item = next((entry for entry in registry.get("models", []) if entry.get("modelId") == model_id), None)
        if item is None:
            raise KeyError(model_id)
        if item.get("format") not in {"pt", "onnx"}:
            raise ValueError("model is not a server runtime artifact")
        if item.get("placeholder"):
            raise ValueError("placeholder models cannot be used for inference")
        path = self._artifact_path(item)
        if not path.is_file():
            raise ValueError("model file does not exist")
        expected_hash = str(item.get("sha256", ""))
        expected_size = item.get("sizeBytes")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            raise ValueError("model size does not match registry")
        if expected_hash and self.sha256(path).lower() != expected_hash.lower():
            raise ValueError("model SHA-256 does not match registry")
        return item, path

    @serialized_mutation
    def publish_upload(self, model_id: str, metadata: dict, result: dict, path: Path, platform: str) -> dict:
        """Append validated artifacts to a single logical model version; never auto-activate."""
        registry = self._load()
        entries = registry.setdefault("models", [])
        item = next((row for row in entries if row["modelId"] == model_id), None)
        relative = path.resolve().relative_to((self.project_root / "models").resolve())
        relative_path = "models/" + relative.as_posix()
        digest = self.sha256(path)
        if platform == "android" and (digest.lower() != result["sha256"].lower() or path.stat().st_size != result["sizeBytes"]):
            raise ValueError("移动端产物与转换验证结果不一致")
        artifact = {"artifactId": "server-pt" if platform == "server" else "android-int8",
                    "format": "pt" if platform == "server" else "tflite", "platform": platform,
                    "path": relative_path, "sizeBytes": path.stat().st_size, "sha256": digest,
                    "contentType": "application/octet-stream"}
        if platform == "server":
            if item and item["sha256"] != digest:
                raise ValueError("已登记版本的 PT 内容不可覆盖")
            if not item:
                item = {"modelId": model_id, "name": metadata["name"], "version": metadata["version"],
                        "scenario": metadata["scenario"], "purpose": metadata["purpose"],
                        "format": "pt", "path": relative_path, "sizeBytes": path.stat().st_size,
                        "sha256": digest, "runtime": "server-pt", "labels": result["labels"],
                        "classCount": len(result["labels"]), "inputSize": result["input_size"],
                        "compatibleDevices": [], "artifacts": [artifact], "releaseEligible": False,
                        "licenseStatus": "internal-functional-testing-only" if metadata["purpose"] == "development" else "requires-review",
                        "sourceSha256": digest, "source": "administrator-upload",
                        "upstreamVersion": result["ultralytics"], "serverReady": True, "androidReady": False}
                entries.append(item)
        else:
            if not item or not item.get("serverReady"):
                raise ValueError("请先完成 PT 校验")
            if item["labels"] != result["labels"]:
                raise ValueError("PT 和 TFLite 类别顺序不一致")
            # A published version is immutable; retry may recover only the identical artifact.
            previous = next((a for a in item["artifacts"] if a["platform"] == "android"), None)
            if previous and previous["sha256"] != digest:
                raise ValueError("该版本已有不同的移动端产物，请上传新版本")
            if not previous:
                item["artifacts"].append(artifact)
                manifest_path = path.with_name("android-manifest.json")
                item["artifacts"].append({"artifactId": "android-manifest", "format": "json", "platform": "android",
                    "path": "models/" + manifest_path.resolve().relative_to((self.project_root / "models").resolve()).as_posix(),
                    "sizeBytes": manifest_path.stat().st_size, "sha256": self.sha256(manifest_path),
                    "contentType": "application/json"})
            signature_valid = bool(result.get("signatureValid", False))
            item.update(runtime="paired-server-pt-android-tflite", androidConverted=True,
                        androidReady=signature_valid, signatureStatus=result.get("signatureStatus", "unsigned"),
                        compatibleDevices=["API 27+ (device validation pending)"],
                        androidContract={key: result[key] for key in ("input", "output", "quantization", "input_size")})
        self._save(registry)
        return self.get(model_id)
