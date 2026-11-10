"""Offline, read-only model comparison. Never imports the service or runs a worker.

ADB is restricted to PKX110 identity checks and run-as reads; model bytes stay
in memory. Reports are diagnostic comparisons, not business accuracy approval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone

import numpy as np

ADB = r"D:\Users\45393\Android\sdk\platform-tools\adb.exe"
PACKAGE = "com.aiyolo.inspection"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def android_input(rgb, size=640):
    """Mirror rotation=0 Android float32 half-pixel RGB letterbox, not uint8 resize."""
    h, w, channels = rgb.shape
    if channels != 3 or h < 1 or w < 1 or size < 1:
        raise ValueError("invalid RGB dimensions")
    scale = min(size / w, size / h)
    rw, rh = int(w * scale + 0.5), int(h * scale + 0.5)
    left, top = (size - rw) // 2, (size - rh) // 2
    x = np.clip((np.arange(rw, dtype=np.float32) + np.float32(.5)) * np.float32(w / rw) - np.float32(.5), 0, w - 1)
    y = np.clip((np.arange(rh, dtype=np.float32) + np.float32(.5)) * np.float32(h / rh) - np.float32(.5), 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    wx, wy = (x - x0).astype(np.float32)[None, :, None], (y - y0).astype(np.float32)[:, None, None]
    a = rgb[y0[:, None], x0].astype(np.float32)
    b = rgb[y0[:, None], x1].astype(np.float32)
    c = rgb[y1[:, None], x0].astype(np.float32)
    d = rgb[y1[:, None], x1].astype(np.float32)
    upper, lower = a + (b - a) * wx, c + (d - c) * wx
    resized = upper + (lower - upper) * wy
    result = np.full((size, size, 3), np.float32(114) * np.float32(1 / 255), dtype=np.float32)
    result[top:top + rh, left:left + rw] = resized * np.float32(1 / 255)
    return np.ascontiguousarray(result.transpose(2, 0, 1)[None]), {
        "sourceWidth": w, "sourceHeight": h, "resizedWidth": rw, "resizedHeight": rh,
        "padding": [left, top, size - rw - left, size - rh - top], "rotation": 0}


def iou(a, b):
    wh = np.maximum(np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2]), 0)
    intersection = np.prod(wh)
    union = np.prod(a[2:] - a[:2]) + np.prod(b[2:] - b[:2]) - intersection
    return float(intersection / union) if union > 0 else 0.0


def summarize(raw, labels, confidence=.35, overlap=.45, limit=300, enabled=None):
    if raw.ndim != 3 or raw.shape[0] != 1 or raw.shape[1] != len(labels) + 4 or raw.shape[2] < 1:
        raise ValueError("expected [1,4+labels,candidates]")
    if not 0 <= confidence <= 1 or not 0 <= overlap <= 1 or limit < 1:
        raise ValueError("invalid postprocessing configuration")
    if len(set(labels)) != len(labels) or not labels or (enabled is not None and not set(enabled) <= set(labels)):
        raise ValueError("invalid labels")
    if not np.isfinite(raw).all():
        raise ValueError("nonfinite output")
    values, scores = raw[0], raw[0, 4:]
    best = scores.argmax(axis=0)
    maximum = scores.max(axis=0)
    candidates = []
    for index in range(values.shape[1]):
        class_id, score = int(best[index]), float(maximum[index])
        cx, cy, w, h = values[:4, index]
        if w <= 0 or h <= 0 or not confidence <= score <= 1:
            continue
        if enabled is not None and labels[class_id] not in enabled:
            continue
        box = np.clip(np.array([cx-w/2, cy-h/2, cx+w/2, cy+h/2], dtype=np.float32), 0, 1)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        candidates.append((score, class_id, index, box))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    kept = []
    for item in candidates:
        if not any(item[1] == other[1] and iou(item[3], other[3]) > overlap for other in kept):
            kept.append(item)
            if len(kept) == limit:
                break
    return {
        "shape": list(raw.shape), "rawSha256": digest(raw.tobytes()),
        "classMax": {label: float(scores[i].max()) for i, label in enumerate(labels)},
        "rawBestAboveThreshold": int(np.sum(maximum >= confidence)),
        "validCandidatesAfterClassFilter": len(candidates), "nmsCount": len(kept),
        "nms": [{"classId": c, "label": labels[c], "confidence": s, "candidate": n, "boxNormalizedInput": box.tolist()} for s, c, n, box in kept],
        "confidenceThreshold": confidence, "iouThreshold": overlap, "maxDetections": limit,
        "enabledLabels": None if enabled is None else sorted(enabled),
    }


def embedded_metadata(data):
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "metadata.json" not in archive.namelist():
            return None
        info = archive.getinfo("metadata.json")
        if info.file_size > 65536:
            raise ValueError("metadata too large")
        meta = json.loads(archive.read(info))
    allowed = ("description", "version", "date", "task", "batch", "imgsz", "names", "args", "end2end")
    return {key: meta[key] for key in allowed if key in meta}


def graph_bytes_hash(data):
    """Ignore appended ZIP metadata timestamps; retain every FlatBuffer byte."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return digest(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        offsets = [item.header_offset for item in archive.infolist()]
    return digest(data[:min(offsets)]) if offsets else digest(data)


