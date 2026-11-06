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
        self.assertIn('COMPOSE_OVERRIDE_LIST="${AIYOLO_COMPOSE_OVERRIDE_LIST:-/etc/aiyolo/compose-overrides.list}"', script)
        self.assertIn('COMPOSE_FILES=("${COMPOSE_FILE}")', script)
        self.assertIn('COMPOSE_FILES+=("${override_file}")', script)
        self.assertIn('Compose override paths must be absolute', script)
        self.assertIn('ENV_FILE="${AIYOLO_ENV_FILE:-${PROJECT_ROOT}/.env}"', script)
        self.assertIn("ADMIN_TOKEN|MOBILE_TOKEN", script)
        self.assertIn("development-only", script)
        self.assertIn("pg_dump --no-password --format=custom", script)
        self.assertIn('PGDATABASE="${pg_dump_url}" pg_dump', script)
        self.assertNotIn('--dbname="${pg_dump_url}"', script)
        self.assertIn('umask 077', script)
        self.assertIn("pg_dump is required for cloud database backups", script)
        self.assertIn('database_url="${DATABASE_URL:-}"', script)
        self.assertIn('"${ENV_FILE}"', script)
        self.assertIn("postgresql+psycopg:", script)
        self.assertNotIn("compose exec -T postgres", script)
        self.assertIn("pull-up)", script)
        self.assertIn("--no-build --wait --wait-timeout 300", script)
        self.assertIn("smoke)", script)
        self.assertIn("MINIO_OK", script)
        self.assertIn("production deployment refuses automatic database migrations", script)

    def test_production_database_upgrade_requires_offline_migration(self) -> None:
        self.assertIn('RUN_DATABASE_MIGRATIONS: "${RUN_DATABASE_MIGRATIONS:-false}"', self.compose)
        self.assertIn("RUN_DATABASE_MIGRATIONS=false", self.env_example)
        self.assertNotIn("RUN_DATABASE_MIGRATIONS=true", self.env_example)
        rejected = validate_environment({"DEPLOYMENT_ENV": "production", "RUN_DATABASE_MIGRATIONS": "true"})
        self.assertTrue(any("RUN_DATABASE_MIGRATIONS must be false" in error for error in rejected))
        for value in ("false", ""):
            with self.subTest(value=value):
                allowed = validate_environment({"DEPLOYMENT_ENV": "production", "RUN_DATABASE_MIGRATIONS": value})
                self.assertFalse(any("RUN_DATABASE_MIGRATIONS" in error for error in allowed))

    def test_runtime_image_is_non_root_and_self_checking(self) -> None:
        self.assertIn("USER app", self.dockerfile)
        self.assertIn("HEALTHCHECK", self.dockerfile)
        self.assertIn("app.container_healthcheck", self.dockerfile)
        self.assertIn("app.container_entrypoint", self.dockerfile)
        self.assertIn("COPY --chown=app:app alembic", self.dockerfile)
        self.assertIn("YOLO_CONFIG_DIR=/tmp/Ultralytics", self.dockerfile)
        self.assertNotIn("COPY .env", self.dockerfile)

    def test_both_images_enforce_cpu_dependencies_and_audit_before_shipping(self) -> None:
        for dockerfile in (self.dockerfile, self.converter_dockerfile):
            self.assertIn("COPY requirements-cpu.txt constraints-cpu.txt ./", dockerfile)
            self.assertIn("PIP_CONSTRAINT=/app/constraints-cpu.txt", dockerfile)
            self.assertIn('PIP_FIND_LINKS="https://download.pytorch.org/whl/cpu/torch/ https://download.pytorch.org/whl/cpu/torchvision/"', dockerfile)
            self.assertIn('CUDA_VISIBLE_DEVICES=""', dockerfile)
            self.assertIn("JAX_PLATFORMS=cpu", dockerfile)
            self.assertIn("&& pip check", dockerfile)
            self.assertIn("&& python tools/check_cpu_runtime.py", dockerfile)
        self.assertIn('YOLO_DEVICE: "cpu"', self.compose)
        self.assertIn("YOLO_DEVICE=cpu", self.env_example)
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!tools/check_cpu_runtime.py", dockerignore)

    def test_admin_frontend_is_reproducibly_built_outside_python_runtime(self) -> None:
        package = json.loads((ROOT / "admin-web" / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "admin-web" / "package-lock.json").read_text(encoding="utf-8"))
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertEqual(3, lock["lockfileVersion"])
        self.assertEqual(package["name"], lock["name"])
        self.assertIn("FROM node:", self.dockerfile)
        self.assertIn("AS admin-build", self.dockerfile)
        self.assertIn("COPY admin-web/package.json admin-web/package-lock.json", self.dockerfile)
        self.assertIn("RUN npm ci --no-audit --no-fund", self.dockerfile)
        self.assertIn("RUN npm run test && npm run build && npm run build:preview", self.dockerfile)
        self.assertIn("/admin-web/dist ./admin-web/dist", self.dockerfile)
        self.assertIn("/admin-web/dist-preview ./admin-web/dist-preview", self.dockerfile)
        self.assertIn("**/node_modules", dockerignore)
        self.assertIn("admin-web/dist", dockerignore)

    def test_container_model_catalog_seed_is_valid_and_empty(self) -> None:
        registry = ROOT / "deploy" / "container-models" / "registry.json"
        catalog = ModelCatalog(registry)
        catalog.validate_startup()
        self.assertEqual([], catalog.list_models())
        self.assertIn("MODEL_SEED_PATH: /models", self.compose)

    def test_checked_in_seed_artifacts_match_registry(self) -> None:
        # Compare one committed snapshot: the working catalog may contain local
        # uploads that intentionally never enter Git or a deployment seed.
        registry = json.loads(subprocess.run(
            ["git", "show", "HEAD:models/registry.json"], cwd=ROOT,
            check=True, capture_output=True,
        ).stdout)
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

    def test_compose_has_only_application_and_converter_health_gates(self) -> None:
        for service in ("model-converter:", "video-service:"):
            self.assertIn(service, self.compose)
        self.assertNotIn("mediamtx:", self.compose)
        self.assertEqual(1, self.compose.count("condition: service_healthy"))
        self.assertNotIn("postgres:", self.compose)
        self.assertNotIn("postgres-data", self.compose)
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
        self.assertNotIn("MEDIAMTX_", self.compose)
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
        self.assertNotIn("MEDIA_WEBRTC_UDP_PORT", self.compose)
        self.assertNotIn("SRT_BIND_ADDRESS", self.compose)
        self.assertNotIn("5432:5432", self.compose)
        self.assertNotIn("9997:9997", self.compose)
        self.assertIn("read_only: true", self.compose)
        self.assertIn("no-new-privileges:true", self.compose)
        self.assertNotIn("seccomp=unconfined", self.compose)
        self.assertIn('max-size: "20m"', self.compose)
        self.assertIn("VIDEO_SERVICE_CPUS", self.compose)
        self.assertIn("VIDEO_SERVICE_MEMORY_LIMIT", self.compose)
        self.assertIn("VIDEO_SERVICE_PIDS_LIMIT", self.compose)
        self.assertIn("CONVERTER_PIDS_LIMIT", self.compose)

    def test_production_environment_rejects_missing_security_settings(self) -> None:
        errors = validate_environment({"DEPLOYMENT_ENV": "production"})
        for field in (
            "DATABASE_URL", "YOLO_MODEL_PATH",
            "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET",
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
                "DATABASE_URL": "postgresql+psycopg://user:pass@db.example.com:5432/db?sslmode=require",
                "MINIO_ENDPOINT": "minio.internal:9000",
                "MINIO_ACCESS_KEY": "access-key",
                "MINIO_SECRET_KEY": "secret-key",
                "MINIO_BUCKET": "aiyolo-alerts",
                "REQUIRE_YOLO_MODEL": "true",
                "YOLO_MODEL_PATH": model.name,
            })
        self.assertEqual([], errors)

    def test_retired_media_settings_do_not_affect_production_validation(self):
        missing = validate_environment({"DEPLOYMENT_ENV": "production"})
        placeholder = validate_environment({
            "DEPLOYMENT_ENV": "production",
            "MEDIAMTX_INTERNAL_TOKEN": "CHANGE_ME_WITH_32_RANDOM_CHARACTERS",
        })
        self.assertEqual(missing, placeholder)
        self.assertFalse(any("MEDIAMTX" in error for error in missing))

    def test_example_requires_operator_owned_values(self) -> None:
        for field in (
            "DATABASE_URL", "CONVERTER_TOKEN",
            "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET",
            "CONVERSION_DEFAULT_CALIBRATION_DATASET_ID", "CALIBRATION_MAX_UPLOAD_BYTES",
            "CALIBRATION_MAX_EXPANDED_BYTES", "CALIBRATION_MAX_FILES",
        ):
            self.assertIn(f"{field}=", self.env_example)
        self.assertNotIn("ADMIN_TOKEN=", self.env_example)
        self.assertNotIn("MOBILE_TOKEN=", self.env_example)
        self.assertNotIn("POSTGRES_PASSWORD=", self.env_example)
        self.assertIn("CHANGE_ME_DATABASE_HOST", self.env_example)
        self.assertIn("sslmode=require", self.env_example)
        placeholder_lines = [line for line in self.env_example.splitlines() if "CHANGE_ME" in line]
        self.assertTrue(placeholder_lines)
        self.assertTrue(all(not line.lstrip().startswith("#") for line in placeholder_lines))

    def test_example_is_ready_for_direct_http_deployment(self) -> None:
        self.assertIn("CONTROL_BIND_ADDRESS=0.0.0.0", self.env_example)
        self.assertIn("CONTROL_PORT=18080", self.env_example)
        self.assertNotIn("MEDIA_BIND_ADDRESS", self.env_example)
        self.assertNotIn("127.0.0.1", self.env_example)
        self.assertNotIn("DIAGNOSTIC_BIND_ADDRESS=", self.env_example)
        self.assertNotIn("SRT_BIND_ADDRESS=", self.env_example)


if __name__ == "__main__":
    unittest.main()
