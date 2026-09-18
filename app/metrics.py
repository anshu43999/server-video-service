from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


def system_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "pid": os.getpid(),
        "cpu_percent": None,
        "memory_mb": None,
        "memory_percent": None,
        "disk_percent": None,
        "gpu": None,
    }
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        metrics["cpu_percent"] = process.cpu_percent(interval=None)
        metrics["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 2)
        metrics["memory_percent"] = round(psutil.virtual_memory().percent, 1)
        metrics["disk_percent"] = round(psutil.disk_usage(os.path.abspath(os.sep)).percent, 1)
    except Exception:
        pass
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            output = subprocess.check_output([nvidia_smi, "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"], text=True, timeout=2).strip()
            rows = []
            for line in output.splitlines():
                values = [value.strip() for value in line.split(",")]
                if len(values) == 3:
                    rows.append({"utilization_percent": float(values[0]), "memory_used_mb": float(values[1]), "memory_total_mb": float(values[2])})
            metrics["gpu"] = rows
        except Exception:
            metrics["gpu"] = None
    return metrics
