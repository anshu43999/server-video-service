import os
import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.config import Settings
from app.detector import YoloDetector
from app.stream import StreamSession
from tools.check_cpu_runtime import gpu_packages, check_runtime
from tools.conversion_worker import configure_cpu_environment


class CpuRuntimeTests(unittest.TestCase):
    def test_old_device_settings_and_model_rebinding_still_predict_on_cpu(self):
        for old_device in ("auto", "", "cpu", "cuda", "cuda:0", "0", "mps"):
            with self.subTest(device=old_device):
                config = Settings(_env_file=None, yolo_device=old_device)
                self.assertEqual(config.yolo_device, "cpu")
                session = StreamSession("cpu-test", detector=YoloDetector("old.pt", device=old_device))
                session.bind_model(model_id="new-model", model_path="new.pt", device=old_device)
                model = Mock(names={0: "person"})
                model.predict.return_value = []
                session.detector._model = model
                session.detector.infer(np.zeros((32, 32, 3), dtype=np.uint8))
                self.assertEqual(model.predict.call_args.kwargs["device"], "cpu")
                self.assertEqual(session.model_metadata()["device"], "cpu")

    def test_gpu_package_audit_handles_distribution_name_variations(self):
        blocked = gpu_packages([
            "torch", "torchvision", "jaxlib", "nvidia-ml-py",
            "nvidia_cublas_cu12", "cuda-toolkit", "triton", "jax-cuda13-plugin",
            "onnxruntime-gpu", "cupy-cuda12x",
        ])
        self.assertEqual(len(blocked), 6)
        self.assertNotIn("nvidia-ml-py", blocked)
        self.assertNotIn("jaxlib", blocked)

    def test_build_audit_rejects_gpu_packages_before_importing_torch(self):
        package = Mock(metadata={"Name": "nvidia-cudnn-cu13"})
        with patch("tools.check_cpu_runtime.importlib.metadata.distributions", return_value=[package]):
            with self.assertRaisesRegex(RuntimeError, "nvidia-cudnn-cu13"):
                check_runtime()

    def test_conversion_worker_overrides_inherited_accelerator_selection(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0", "JAX_PLATFORMS": "cuda"}):
            configure_cpu_environment()
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "")
            self.assertEqual(os.environ["JAX_PLATFORMS"], "cpu")


if __name__ == "__main__":
    unittest.main()
