"""Generate the deterministic, project-owned calibration smoke-test images."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "calibration" / "builtin" / "dev8"
WIDTH = HEIGHT = 320


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def pixel(seed: int, x: int, y: int) -> tuple[int, int, int]:
    band = ((x // (18 + seed)) + (y // (23 + seed * 2))) % 3
    circle = ((x - (52 + seed * 27) % 250) ** 2 + (y - (71 + seed * 31) % 230) ** 2) < (28 + seed * 3) ** 2
    stripe = abs((x * (seed + 2) - y * (seed + 1)) % 101 - 50) < 8
    base = ((x * (seed + 3) + y * 2) % 256, (y * (seed + 5) + x) % 256, ((x + y) * (seed + 1)) % 256)
    if circle:
        return 238, 188 - seed * 7, 44 + seed * 13
    if stripe:
        return 38 + seed * 17, 168, 115 + band * 42
    return tuple((value // 2 + band * 35) % 256 for value in base)


def png(seed: int) -> bytes:
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)
        for x in range(WIDTH):
            rows.extend(pixel(seed, x, y))
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return signature + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + png_chunk(b"IEND", b"")


def main() -> None:
    images = TARGET / "images"
    images.mkdir(parents=True, exist_ok=True)
    (TARGET / "labels.cache").unlink(missing_ok=True)
    for existing in images.iterdir():
        if existing.is_file():
            existing.unlink()
    yaml = (
        "# Project-owned synthetic images for conversion smoke tests only.\n"
        "path: __AIYOLO_BUILTIN_CALIBRATION_ROOT__\n"
        "train: images\n"
        "val: images\n"
        "names:\n"
        "  0: calibration\n"
    ).encode("utf-8")
    (TARGET / "dataset.yaml").write_bytes(yaml)
    files = []
    for seed in range(1, 9):
        path = images / f"{seed:06d}.png"
        path.write_bytes(png(seed))
    for path in [TARGET / "dataset.yaml", *sorted(images.glob("*.png"))]:
        content = path.read_bytes()
        files.append({
            "path": path.relative_to(TARGET).as_posix(),
            "sizeBytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    fingerprint = hashlib.sha256()
    for item in files:
        fingerprint.update(item["path"].encode("utf-8") + b"\0")
        fingerprint.update(item["sha256"].encode("ascii") + b"\0")
    manifest = {
        "schemaVersion": 1,
        "datasetId": "coco8-dev",
        "name": "内置 8 图转换测试",
        "license": "Project-generated test fixture; not derived from COCO images",
        "purpose": "conversion-smoke-test-only",
        "contentSha256": fingerprint.hexdigest(),
        "yamlPath": "dataset.yaml",
        "files": files,
    }
    (TARGET / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
