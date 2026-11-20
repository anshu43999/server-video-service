"""Read local conversion inputs/results without service imports or database access."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from compare_mobile_model_outputs import graph_bytes_hash


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-calibration-root", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.resolve().relative_to(root / "evidence" / "M27")
    args.output.mkdir(parents=True, exist_ok=False)
    attempts = ["7cf5aae8bf6d4690a8c0b72c255ab475", "38b78222608c4f0ea00dadf85af5d5dd", "e65111bff2ba40dba2a578428131daea"]
    report = {"createdAt": datetime.now(timezone.utc).isoformat(), "attempts": []}
    for attempt in attempts:
        folder = root / "models/local-conversion" / attempt / "1"
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        report["attempts"].append({
            "attempt": attempt,
            "flatbufferPrefixSha256": graph_bytes_hash((folder / "android.tflite").read_bytes()),
            "files": {name: {"sha256": sha(folder / name), "bytes": (folder / name).stat().st_size} for name in
                      ("source.pt", "source_int8.tflite", "android.tflite", "request.json", "result.json", "worker.log", "android-manifest.json")},
            "request": {k: request.get(k) for k in ("mode", "distribution", "python_path", "input_size", "calibration_data", "default_calibration_dataset_id", "timeout_seconds")},
            "result": {k: result.get(k) for k in ("ok", "labels", "input_size", "warmup", "sha256", "sizeBytes", "quantization", "calibration", "ultralytics")},
        })
    builtin = root / "calibration/builtin/dev8"
    manifest = json.loads((builtin / "manifest.json").read_text(encoding="utf-8"))
    files = []
    fingerprint = hashlib.sha256()
    for item in manifest["files"]:
        path = builtin / item["path"]
        actual = sha(path)
        if actual != item["sha256"] or path.stat().st_size != item["sizeBytes"]:
            raise ValueError("builtin calibration integrity mismatch")
        fingerprint.update(item["path"].encode() + b"\0" + actual.encode() + b"\0")
        if item["path"].startswith("images/"):
            local = args.local_calibration_root / item["path"]
            local_hash = sha(local) if local.is_file() else None
            files.append({"path": item["path"], "builtinHash": actual, "localCacheHash": local_hash, "equal": local_hash == actual})
    if fingerprint.hexdigest() != manifest["contentSha256"]:
        raise ValueError("calibration fingerprint mismatch")
    report["calibration"] = {"manifestHash": sha(builtin / "manifest.json"), "contentSha256Verified": fingerprint.hexdigest(),
        "files": files, "scope": "Current local cache vs repository builtin; NOT historic/production calibration consumption proof"}
    source_files = ["tools/conversion_worker.py", "converter_service/jobs.py", "app/conversion.py", "app/model_signing.py",
                    "requirements-convert.txt", "requirements-yolo.txt", "constraints-cpu.txt", "Dockerfile.converter"]
    report["workingTreeFiles"] = {name: sha(root / name) for name in source_files}
    report["gitHead"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    packages = ["torch", "ultralytics", "litert-torch", "ai-edge-litert", "ai-edge-quantizer", "litert-converter"]
    code = "import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in " + repr(packages) + "}))"
    process = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--",
        "/home/anshu/.cache/aiyolo-model-tools/venv/bin/python", "-c", code], capture_output=True, text=True, check=True, timeout=30)
    report["currentWslVersions"] = json.loads(process.stdout)
    report["limitations"] = ["No production connection, database, Docker, worker start or phone mutation",
        "Current environment versions do not prove historical execution versions beyond saved result/metadata",
        "Manifest runtime 2.1.6 is generated as a literal and does not prove converter runtime version",
        "Registry upstreamVersion belongs to PT inspection, not necessarily the mobile exporter"]
    target = args.output / "provenance.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"report": str(target), "attempts": len(report["attempts"]), "calibrationImagesMatch": all(x["equal"] for x in files)}))


if __name__ == "__main__":
    main()
