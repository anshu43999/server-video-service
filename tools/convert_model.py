"""Convert a YOLO PT model into server/mobile deployment artifacts.

Examples:
  python tools/convert_model.py --weights models/yolo11n.pt --format all
  python tools/convert_model.py --weights models/yolo11n.pt --format mobile --imgsz 640
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_ultralytics():
    try:
        import ultralytics
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("ultralytics 未安装，请先执行 pip install -r requirements-yolo.txt") from exc
    return ultralytics, YOLO


def _find_tflite(export_result: str | Path) -> Path:
    path = Path(export_result)
    if path.is_file() and path.suffix.lower() == ".tflite":
        return path
    candidates = sorted(path.rglob("*_int8.tflite")) if path.is_dir() else []
    if len(candidates) != 1:
        raise RuntimeError(f"LiteRT 导出结果中应有且仅有一个 *_int8.tflite，实际找到 {len(candidates)} 个: {path}")
    return candidates[0]


def _mobile_export_error(exc: BaseException) -> RuntimeError:
    system = platform.system()
    if system == "Windows":
        return RuntimeError(
            "当前 Ultralytics LiteRT 导出链不支持 Windows 原生环境。"
            "请在 WSL2 Ubuntu/Linux x86 或 macOS 中安装 requirements-convert.txt 后重试；"
            "服务端 ONNX/PT 转换仍可在 Windows 执行。"
        )
    return RuntimeError(f"LiteRT INT8 导出失败: {exc}")


def export_model(args: argparse.Namespace) -> list[Path]:
    weights = args.weights.resolve()
    if not weights.is_file() or weights.suffix.lower() != ".pt":
        raise FileNotFoundError(f"PT weights not found: {weights}")
    _, YOLO = load_ultralytics()
    model = YOLO(str(weights))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    if args.format in ("server", "all"):
        if args.server_format in ("onnx", "both"):
            exported = model.export(format="onnx", imgsz=args.imgsz, nms=False, simplify=False, dynamic=False)
            source = Path(exported)
            destination = output_dir / f"{weights.stem}_{args.imgsz}.onnx"
            shutil.copy2(source, destination)
            generated.append(destination)
        if args.server_format in ("pt", "both"):
            destination = output_dir / f"{weights.stem}_{args.imgsz}.pt"
            shutil.copy2(weights, destination)
            generated.append(destination)
    if args.format in ("mobile", "all"):
        try:
            exported = model.export(format="litert", imgsz=args.imgsz, quantize="int8", data="coco8.yaml", nms=False, batch=1, device="cpu")
            source = _find_tflite(exported)
        except Exception as exc:
            raise _mobile_export_error(exc) from exc
        destination = output_dir / f"{weights.stem}_{args.imgsz}_int8.tflite"
        shutil.copy2(source, destination)
        generated.append(destination)
    return generated


def write_manifest(args: argparse.Namespace, generated: list[Path]) -> Path:
    try:
        ultralytics_version = importlib.metadata.version("ultralytics")
    except importlib.metadata.PackageNotFoundError:
        ultralytics_version = None
    manifest = {
        "schemaVersion": 1,
        "manifestType": "converted-model-set",
        "sourceWeights": {"path": str(args.weights), "sha256": sha256(args.weights.resolve())},
        "purpose": "development",
        "releaseEligible": False,
        "conversion": {
            "format": args.format,
            "serverFormat": args.server_format if args.format in ("server", "all") else None,
            "imgsz": args.imgsz,
            "nms": False,
            "quantization": "int8" if args.format in ("mobile", "all") else "none",
            "platform": platform.platform(),
        },
        "toolchain": {
            "python": platform.python_version(),
            "ultralytics": ultralytics_version,
            "onnx": _package_version("onnx"),
            "onnxsim": _package_version("onnxsim"),
        },
        "outputProtocol": {"nms": False, "note": "消费者必须按模型登记的输出张量协议执行后处理"},
        "artifacts": [
            {"path": str(path), "format": path.suffix.lstrip("."), "sizeBytes": path.stat().st_size, "sha256": sha256(path)}
            for path in generated
        ],
        "licenseStatus": "requires-project-specific-review-before-distribution",
    }
    path = args.output_dir.resolve() / f"{args.weights.stem}_{args.imgsz}_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert YOLO PT into server/mobile artifacts")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--format", choices=("server", "mobile", "all"), default="all")
    parser.add_argument(
        "--server-format",
        choices=("onnx", "pt", "both"),
        default="onnx",
        help="服务端产物格式；pt 表示复制并登记可直接加载的 PT 权重，both 同时生成 ONNX 与 PT。",
    )
    parser.add_argument("--imgsz", type=int, choices=(320, 416, 640), default=640)
    parser.add_argument("--output-dir", type=Path, default=Path("models/converted"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    generated = export_model(args)
    manifest = write_manifest(args, generated)
    for path in generated + [manifest]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