def buffer_bytes(buffer, data):
    """Read both inline and external TFLite buffers without omitting weights."""
    if buffer.DataLength():
        return buffer.DataAsNumpy().tobytes()
    offset, size = int(buffer.Offset()), int(buffer.Size())
    if not size:
        return b''
    if offset < 0 or offset + size > len(data):
        raise ValueError('external buffer outside artifact')
    return data[offset:offset + size]


def graph_summary(data):
    from ai_edge_litert import schema_py_generated as schema
    model = schema.Model.GetRootAsModel(data, 0)
    graph = model.Subgraphs(0)
    types = {v: k for k, v in vars(schema.TensorType).items() if isinstance(v, int)}
    operations = {v: k for k, v in vars(schema.BuiltinOperator).items() if isinstance(v, int)}
    dtypes = Counter(types.get(graph.Tensors(i).Type(), "unknown") for i in range(graph.TensorsLength()))
    ops = Counter(operations.get(model.OperatorCodes(graph.Operators(i).OpcodeIndex()).BuiltinCode(), "unknown") for i in range(graph.OperatorsLength()))
    constant_hashes = []
    for i in range(graph.TensorsLength()):
        tensor = graph.Tensors(i)
        buf = model.Buffers(tensor.Buffer())
        raw = buffer_bytes(buf, data)
        if raw:
            constant_hashes.append(digest(raw))
    return {"tensorCount": graph.TensorsLength(), "operatorCount": graph.OperatorsLength(),
            "tensorTypes": dict(dtypes), "operations": dict(ops),
            "constantHashIncludesExternalBuffers": True,
            "externalBufferCount": sum(model.Buffers(i).Size() > 0 for i in range(model.BuffersLength())),
            "orderedConstantHash": digest("".join(constant_hashes).encode())}


def manifest_summary(manifest):
    return {k: manifest.get(k) for k in ("modelId", "version", "runtime", "modelFile", "input", "output", "labels", "quantization", "calibrationDataset", "source")}


def phone_artifact(serial, directory):
    path = PurePosixPath(directory)
    if len(path.parts) != 3 or path.parts[:2] != ("files", "suite-model-artifacts") or any(c not in "0123456789abcdef-" for c in path.parts[2]):
        raise ValueError("only a single suite artifact directory is allowed")
    def adb(*args):
        return subprocess.run([ADB, "-s", serial, *args], check=True, capture_output=True, timeout=30).stdout
    if serial.startswith("emulator-") or adb("shell", "getprop", "ro.product.model").decode().strip() != "PKX110":
        raise ValueError("explicit PKX110 device required")
    manifest_bytes = adb("exec-out", "run-as", PACKAGE, "cat", str(path / "manifest.json"))
    manifest = json.loads(manifest_bytes)
    data = adb("exec-out", "run-as", PACKAGE, "cat", str(path / "model.tflite"))
    after = adb("exec-out", "run-as", PACKAGE, "cat", str(path / "manifest.json"))
    if after != manifest_bytes:
        raise ValueError("device artifact changed while reading")
    return data, manifest


def verify_identity(data, manifest, source_hash):
    if digest(data) != manifest["modelFile"]["sha256"] or len(data) != manifest["modelFile"]["sizeBytes"]:
        raise ValueError("artifact size/hash mismatch")
    if manifest["source"]["revision"] != source_hash:
        raise ValueError("manifest source differs from actual PT hash")
    if manifest["input"]["layout"] != "NCHW" or manifest["output"]["coordinateSpace"] != "normalized-input":
        raise ValueError("unsupported tensor contract")


