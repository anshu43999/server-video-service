import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.conversion import ConversionConfig, ConversionPreflightError, ConversionService, ProcessRunner, environment_conversion_config


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = ConversionService(Path(self.tmp.name))
        self.config = ConversionConfig(mode="local", python_path=sys.executable)
        self.service.configure(self.config)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def wait(self, job):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = self.service.get(job["id"])
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.01)
        self.fail("worker did not finish")

    def test_config_roundtrip_and_fixed_argument_command(self):
        self.assertEqual(ConversionService(self.service.root).config(), self.config)
        command = ProcessRunner().command(self.config, "check", self.service.root / "space & directory")
        self.assertEqual(command[0], sys.executable)
        self.assertIn(str((self.service.root / "space & directory").resolve()), command)
        self.assertTrue(command[1].endswith("conversion_worker.py"))
        with self.assertRaises(ValueError):
            ConversionConfig(python_path="--bad")

    def test_wsl_preflight_runs_configured_interpreter(self):
        config = ConversionConfig(mode="wsl", distribution="Ubuntu", python_path="/venv/bin/python")
        completed = __import__("subprocess").CompletedProcess(
            ["wsl.exe"], 0, stdout=b"Python 3.12.3\n"
        )
        with patch("app.conversion.subprocess.run", return_value=completed) as probe:
            result = ProcessRunner().preflight(config)
        self.assertTrue(result["ok"])
        self.assertEqual(result["distribution"], "Ubuntu")
        self.assertEqual(probe.call_args.args[0], [
            "wsl.exe", "--distribution", "Ubuntu", "--exec", "/venv/bin/python", "--version"
        ])

    def test_wsl_preflight_rejects_access_denied_before_queueing(self):
        config = ConversionConfig(mode="wsl", distribution="Ubuntu", python_path="/venv/bin/python")
        output = "Wsl/Service/E_ACCESSDENIED\n".encode("utf-16")
        completed = __import__("subprocess").CompletedProcess(["wsl.exe"], -1, stdout=output)
        with patch("app.conversion.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(ConversionPreflightError, "退出码 4294967295.*E_ACCESSDENIED"):
                ProcessRunner().preflight(config)

        self.service.configure(config)
        with patch.object(self.service.runner, "preflight",
                          side_effect=ConversionPreflightError("WSL 连通性检测失败")):
            with self.assertRaises(ConversionPreflightError):
                self.service.submit("mobile")
        self.assertEqual(self.service.jobs(), [])

    def test_queued_jobs_survive_restart_and_use_config_snapshot(self):
        job = self.service.submit("check")
        self.service.configure(self.config.model_copy(update={"input_size": 320}))
        seen = []
        self.service.handler = lambda job, directory, config: seen.append(config.input_size) or {"ok": True}
        self.service.start()
        self.assertEqual(self.wait(job)["status"], "succeeded")
        self.assertEqual(seen, [640])

    def test_failure_retry_and_running_rejection(self):
        def failure(*args):
            raise RuntimeError("missing dependency")
        self.service.handler = failure
        job = self.service.submit("mobile")
        with self.assertRaises(ValueError):
            self.service.retry(job["id"])
        self.service.start()
        self.assertEqual(self.wait(job)["error"], "missing dependency")
        self.service.handler = lambda *args: {"ok": True}
        self.service.retry(job["id"])
        result = self.wait(job)
        self.assertEqual((result["status"], result["attempt"]), ("succeeded", 2))

    def test_stale_running_job_is_interrupted_and_attempt_cancelled(self):
        job = self.service.submit("mobile")
        self.service._save({**job, "status": "running"})
        self.service.start()
        self.assertEqual(self.service.get(job["id"])["status"], "interrupted")
        self.assertTrue((self.service.root / job["id"] / "1" / "cancel").is_file())

    def test_only_one_service_can_own_directory(self):
        self.service.start()
        other = ConversionService(self.service.root)
        with self.assertRaises(RuntimeError):
            other.start()

    def test_subprocess_error_without_result_is_actionable(self):
        with patch("app.conversion.subprocess.Popen") as spawn:
            process = spawn.return_value
            process.poll.return_value = 2
            process.returncode = 2
            with self.assertRaisesRegex(RuntimeError, "未返回结果"):
                ProcessRunner().run(self.config, "check", self.service.root / "failed", threading.Event())
            self.assertFalse(spawn.call_args.kwargs["shell"])

    def test_timeout_cancels_attempt_and_reaps_launcher(self):
        with patch("app.conversion.subprocess.Popen") as spawn, patch("app.conversion.time.monotonic", side_effect=[0, 10000]):
            process = spawn.return_value
            process.poll.return_value = None
            directory = self.service.root / "timed-out"
            with self.assertRaisesRegex(RuntimeError, "超时"):
                ProcessRunner().run(self.config, "mobile", directory, threading.Event())
            self.assertTrue((directory / "cancel").exists())
            process.kill.assert_called_once()
            process.wait.assert_called_once()

    def test_shutdown_signals_worker_cancellation(self):
        stopping = threading.Event()
        stopping.set()
        with patch("app.conversion.subprocess.Popen") as spawn:
            spawn.return_value.poll.return_value = None
            directory = self.service.root / "cancelled"
            with self.assertRaisesRegex(RuntimeError, "已中断"):
                ProcessRunner().run(self.config, "mobile", directory, stopping)
            self.assertTrue((directory / "cancel").exists())

    def test_remote_config_requires_https_and_persists_only_token_environment_name(self):
        with self.assertRaises(ValueError):
            ConversionConfig(mode="remote", remote_endpoint="http://converter.example")
        config = ConversionConfig(
            mode="remote",
            remote_endpoint="https://converter.example/v1",
            remote_token_env="AIYOLO_TEST_CONVERTER_TOKEN",
            python_path=sys.executable,
            remote_verifier_mode="local",
        )
        dumped = config.model_dump()
        self.assertEqual(dumped["remote_token_env"], "AIYOLO_TEST_CONVERTER_TOKEN")
        self.assertNotIn("AIYOLO_TEST_CONVERTER_TOKEN", json.dumps({
            key: value for key, value in dumped.items() if key != "remote_token_env"
        }))
        self.assertEqual(ProcessRunner().command(config, "check", self.service.root / "probe")[0], "remote-conversion")

    def test_remote_config_allows_explicit_local_http_development_endpoint(self):
        config = ConversionConfig(
            mode="remote",
            remote_endpoint="http://127.0.0.1:9000",
            remote_allow_insecure_http=True,
            python_path=sys.executable,
            remote_verifier_mode="local",
        )
        self.assertEqual(config.remote_endpoint, "http://127.0.0.1:9000")

    def test_container_environment_bootstraps_remote_config_without_persisting_secret(self):
        values = {
            "CONVERSION_REMOTE_ENDPOINT": "http://model-converter:8090",
            "CONVERSION_REMOTE_ALLOW_INSECURE_HTTP": "true",
            "CONVERSION_VERIFIER_PYTHON": sys.executable,
            "CONVERSION_CALIBRATION_DATA": "dataset.yaml",
            "CONVERSION_INPUT_SIZE": "416",
            "CONVERSION_TIMEOUT_SECONDS": "1200",
            "CONVERSION_AUTO_CONVERT": "true",
            "CONVERSION_REMOTE_TOKEN_ENV": "AIYOLO_REMOTE_CONVERSION_TOKEN",
            "AIYOLO_REMOTE_CONVERSION_TOKEN": "secret-not-part-of-config",
        }
        with patch.dict("os.environ", values, clear=True):
            config = environment_conversion_config()
            fresh = ConversionService(self.service.root / "environment-only").config()
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual("remote", config.mode)
        self.assertEqual(416, config.input_size)
        self.assertTrue(config.auto_convert)
        self.assertEqual(config, fresh)
        self.assertNotIn("secret-not-part-of-config", json.dumps(config.model_dump()))



if __name__ == "__main__":
    unittest.main()
