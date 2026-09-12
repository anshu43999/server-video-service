"""Fixed entry point run by the configured virtualenv, including inside WSL.

The stdlib supervisor bounds the lifetime of the entire exporter process group.
Heavy imports belong exclusively to the child process.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


def environment() -> dict:
    import ultralytics
    import torch
    packages = {name: importlib.metadata.version(name) for name in ("ultralytics", "torch")}
    mobile = False
    reason = "Windows 原生环境不支持本项目 LiteRT 导出，请使用 WSL"
    if platform.system() != "Windows":
        try:
            import ai_edge_litert.interpreter
            for name in ("litert-torch", "ai-edge-litert", "ai-edge-quantizer", "litert-converter"):
                packages[name] = importlib.metadata.version(name)
            mobile, reason = True, "依赖已就绪；实际模型导出结果仍需独立验证"
        except ImportError as exc:
            reason = f"缺少移动端转换依赖：{exc}"
    return {"ok": True, "python": platform.python_version(), "platform": platform.system(),
            "packages": packages, "server_available": True, "mobile_available": mobile, "message": reason}


def execute(action: str, directory: Path) -> dict:
    if action == "check":
        return environment()
    import numpy as np
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    if action == "verify":
        from ai_edge_litert.interpreter import Interpreter
        target = directory / "android.tflite"
        if not target.is_file():
            raise ValueError("本地复验缺少 android.tflite")
        labels = request.get("expected_labels")
        if not isinstance(labels, list) or not labels:
            raise ValueError("本地复验缺少类别标签")
        size = request["input_size"]
        interpreter = Interpreter(model_path=str(target), num_threads=1)
        interpreter.allocate_tensors()
        inputs, outputs = interpreter.get_input_details(), interpreter.get_output_details()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("App 当前要求单输入、单输出检测模型")
        inp, out = inputs[0], outputs[0]
        shape = out["shape"].tolist()
        if (inp["shape"].tolist() != [1, 3, size, size] or inp["dtype"] != np.float32 or
                out["dtype"] != np.float32 or len(shape) != 3 or shape[:2] != [1, len(labels) + 4]):
            raise ValueError("远程 TFLite 不符合当前 App NCHW float32 / [1,4+类别数,N] 协议")
        interpreter.set_tensor(inp["index"], np.zeros(inp["shape"], dtype=np.float32))
        interpreter.invoke()
        if not np.isfinite(interpreter.get_tensor(out["index"])).all():
            raise ValueError("远程 TFLite 本地预热产生非有限值")
        def tensor(detail):
            return {"name": detail["name"], "shape": detail["shape"].tolist(),
                    "dataType": "float32", "quantization": list(detail["quantization"])}
        return {"ok": True, "labels": labels, "input_size": size, "warmup": "passed",
                "input": tensor(inp), "output": tensor(out), "quantization": "int8",
                "ultralytics": "remote-service"}
    from ultralytics import YOLO
    model = YOLO(str(directory / "source.pt"))
    if model.task != "detect":
        raise ValueError("当前仅支持 Ultralytics 目标检测模型，不支持分类、分割或姿态模型")
    if getattr(model.model, "end2end", False):
        raise ValueError("当前不支持端到端/NMS 内置检测模型，请使用常规 YOLO 检测权重")
    labels = [str(model.names[index]) for index in range(len(model.names))]
    if not labels or any(not label.strip() for label in labels):
        raise ValueError("模型没有有效的连续类别标签")
    size = request["input_size"]
    sample = np.zeros((size, size, 3), dtype=np.uint8)
    prediction = model.predict(sample, imgsz=size, device="cpu", verbose=False)[0]
    if prediction.boxes is None or not np.isfinite(prediction.boxes.data.cpu().numpy()).all():
        raise ValueError("模型试推理返回无效检测输出")
    if action == "inspect":
        return {"ok": True, "labels": labels, "input_size": size, "task": "detect",
                "ultralytics": importlib.metadata.version("ultralytics"), "warmup": "passed"}
    if action == "mobile":
        if not request["calibration_data"]:
            raise ValueError("INT8 转换需要校准数据；COCO 功能测试可填 coco8.yaml，业务模型请提供代表性数据集 YAML")
        result = model.export(format="litert", imgsz=size, quantize="int8",
                              data=request["calibration_data"], nms=False, batch=1, device="cpu")
        source = Path(result)
        candidates = [source] if source.is_file() and source.suffix == ".tflite" else list(source.rglob("*_int8.tflite"))
        if len(candidates) != 1:
            raise ValueError("导出没有产生唯一 INT8 TFLite 文件")
        target = directory / "android.tflite"
        shutil.copyfile(candidates[0], target)
        from ai_edge_litert.interpreter import Interpreter
        interpreter = Interpreter(model_path=str(target), num_threads=1)
        interpreter.allocate_tensors()
        inputs, outputs = interpreter.get_input_details(), interpreter.get_output_details()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("App 当前要求单输入、单输出检测模型")
        inp, out = inputs[0], outputs[0]
        shape = out["shape"].tolist()
        if (inp["shape"].tolist() != [1, 3, size, size] or inp["dtype"] != np.float32 or
                out["dtype"] != np.float32 or len(shape) != 3 or shape[:2] != [1, len(labels) + 4]):
            raise ValueError("导出张量不符合当前 App NCHW float32 / [1,4+类别数,N] 协议")
        interpreter.set_tensor(inp["index"], np.zeros(inp["shape"], dtype=np.float32))
        interpreter.invoke()
        if not np.isfinite(interpreter.get_tensor(out["index"])).all():
            raise ValueError("TFLite 预热产生非有限值")
        def tensor(detail):
            return {"name": detail["name"], "shape": detail["shape"].tolist(),
                    "dataType": "float32", "quantization": list(detail["quantization"])}
        return {"ok": True, "labels": labels, "input_size": size, "warmup": "passed",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "sizeBytes": target.stat().st_size,
                "input": tensor(inp), "output": tensor(out), "quantization": "int8",
                "calibration": request["calibration_data"], "ultralytics": importlib.metadata.version("ultralytics")}
    raise ValueError("unsupported worker action")


def stop_process(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("check", "inspect", "mobile", "verify"), required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chdir(directory)
    if args.execute:
        try:
            result = execute(args.action, directory)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            result = {"ok": False, "error": str(exc)[:2000]}
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return 0 if result.get("ok") else 1
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--execute"],
                               start_new_session=os.name == "posix")
    deadline = time.monotonic() + args.timeout
    while process.poll() is None:
        if (directory / "cancel").exists() or time.monotonic() > deadline:
            stop_process(process)
            (directory / "result.json").write_text(json.dumps({"ok": False, "error": "任务取消或执行超时"}), encoding="utf-8")
            return 1
        time.sleep(0.2)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
