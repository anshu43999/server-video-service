from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any

from .model_catalog import ModelCatalog, ModelCatalogValidationError


class ModelSeedError(RuntimeError):
    """Raised when checked-in model assets cannot be imported safely."""


@dataclass(frozen=True)
class ModelSeedResult:
    imported_models: int
    preserved_models: int
    copied_files: int


def _read_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelSeedError(f"cannot read model registry {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ModelSeedError(f"model registry is invalid: {path}")
    return payload


def _resolve_seed_file(raw_path: Any, project_root: Path, models_root: Path) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    resolved = path.resolve()
    if resolved != models_root and models_root not in resolved.parents:
        return None
    return resolved


def _registered_files(model: dict[str, Any], catalog: ModelCatalog) -> dict[Path, str | None]:
    models_root = catalog.registry_path.parent.resolve()
    project_root = catalog.project_root.resolve()
    files: dict[Path, str | None] = {}

    primary = _resolve_seed_file(model.get("path"), project_root, models_root)
    if primary is None or not primary.is_file():
        raise ModelSeedError(f"seed model {model.get('modelId')} has no readable primary artifact")
    primary_hash = str(model.get("sha256", "")) or None
    if primary_hash and _sha256(primary).lower() != primary_hash.lower():
        raise ModelSeedError(f"seed model {model.get('modelId')} has an invalid primary hash")
    primary_size = model.get("sizeBytes")
    if isinstance(primary_size, int) and primary.stat().st_size != primary_size:
        raise ModelSeedError(f"seed model {model.get('modelId')} has an invalid primary size")
    files[primary] = primary_hash

    for artifact in model.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        path = _resolve_seed_file(
            artifact.get("path") or artifact.get("repositoryPath"),
            project_root,
            models_root,
        )
        if path is None or not path.is_file():
            raise ModelSeedError(
                f"seed model {model.get('modelId')} has a missing registered artifact"
            )
        expected_hash = str(artifact.get("sha256", "")) or None
        previous_hash = files.get(path)
        if previous_hash and expected_hash and previous_hash.lower() != expected_hash.lower():
            raise ModelSeedError(f"seed model {model.get('modelId')} declares conflicting hashes")
        files[path] = expected_hash or previous_hash

    # Copy useful checked-in metadata when it lives beside the seed assets.
    for field in ("manifestPath", "labelsPath", "source"):
        path = _resolve_seed_file(model.get(field), project_root, models_root)
        if path is not None and path.is_file():
            files.setdefault(path, None)
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_validated_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(registry, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        ModelCatalog(temporary).validate_startup()
        temporary.replace(path)
    except ModelCatalogValidationError as exc:
        raise ModelSeedError(str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


def seed_model_catalog(seed_models_root: Path, target_models_root: Path) -> ModelSeedResult:
    """Merge checked-in model assets into the persistent runtime catalog.

    Existing model IDs, files, and the active model selection are never replaced.
    This makes the operation safe to repeat on every container startup.
    """
    seed_models_root = seed_models_root.resolve()
    target_models_root = target_models_root.resolve()
    source_registry_path = seed_models_root / "registry.json"
    target_registry_path = target_models_root / "registry.json"

    if not source_registry_path.exists():
        # An operator-supplied model mount may contain only an inference model.
        return ModelSeedResult(0, 0, 0)

    source_catalog = ModelCatalog(source_registry_path)
    try:
        source_catalog.validate_startup()
    except ModelCatalogValidationError as exc:
        raise ModelSeedError(f"model seed validation failed: {exc}") from exc
    source_registry = _read_registry(source_registry_path)

    if target_registry_path.is_file():
        target_registry = _read_registry(target_registry_path)
    else:
        target_registry = {
            "schemaVersion": source_registry.get("schemaVersion", 1),
            "registryType": source_registry.get(
                "registryType", "server-video-service-models"
            ),
            "updatedAt": None,
            "activeServerModel": None,
            "models": [],
        }

    target_models = target_registry["models"]
    existing_ids = {
        item.get("modelId") for item in target_models if isinstance(item, dict)
    }
    additions = [
        item
        for item in source_registry["models"]
        if isinstance(item, dict) and item.get("modelId") not in existing_ids
    ]
    if not additions:
        return ModelSeedResult(0, len(existing_ids), 0)

    planned_files: dict[Path, tuple[Path, str | None]] = {}
    for model in additions:
        for source, expected_hash in _registered_files(model, source_catalog).items():
            relative = source.relative_to(seed_models_root)
            destination = target_models_root / relative
            resolved_parent = destination.parent.resolve()
            if resolved_parent != target_models_root and target_models_root not in resolved_parent.parents:
                raise ModelSeedError(f"model seed target escapes the models directory: {relative}")
            previous = planned_files.get(destination)
            if previous and previous[0] != source:
                raise ModelSeedError(f"multiple seed files target {relative.as_posix()}")
            planned_files[destination] = (source, expected_hash)

    copies: list[tuple[Path, Path]] = []
    for destination, (source, expected_hash) in planned_files.items():
        if destination.exists():
            if not destination.is_file():
                raise ModelSeedError(f"model seed target is not a file: {destination}")
            if expected_hash and _sha256(destination).lower() != expected_hash.lower():
                raise ModelSeedError(
                    f"model seed target already contains different data: {destination}"
                )
            continue
        copies.append((source, destination))

    for source, destination in copies:
        _copy_atomic(source, destination)

    target_models.extend(additions)
    target_registry["updatedAt"] = date.today().isoformat()
    target_registry.setdefault("activeServerModel", None)
    _write_validated_registry(target_registry_path, target_registry)
    return ModelSeedResult(len(additions), len(existing_ids), len(copies))
