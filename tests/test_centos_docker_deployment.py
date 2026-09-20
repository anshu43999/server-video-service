from pathlib import Path
import tempfile
import unittest

from app.container_entrypoint import validate_environment
from app.model_catalog import ModelCatalog


ROOT = Path(__file__).resolve().parents[1]


class CentOSDockerDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = (ROOT / "compose.centos.yml").read_text(encoding="utf-8")
        cls.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        cls.env_example = (ROOT / "deploy" / "centos" / ".env.example").read_text(encoding="utf-8")

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

    def test_compose_has_database_media_and_application_health_gates(self) -> None:
        for service in ("postgres:", "mediamtx:", "video-service:"):
            self.assertIn(service, self.compose)
        self.assertIn("image: postgres:16-alpine", self.compose)
        self.assertIn("image: bluenviron/mediamtx:1.20.1", self.compose)
        self.assertIn('test: ["CMD", "/mediamtx", "--version"]', self.compose)
        self.assertGreaterEqual(self.compose.count("condition: service_healthy"), 2)
        self.assertIn("postgres-data:/var/lib/postgresql/data", self.compose)
        self.assertIn("model-data:/app/models", self.compose)
        self.assertIn("evidence-data:/app/evidence", self.compose)

    def test_compose_hardens_mounts_ports_and_logs(self) -> None:
        self.assertIn(":/models:ro,Z", self.compose)
        self.assertIn("CONTROL_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertIn("DIAGNOSTIC_BIND_ADDRESS:-127.0.0.1", self.compose)
        self.assertIn("MEDIA_WEBRTC_UDP_PORT:-8189}:8189/udp", self.compose)
        self.assertNotIn("5432:5432", self.compose)
        self.assertNotIn("9997:9997", self.compose)
        self.assertIn("read_only: true", self.compose)
        self.assertIn("no-new-privileges:true", self.compose)
        self.assertIn('max-size: "20m"', self.compose)

    def test_production_environment_rejects_missing_security_settings(self) -> None:
        errors = validate_environment({"DEPLOYMENT_ENV": "production"})
        for field in (
            "DATABASE_URL", "ADMIN_TOKEN", "MOBILE_TOKEN", "MEDIAMTX_ENABLED",
            "MEDIAMTX_WHEP_URL", "MEDIAMTX_LLHLS_URL", "YOLO_MODEL_PATH",
        ):
            self.assertTrue(any(field in error for error in errors), field)

    def test_production_environment_accepts_complete_settings(self) -> None:
        with tempfile.NamedTemporaryFile() as model:
            errors = validate_environment({
                "DEPLOYMENT_ENV": "production",
                "DATABASE_URL": "postgresql+psycopg://user:pass@postgres/db",
                "ADMIN_TOKEN": "a" * 32,
                "MOBILE_TOKEN": "m" * 32,
                "MEDIAMTX_ENABLED": "true",
                "MEDIAMTX_WHEP_URL": "https://video.example.com:8889",
                "MEDIAMTX_LLHLS_URL": "https://video.example.com:8888",
                "REQUIRE_YOLO_MODEL": "true",
                "YOLO_MODEL_PATH": model.name,
            })
        self.assertEqual([], errors)

    def test_example_requires_operator_owned_values(self) -> None:
        for field in ("POSTGRES_PASSWORD", "DATABASE_URL", "ADMIN_TOKEN", "MOBILE_TOKEN", "MEDIA_PUBLIC_HOST"):
            self.assertIn(f"{field}=", self.env_example)
        self.assertNotIn("ADMIN_TOKEN=admin", self.env_example)
        placeholder_lines = [line for line in self.env_example.splitlines() if "CHANGE_ME" in line]
        self.assertTrue(placeholder_lines)
        self.assertTrue(all(not line.lstrip().startswith("#") for line in placeholder_lines))


if __name__ == "__main__":
    unittest.main()
