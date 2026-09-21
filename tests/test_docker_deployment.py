from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

from app.container_entrypoint import validate_environment
from app.calibration import CalibrationDatasetCatalog
from app.model_catalog import ModelCatalog


ROOT = Path(__file__).resolve().parents[1]


class DockerDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        cls.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        cls.converter_dockerfile = (ROOT / "Dockerfile.converter").read_text(encoding="utf-8")
        cls.env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_single_canonical_compose_and_deploy_entrypoint(self) -> None:
        self.assertTrue((ROOT / "compose.yml").is_file())
        self.assertFalse((ROOT / "compose.centos.yml").exists())
        self.assertFalse((ROOT / "docker-compose.yml").exists())
        script = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn('COMPOSE_FILE="${PROJECT_ROOT}/compose.yml"', script)
        self.assertIn('ENV_FILE="${AIYOLO_ENV_FILE:-${PROJECT_ROOT}/.env}"', script)
        self.assertIn("ADMIN_TOKEN|MOBILE_TOKEN", script)
        self.assertIn("development-only", script)

    def test_runtime_image_is_non_root_and_self_checking(self) -> None:
        self.assertIn("USER app", self.dockerfile)
        self.assertIn("HEALTHCHECK", self.dockerfile)
        self.assertIn("app.container_healthcheck", self.dockerfile)
        self.assertIn("app.container_entrypoint", self.dockerfile)
        self.assertIn("COPY --chown=app:app alembic", self.dockerfile)
        self.assertIn("YOLO_CONFIG_DIR=/tmp/Ultralytics", self.dockerfile)
        self.assertNotIn("COPY .env", self.dockerfile)

    def test_container_model_catalog_seed_is_valid_and_empty(self) -> None:
        registry = ROOT / "deploy" / "container-models" / "registry.json"
        catalog = ModelCatalog(registry)
        catalog.validate_startup()
        self.assertEqual([], catalog.list_models())
        self.assertIn("MODEL_SEED_PATH: /models", self.compose)

    def test_checked_in_seed_artifacts_match_registry(self) -> None:
        registry = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("models/**/*.json text eol=lf", attributes)
        for model in registry["models"]:
            for artifact in model["artifacts"]:
                path = artifact["path"]
                with self.subTest(path=path):
                    committed = subprocess.run(
                        ["git", "show", f"HEAD:{path}"],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                    ).stdout
                    self.assertEqual(artifact["sizeBytes"], len(committed))
                    self.assertEqual(
                        artifact["sha256"].lower(), hashlib.sha256(committed).hexdigest()
                    )

    def test_compose_has_database_media_and_application_health_gates(self) -> None:
        for service in ("postgres:", "mediamtx:", "model-converter:", "video-service:"):
            self.assertIn(service, self.compose)
        self.assertIn("image: postgres:16-alpine", self.compose)
        self.assertIn("image: bluenviron/mediamtx:1.20.1", self.compose)
        self.assertIn('test: ["CMD", "/mediamtx", "--version"]', self.compose)
        self.assertGreaterEqual(self.compose.count("condition: service_healthy"), 3)
        self.assertIn("postgres-data:/var/lib/postgresql/data", self.compose)
        self.assertIn("model-data:/app/models", self.compose)
        self.assertIn("evidence-data:/app/evidence", self.compose)
        self.assertIn("converter-data:/data", self.compose)
        self.assertIn("calibration-data:/app/calibration", self.compose)
        self.assertIn("calibration-data:/calibration:ro", self.compose)

    def test_converter_is_internal_isolated_and_resource_bounded(self) -> None:
        self.assertIn("dockerfile: Dockerfile.converter", self.compose)
        self.assertIn('CONVERSION_REMOTE_ENDPOINT: "http://model-converter:8090"', self.compose)
        self.assertIn("AIYOLO_REMOTE_CONVERSION_TOKEN", self.compose)
        self.assertIn("CONVERTER_TOKEN", self.compose)
        self.assertIn("CALIBRATION_ROOT: /app/calibration", self.compose)
        self.assertIn("CONVERTER_BUILTIN_CALIBRATION_MANIFEST: /app/calibration-builtin/manifest.json", self.compose)
        self.assertIn("mem_limit:", self.compose)
        self.assertIn("cpus:", self.compose)
        self.assertNotIn("8090:8090", self.compose)
        self.assertIn("USER converter", self.converter_dockerfile)
        self.assertIn("requirements-converter-service.txt", self.converter_dockerfile)
        self.assertIn("converter_service.healthcheck", self.converter_dockerfile)
        self.assertIn("COPY --chown=converter:converter calibration/builtin/dev8 /app/calibration-builtin", self.converter_dockerfile)
        self.assertNotIn("requirements-convert.txt", self.dockerfile)
        self.assertIn("requirements-verifier.txt", self.dockerfile)
        self.assertIn("COPY requirements.txt requirements-yolo.txt requirements-verifier.txt", self.dockerfile)

    def test_converter_image_contains_verified_offline_calibration_fixture(self) -> None:
        root = ROOT / "calibration" / "builtin" / "dev8"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("coco8-dev", manifest["datasetId"])
        self.assertEqual("conversion-smoke-test-only", manifest["purpose"])
        self.assertIn("Ultralytics COCO8", manifest["name"])
        self.assertIn("LICENSE", {item["path"] for item in manifest["files"]})
        images = [item for item in manifest["files"] if item["path"].startswith("images/")]
        labels = [item for item in manifest["files"] if item["path"].startswith("labels/")]
        self.assertEqual(8, len(images))
        self.assertEqual(8, len(labels))
        fingerprint = hashlib.sha256()
        for item in manifest["files"]:
            path = root / item["path"]
            content = path.read_bytes()
            self.assertEqual(item["sizeBytes"], len(content))
            actual = hashlib.sha256(content).hexdigest()
            self.assertEqual(item["sha256"], actual)
            fingerprint.update(item["path"].encode("utf-8") + b"\0")
            fingerprint.update(actual.encode("ascii") + b"\0")
        self.assertEqual(manifest["contentSha256"], fingerprint.hexdigest())
        builtin = CalibrationDatasetCatalog.builtin()
        self.assertEqual(manifest["contentSha256"], builtin["contentSha256"])
        self.assertEqual(sum(item["sizeBytes"] for item in manifest["files"]), builtin["sizeBytes"])
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!calibration/builtin/**", dockerignore)

    def test_compose_hardens_mounts_ports_and_logs(self) -> None:
        self.assertIn(":/models:ro,Z", self.compose)
        self.assertIn("CONTROL_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertIn("DIAGNOSTIC_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertIn("MEDIA_WEBRTC_UDP_PORT:-8189}:8189/udp", self.compose)
        self.assertIn("SRT_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertNotIn("5432:5432", self.compose)
        self.assertNotIn("9997:9997", self.compose)
        self.assertIn("read_only: true", self.compose)
        self.assertIn("no-new-privileges:true", self.compose)
        postgres_block = self.compose.split("  postgres:", 1)[1].split("\n  mediamtx:", 1)[0]
        self.assertIn("seccomp=unconfined", postgres_block)
        self.assertIn("no-new-privileges:true", postgres_block)
        self.assertEqual(1, self.compose.count("seccomp=unconfined"))
        self.assertIn('max-size: "20m"', self.compose)

    def test_production_environment_rejects_missing_security_settings(self) -> None:
        errors = validate_environment({"DEPLOYMENT_ENV": "production"})
        for field in (
            "DATABASE_URL", "MEDIAMTX_ENABLED",
            "MEDIAMTX_WHEP_URL", "MEDIAMTX_LLHLS_URL", "YOLO_MODEL_PATH",
        ):
            self.assertTrue(any(field in error for error in errors), field)

    def test_production_environment_rejects_development_static_tokens(self) -> None:
        errors = validate_environment({
            "DEPLOYMENT_ENV": "production",
            "ADMIN_TOKEN": "a" * 32,
            "MOBILE_TOKEN": "m" * 32,
        })
        self.assertTrue(any("ADMIN_TOKEN must not be set" in error for error in errors))
        self.assertTrue(any("MOBILE_TOKEN must not be set" in error for error in errors))

    def test_production_environment_accepts_complete_settings(self) -> None:
        with tempfile.NamedTemporaryFile() as model:
            errors = validate_environment({
                "DEPLOYMENT_ENV": "production",
                "DATABASE_URL": "postgresql+psycopg://user:pass@postgres/db",
                "MEDIAMTX_ENABLED": "true",
                "MEDIAMTX_WHEP_URL": "https://video.example.com:8889",
                "MEDIAMTX_LLHLS_URL": "https://video.example.com:8888",
                "REQUIRE_YOLO_MODEL": "true",
                "YOLO_MODEL_PATH": model.name,
            })
        self.assertEqual([], errors)

    def test_example_requires_operator_owned_values(self) -> None:
        for field in (
            "POSTGRES_PASSWORD", "DATABASE_URL", "CONVERTER_TOKEN", "MEDIA_PUBLIC_HOST",
            "CONVERSION_DEFAULT_CALIBRATION_DATASET_ID", "CALIBRATION_MAX_UPLOAD_BYTES",
            "CALIBRATION_MAX_EXPANDED_BYTES", "CALIBRATION_MAX_FILES",
        ):
            self.assertIn(f"{field}=", self.env_example)
        self.assertNotIn("ADMIN_TOKEN=", self.env_example)
        self.assertNotIn("MOBILE_TOKEN=", self.env_example)
        placeholder_lines = [line for line in self.env_example.splitlines() if "CHANGE_ME" in line]
        self.assertTrue(placeholder_lines)
        self.assertTrue(all(not line.lstrip().startswith("#") for line in placeholder_lines))

    def test_example_is_ready_for_direct_http_deployment(self) -> None:
        self.assertIn("CONTROL_BIND_ADDRESS=0.0.0.0", self.env_example)
        self.assertIn("CONTROL_PORT=18080", self.env_example)
        self.assertIn("MEDIA_BIND_ADDRESS=0.0.0.0", self.env_example)
        self.assertNotIn("127.0.0.1", self.env_example)
        self.assertNotIn("DIAGNOSTIC_BIND_ADDRESS=", self.env_example)
        self.assertNotIn("SRT_BIND_ADDRESS=", self.env_example)


if __name__ == "__main__":
    unittest.main()
