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

MODEL_RELEASE_STATUSES = {
    "DRAFT",
    "CONVERTING",
    "READY",
    "PUBLISHED",
    "DEPRECATED",
    "REVOKED",
    "UNINSTALLED",
}
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


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

    @staticmethod
    def release_key(item: dict[str, Any]) -> str:
        return f"{item.get('modelId')}@{item.get('version')}"

    @staticmethod
    def _status(item: dict[str, Any]) -> str:
        status = str(item.get("status") or "").upper()
        if status in MODEL_RELEASE_STATUSES:
            return status
        # v1 registries predate lifecycle state. A release-eligible item is
        # treated as published; all other legacy entries remain diagnostically
        # visible but cannot be selected as a production latest version.
        return "PUBLISHED" if item.get("releaseEligible") else "READY"

    @staticmethod
    def _version_sort_key(version: Any) -> tuple:
        value = str(version or "")
        match = _SEMVER.fullmatch(value)
        if match:
            major, minor, patch, prerelease = match.groups()
            # Stable releases sort after prereleases for the same numbers.
            pre_key = (1, "") if not prerelease else (0, prerelease)
            return (2, int(major), int(minor), int(patch), pre_key, value)
        return (1, 0, 0, 0, (0, ""), value)

    def _entries_for_model(self, registry: dict[str, Any], model_id: str) -> list[dict[str, Any]]:
        return [item for item in registry.get("models", []) if item.get("modelId") == model_id]

    def _latest_published(self, registry: dict[str, Any], model_id: str) -> dict[str, Any] | None:
        candidates = [
            item for item in self._entries_for_model(registry, model_id)
            if self._status(item) == "PUBLISHED" and bool(item.get("releaseEligible", True))
        ]
        return max(candidates, key=lambda item: self._version_sort_key(item.get("version")), default=None)

    def _find_entry(
        self,
        registry: dict[str, Any],
        model_id: str,
        version: str | None = None,
    ) -> dict[str, Any] | None:
        entries = self._entries_for_model(registry, model_id)
        if version is not None:
            return next((item for item in entries if str(item.get("version")) == version), None)
        active = self._resolve_active_reference(registry)
        if active and active.startswith(f"{model_id}@"):
            active_item = next((item for item in entries if self.release_key(item) == active), None)
            if active_item is not None:
                return active_item
        return self._latest_published(registry, model_id) or max(
            entries,
            key=lambda item: self._version_sort_key(item.get("version")),
            default=None,
        )

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
            version = model.get("version")
            release_key = f"{model_id}@{version}"
            if release_key in seen:
                errors.append(f"duplicate release: {release_key}")
            else:
                seen.add(release_key)
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
            old = next(
                (
                    entry
                    for entry in existing
                    if entry.get("modelId") == model_id
                    and str(entry.get("version")) == str(item.get("version"))
                ),
                None,
            )
            if old is None:
                existing.append(item)
            else:
                old.update(item)
            registered.append(self.inspect(item, self._resolve_active_model_id(registry)))
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
            artifact_copy["url"] = f"/aiyoloapi/models/{item.get('modelId')}/artifacts/{artifact.get('artifactId')}/download"
            artifact_copy["versionedUrl"] = (
                f"/aiyoloapi/models/{item.get('modelId')}/versions/{item.get('version')}"
                f"/artifacts/{artifact.get('artifactId')}/download"
            )
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
            "active": active_name in {item.get("modelId"), self.release_key(item)},
        }
        if inspected_artifacts:
            result["artifacts"] = inspected_artifacts
        return result

    def _resolve_active_reference(self, registry: dict[str, Any]) -> str | None:
        """Resolve modelId@version and legacy modelId/basename references."""
        active_ref = str(registry.get("activeServerModel") or "")
        if not active_ref:
            return None
        models = registry.get("models", [])
        if any(self.release_key(item) == active_ref for item in models):
            return active_ref
        if any(item.get("modelId") == active_ref for item in models):
            entries = self._entries_for_model(registry, active_ref)
            item = self._latest_published(registry, active_ref) or max(
                entries,
                key=lambda candidate: self._version_sort_key(candidate.get("version")),
                default=None,
            )
            return self.release_key(item) if item is not None else active_ref
        # Legacy catalogs stored only the basename. Select the first matching
        # server model, preserving the historical default without collisions.
        for item in models:
            if item.get("format") in {"pt", "onnx"} and Path(str(item.get("path", ""))).name == Path(active_ref).name:
                return self.release_key(item)
        return None

    def _resolve_active_model_id(self, registry: dict[str, Any]) -> str | None:
        reference = self._resolve_active_reference(registry)
        return reference.split("@", 1)[0] if reference else None

    def list_models(self) -> list[dict[str, Any]]:
        registry = self._load()
        active_reference = self._resolve_active_reference(registry)
        return [self.public_inspect(item, active_reference, registry) for item in registry.get("models", [])]

    def calibration_references(self, dataset_id: str) -> list[str]:
        registry = self._load()
        return [
            str(item.get("modelId"))
            for item in registry.get("models", [])
            if isinstance(item.get("calibrationDataset"), dict)
            and item["calibrationDataset"].get("datasetId") == dataset_id
        ]

    def get(self, model_id: str, version: str | None = None) -> dict[str, Any]:
        registry = self._load()
        item = self._find_entry(registry, model_id, version)
        if item is not None:
            return self.public_inspect(item, self._resolve_active_reference(registry), registry)
        raise KeyError(model_id)

    def _model_paths(self, item: dict[str, Any]) -> set[Path]:
        paths: set[Path] = set()
        for field in ("path", "labelsPath", "manifestPath"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                # Labels and manifests may intentionally live under docs/;
                # uninstall only cleans files owned by the models directory.
                try:
                    paths.add(self._artifact_path({"path": value}))
                except ModelCatalogValidationError:
                    continue
        for artifact in item.get("artifacts", []):
            if isinstance(artifact, dict):
                paths.add(self._artifact_path(artifact))
        return paths

    @serialized_mutation
    def uninstall(self, model_id: str, version: str | None = None) -> dict[str, Any]:
        """Remove one release, preserving a small immutable audit tombstone."""
        registry = self._load()
        models = registry.get("models", [])
        matches = self._entries_for_model(registry, model_id)
        if version is None and len(matches) > 1:
            raise ValueError("version required when model has multiple releases")
        target = self._find_entry(registry, model_id, version)
        if target is None:
            raise KeyError(model_id)

        if self.release_key(target) == self._resolve_active_reference(registry):
            raise ValueError("active model release cannot be uninstalled")

        remaining = [item for item in models if item is not target]
        target_paths = self._model_paths(target)
        shared_paths: set[Path] = set()
        for item in remaining:
            shared_paths.update(self._model_paths(item))
        removable_paths = target_paths - shared_paths

        registry["models"] = remaining
        history = registry.setdefault("modelHistory", [])
        tombstone = dict(target)
        tombstone["status"] = "UNINSTALLED"
        tombstone["uninstalledAt"] = date.today().isoformat()
        history.append({
            key: tombstone[key]
            for key in (
                "modelId", "version", "status", "manifestSha256", "artifacts",
                "releaseEligible", "publishedAt", "uninstalledAt",
            )
            if key in tombstone
        })
        registry["updatedAt"] = date.today().isoformat()
        self._save(registry)

        deleted = 0
        missing = 0
        cleanup_failures: list[str] = []
        models_root = (self.project_root / "models").resolve()
        for path in sorted(removable_paths, key=lambda value: len(value.parts), reverse=True):
            try:
                if path.is_file():
                    path.unlink()
                    deleted += 1
                else:
                    missing += 1
            except OSError:
                cleanup_failures.append(path.name)
                continue
            parent = path.parent
            while parent != models_root and models_root in parent.parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

        return {
            "modelId": model_id,
            "version": target.get("version"),
            "uninstalled": True,
            "deletedFiles": deleted,
            "missingFiles": missing,
            "retainedSharedFiles": len(target_paths & shared_paths),
            "cleanupFailures": cleanup_failures,
        }

    def versions(self, model_id: str) -> list[dict[str, Any]]:
        registry = self._load()
        entries = self._entries_for_model(registry, model_id)
        if not entries:
            raise KeyError(model_id)
        active_reference = self._resolve_active_reference(registry)
        return [
            self.public_inspect(item, active_reference, registry)
            for item in sorted(entries, key=lambda entry: self._version_sort_key(entry.get("version")), reverse=True)
        ]

    @serialized_mutation
    def migrate_release(
        self,
        source_model_id: str,
        target_model_id: str,
        version: str,
        reason: str | None = None,
        actor: str = "admin",
    ) -> dict[str, Any]:
        """Explicitly move one historical release into a stable model family.

        This operation is intentionally never inferred from name, source hash,
        or version.  A release is moved only when an administrator names both
        identities and the exact version, and an existing target release is
        never overwritten.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", target_model_id):
            raise ValueError("target modelId is invalid")
        if source_model_id == target_model_id:
            raise ValueError("source and target modelId must differ")
        registry = self._load()
        if any(
            item.get("modelId") == target_model_id and str(item.get("version")) == str(version)
            for item in registry.get("models", [])
        ):
            raise ValueError("target modelId and version already exists")
        source = self._find_entry(registry, source_model_id, version)
        if source is None:
            raise KeyError(source_model_id)
        source["modelId"] = target_model_id
        source["migratedFromModelId"] = source_model_id
        source["migratedAt"] = date.today().isoformat()
        history = registry.setdefault("modelHistory", [])
        history.append({
            "modelId": target_model_id,
            "version": version,
            "status": "MIGRATED",
            "sourceModelId": source_model_id,
            "targetModelId": target_model_id,
            "reason": (reason or "explicit administrator migration").strip()[:512],
            "actor": actor.strip()[:128] or "admin",
            "changedAt": date.today().isoformat(),
        })
        registry["updatedAt"] = date.today().isoformat()
        self._save(registry)
        result = self.public_inspect(source, self._resolve_active_reference(registry), registry)
        result["migratedFromModelId"] = source_model_id
        return result

    @serialized_mutation
    def set_release_status(
        self,
        model_id: str,
        version: str,
        status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        status = status.upper()
        if status not in {"DEPRECATED", "REVOKED"}:
            raise ValueError("unsupported release status")
        registry = self._load()
        target = self._find_entry(registry, model_id, version)
        if target is None:
            raise KeyError(model_id)
        current = self._status(target)
        if current in {"UNINSTALLED", "REVOKED"} and status != "REVOKED":
            raise ValueError(f"release is already {current.lower()}")
        target["status"] = status
        if status == "DEPRECATED":
            target["deprecatedAt"] = date.today().isoformat()
        else:
            target["revokedAt"] = date.today().isoformat()
            target["revokeReason"] = (reason or "operator revoked release").strip()[:512]
        registry["updatedAt"] = date.today().isoformat()
        registry.setdefault("modelHistory", []).append({
            "modelId": model_id,
            "version": version,
            "status": status,
            "reason": reason,
            "changedAt": date.today().isoformat(),
        })
        self._save(registry)
        return self.public_inspect(target, self._resolve_active_reference(registry), registry)

    def get_artifact(
        self,
        model_id: str,
        artifact_id: str,
        version: str | None = None,
    ) -> tuple[dict[str, Any], Path]:
        """Resolve a registered artifact for download without exposing its path.

        The returned file is revalidated immediately before serving.  A changed
        or missing artifact is rejected rather than streaming bytes that cannot
        satisfy the catalog's advertised size/hash contract.
        """
        registry = self._load()
        model = self._find_entry(registry, model_id, version)
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

    def public_inspect(
        self,
        item: dict[str, Any],
        active_name: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the API-safe representation of a catalog entry.

        Registry paths are implementation details and must never cross the API
        boundary.  This method deliberately projects the internal inspection
        result to the frozen M09-T01 contract and retains only URL-based artifact
        references.  ``exists`` and ``hashValid`` are useful operational status
        fields and do not expose filesystem locations.
        """
        inspected = self.inspect(item, active_name)
        registry = registry or self._load()
        siblings = self._entries_for_model(registry, str(item.get("modelId")))
        latest = self._latest_published(registry, str(item.get("modelId")))
        artifacts = inspected.get("artifacts", [])
        public_artifacts: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            allowed = {
                key: artifact[key]
                for key in ("artifactId", "format", "platform", "url", "versionedUrl", "sizeBytes", "sha256", "contentType", "exists", "hashValid")
                if key in artifact
            }
            public_artifacts.append(allowed)
        primary = public_artifacts[0] if public_artifacts else {}
        calibration = inspected.get("calibrationDataset")
        public_calibration = None
        if isinstance(calibration, dict):
            public_calibration = {
                key: calibration[key]
                for key in (
                    "datasetId", "name", "version", "scenario", "imageCount",
                    "sizeBytes", "contentSha256", "yamlPath", "builtin",
                )
                if key in calibration
            }
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
            "status": self._status(item),
            "versionOrder": self._version_sort_key(item.get("version")),
            "isLatest": latest is not None and self.release_key(latest) == self.release_key(item),
            "latestVersion": latest.get("version") if latest is not None else None,
            "availableVersions": [
                str(entry.get("version"))
                for entry in sorted(
                    siblings,
                    key=lambda entry: self._version_sort_key(entry.get("version")),
                    reverse=True,
                )
            ],
            "publishedAt": item.get("publishedAt"),
            "deprecatedAt": item.get("deprecatedAt"),
            "revokedAt": item.get("revokedAt"),
            "revokeReason": item.get("revokeReason"),
            "manifestSha256": item.get("manifestSha256"),
            "inputSize": inspected.get("inputSize"),
            "serverReady": inspected.get("serverReady", False),
            "androidReady": inspected.get("androidReady", False),
            "androidConverted": inspected.get("androidConverted", inspected.get("androidReady", False)),
            "signatureStatus": inspected.get("signatureStatus", "unsigned"),
            "androidContract": inspected.get("androidContract"),
            "calibrationDataset": public_calibration,
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
    def activate(self, model_id: str, version: str | None = None) -> dict[str, Any]:
        registry = self._load()
        target = self._find_entry(registry, model_id, version)
        if target is None:
            raise KeyError(model_id)
        if self._status(target) in {"DEPRECATED", "REVOKED", "UNINSTALLED"}:
            raise ValueError(f"model release is {self._status(target).lower()}")
        if target.get("placeholder"):
            raise ValueError("placeholder models cannot be activated")
        inspected = self.inspect(target, self._resolve_active_reference(registry))
        if not inspected["exists"]:
            raise ValueError("model file does not exist")
        if not inspected["hashValid"]:
            raise ValueError("model SHA-256 does not match registry")
        if target.get("format") not in {"pt", "onnx"}:
            raise ValueError("only server model formats pt and onnx can be activated")
        registry["activeServerModel"] = self.release_key(target) if version is not None else model_id
        self._save(registry)
        return self.inspect(target, self._resolve_active_reference(registry))

    def active_server_path(self) -> str:
        registry = self._load()
        active_reference = self._resolve_active_reference(registry)
        for item in registry.get("models", []):
            if self.release_key(item) == active_reference and item.get("format") in {"pt", "onnx"}:
                return str((self.registry_path.parents[1] / item["path"]).resolve())
        return str((self.registry_path.parents[1] / "models" / "yolo11n.pt").resolve())

    def resolve_server_model(self, model_id: str, version: str | None = None) -> tuple[dict[str, Any], Path]:
        """Resolve a registered, hash-valid PT/ONNX model for a stream binding.

        TFLite/mobile-only entries are deliberately rejected so a stream can never
        switch to an artifact that the server detector cannot load.
        """
        registry = self._load()
        item = self._find_entry(registry, model_id, version)
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
        version = str(metadata.get("version") or result.get("version") or "0.0.0-legacy")
        item = next(
            (
                row
                for row in entries
                if row.get("modelId") == model_id and str(row.get("version")) == version
            ),
            None,
        )
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
                item = {"modelId": model_id, "name": metadata["name"], "version": version,
                        "scenario": metadata["scenario"], "purpose": metadata["purpose"],
                        "format": "pt", "path": relative_path, "sizeBytes": path.stat().st_size,
                        "sha256": digest, "runtime": "server-pt", "labels": result["labels"],
                        "classCount": len(result["labels"]), "inputSize": result["input_size"],
                        "compatibleDevices": [], "artifacts": [artifact], "releaseEligible": False,
                        "licenseStatus": "internal-functional-testing-only" if metadata["purpose"] == "development" else "requires-review",
                        "sourceSha256": digest, "source": "administrator-upload",
                        "upstreamVersion": result["ultralytics"], "serverReady": True, "androidReady": False,
                        "status": "READY"}
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
                        androidContract={key: result[key] for key in ("input", "output", "quantization", "input_size")},
                        calibrationDataset=result.get("calibration_dataset"))
        self._save(registry)
        return self.get(model_id, version)
