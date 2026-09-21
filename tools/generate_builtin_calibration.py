"""Refresh the manifest for the checked-in real Ultralytics COCO8 assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "calibration" / "builtin" / "dev8"


def main() -> None:
    yaml = TARGET / "dataset.yaml"
    images = sorted((TARGET / "images").glob("**/*"))
    labels = sorted((TARGET / "labels").glob("**/*"))
    files = [yaml, *[path for path in [*images, *labels] if path.is_file()], TARGET / "LICENSE", TARGET / "README.md"]
    if not yaml.is_file() or len([path for path in images if path.is_file()]) != 8:
        raise SystemExit("real COCO8 assets are incomplete")
    manifest_files = []
    for path in sorted(files, key=lambda item: item.relative_to(TARGET).as_posix()):
        content = path.read_bytes()
        manifest_files.append({
            "path": path.relative_to(TARGET).as_posix(),
            "sizeBytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    fingerprint = hashlib.sha256()
    for item in manifest_files:
        fingerprint.update(item["path"].encode("utf-8") + b"\0")
        fingerprint.update(item["sha256"].encode("ascii") + b"\0")
    manifest = {
        "schemaVersion": 1,
        "datasetId": "coco8-dev",
        "name": "Ultralytics COCO8 功能测试",
        "version": "ultralytics-v1",
        "source": "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco8.zip",
        "license": "See LICENSE; review Ultralytics and COCO terms before redistribution",
        "purpose": "conversion-smoke-test-only",
        "imageCount": 8,
        "sizeBytes": sum(item["sizeBytes"] for item in manifest_files),
        "contentSha256": fingerprint.hexdigest(),
        "yamlPath": "dataset.yaml",
        "files": manifest_files,
    }
    (TARGET / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
