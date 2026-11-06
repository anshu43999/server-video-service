"""Fail an image build if its resolved inference stack includes GPU runtimes."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re


def gpu_packages(names) -> list[str]:
    blocked = []
    for name in names:
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        # Ultralytics includes this small monitoring client even on CPU; it is
        # not a CUDA runtime and does not install NVIDIA compute libraries.
        if normalized == "nvidia-ml-py":
            continue
        if (normalized.startswith(("nvidia-", "cuda-", "cupy", "jax-cuda", "jax-rocm", "pytorch-triton"))
                or normalized in {"triton", "onnxruntime-gpu", "tensorflow-gpu"}):
            blocked.append(name)
    return sorted(blocked)


def check_runtime() -> dict:
    blocked = gpu_packages(dist.metadata["Name"] for dist in importlib.metadata.distributions())
    if blocked:
        raise RuntimeError("CPU image contains GPU packages: " + ", ".join(blocked))

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["JAX_PLATFORMS"] = "cpu"
    import torch
    import torchvision

    if torch.version.cuda is not None or torch.version.hip is not None:
        raise RuntimeError("CPU image requires a CPU-only PyTorch wheel")
    if platform.system() == "Linux" and "+cpu" not in torch.__version__:
        raise RuntimeError("Linux CPU image requires an explicitly tagged +cpu PyTorch wheel")
    if torch.cuda.is_available():
        raise RuntimeError("CUDA must not be available in the CPU image")
    # Exercise a compiled TorchVision operator: mismatched wheels can import
    # successfully but fail when YOLO first performs non-maximum suppression.
    kept = torchvision.ops.nms(
        torch.tensor([[0., 0., 10., 10.], [1., 1., 9., 9.]], device="cpu"),
        torch.tensor([0.9, 0.8], device="cpu"), 0.5,
    )
    if kept.tolist() != [0]:
        raise RuntimeError("CPU TorchVision NMS smoke test failed")
    result = {"device": "cpu", "torch": torch.__version__,
              "torchvision": torchvision.__version__, "torch_cuda": torch.version.cuda,
              "cuda_available": False, "gpu_packages": blocked, "nms": "passed"}
    try:
        importlib.metadata.version("jax")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        import jax
        devices = [device.platform for device in jax.devices()]
        if not devices or set(devices) != {"cpu"}:
            raise RuntimeError(f"JAX must use CPU devices: {devices}")
        result["jax_devices"] = devices
    return result


if __name__ == "__main__":
    print(json.dumps(check_runtime(), sort_keys=True))