def run_tflite(data, tensor, labels, confidence, no_delegate):
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    kwargs = {"experimental_op_resolver_type": OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES} if no_delegate else {}
    engine = Interpreter(model_content=data, num_threads=1, **kwargs)
    engine.allocate_tensors()
    inputs, outputs = engine.get_input_details(), engine.get_output_details()
    if len(inputs) != 1 or len(outputs) != 1 or list(inputs[0]["shape"]) != list(tensor.shape) or inputs[0]["dtype"] != np.float32 or outputs[0]["dtype"] != np.float32:
        raise ValueError("unexpected input/output tensors")
    engine.set_tensor(inputs[0]["index"], tensor)
    engine.invoke()
    raw = engine.get_tensor(outputs[0]["index"])
    return {"allClasses": summarize(raw, labels, confidence),
            "headOnlyDiagnosticNotActualParameters": summarize(raw, labels, confidence, enabled={"head"}) if "head" in labels else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--local-manifest", type=Path, action="append", default=[])
    parser.add_argument("--artifact-pair", type=Path, nargs=2, action="append", default=[], metavar=("MANIFEST", "TFLITE"))
    parser.add_argument("--serial")
    parser.add_argument("--phone-directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=.35)
    args = parser.parse_args()
    if bool(args.serial) != bool(args.phone_directory):
        parser.error("serial and phone-directory must be supplied together")
    # No overwrite, model registry writes, production connection or exporter.
    root = Path(__file__).resolve().parents[1]
    args.output.resolve().relative_to(root / "evidence" / "M27")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["YOLO_AUTOINSTALL"] = "false"
    runtime_config = args.output.resolve() / "runtime-config"
    runtime_config.mkdir()
    os.environ["YOLO_CONFIG_DIR"] = str(runtime_config)
    from PIL import Image
    source_hash = digest(args.source.read_bytes())
    rgb = np.asarray(Image.open(args.image).convert("RGB"))
    tensor, transform = android_input(rgb)
    report = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
              "execution": "desktop CPU inference; NOT phone inference or accuracy certification",
              "source": {"path": str(args.source), "sha256": source_hash},
              "sample": {"path": str(args.image), "sha256": digest(args.image.read_bytes()), "transform": transform, "inputSha256": digest(tensor.tobytes())},
              "versions": {n: importlib.metadata.version(n) for n in ("torch", "ultralytics", "ai-edge-litert", "numpy", "pillow")},
              "artifacts": []}
    artifacts = []
    for manifest_path in args.local_manifest:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts.append((str(manifest_path), (manifest_path.parent / "android.tflite").read_bytes(), manifest))
    for manifest_path, model_path in args.artifact_pair:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts.append((str(model_path), model_path.read_bytes(), manifest))
    if args.serial:
        data, manifest = phone_artifact(args.serial, args.phone_directory)
        artifacts.append(("PKX110 read-only memory capture", data, manifest))
    labels = None
    for origin, data, manifest in artifacts:
        verify_identity(data, manifest, source_hash)
        if labels is not None and labels != manifest["labels"]:
            raise ValueError("different label orders")
        labels = manifest["labels"]
        entry = {"origin": origin, "actualSha256": digest(data), "actualSizeBytes": len(data),
                 "flatbufferPrefixSha256": graph_bytes_hash(data),
                 "manifest": manifest_summary(manifest), "embeddedMetadata": embedded_metadata(data), "graph": graph_summary(data)}
        entry["defaultDelegate"] = run_tflite(data, tensor, labels, args.confidence, False)
        entry["withoutDefaultDelegates"] = run_tflite(data, tensor, labels, args.confidence, True)
        report["artifacts"].append(entry)
        print(json.dumps({"artifact": origin, "sha256": entry["actualSha256"], "max": entry["defaultDelegate"]["allClasses"]["classMax"]}), flush=True)
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(1)
    model = YOLO(str(args.source))
    pt_labels = [str(model.names[i]) for i in range(len(model.names))]
    if labels is not None and labels != pt_labels:
        raise ValueError("PT label order mismatch")
    model.model.eval()
    with torch.inference_mode():
        output = model.model(torch.from_numpy(tensor))
    raw = (output[0] if isinstance(output, tuple) else output).detach().cpu().numpy().copy()
    raw[:, :4] /= np.float32(tensor.shape[2])
    report["pt"] = summarize(raw, pt_labels, args.confidence)
    report["limitations"] = ["Single supplied image, not labelled evaluation or business accuracy acceptance",
        "Manifest source hash is provenance linkage, not production worker input-byte proof",
        "No production access and no phone inference, install, parameter update or alert upload",
        "0.35/0.45/300 is a fixed comparison configuration, not proof of live approved parameters",
        "JPEG decoded with Pillow; arithmetic mirrors Android, not a device frame capture"]
    target = args.output / "comparison.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"report": str(target), "ptMax": report["pt"]["classMax"], "ptNmsCount": report["pt"]["nmsCount"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
