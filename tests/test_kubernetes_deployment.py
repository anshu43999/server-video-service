from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "deploy" / "k8s" / "production"


class KubernetesDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.video = (K8S / "video-service.yaml").read_text(encoding="utf-8")
        cls.converter = (K8S / "model-converter.yaml").read_text(encoding="utf-8")
        cls.services = (K8S / "services.yaml").read_text(encoding="utf-8")
        cls.ingress = (K8S / "ingress.yaml").read_text(encoding="utf-8")
        cls.config = (K8S / "config.env.example").read_text(encoding="utf-8")
        cls.secret = (K8S / "secret.env.example").read_text(encoding="utf-8")

    def test_all_manifests_are_valid_yaml(self) -> None:
        for path in K8S.glob("*.yaml"):
            with self.subTest(path=path.name):
                self.assertTrue(list(yaml.safe_load_all(path.read_text(encoding="utf-8"))))

    def test_video_service_uses_external_database_and_minio_secrets(self) -> None:
        self.assertIn("name: DATABASE_URL", self.video)
        self.assertIn("name: MINIO_ENDPOINT", self.video)
        self.assertIn("name: MINIO_ACCESS_KEY", self.video)
        self.assertIn("name: MINIO_SECRET_KEY", self.video)
        self.assertIn("name: aiyolo-runtime-secret", self.video)
        self.assertNotIn("kind: Secret", self.video)
        self.assertNotIn("kind: StatefulSet", self.video)
        self.assertIn("kind: Deployment", self.video)

    def test_workloads_are_hardened_and_observable(self) -> None:
        for document in (self.video, self.converter):
            self.assertIn("readOnlyRootFilesystem: true", document)
            self.assertIn("allowPrivilegeEscalation: false", document)
            self.assertIn("drop: [ALL]", document)
            self.assertIn("resources:", document)
            self.assertIn("startupProbe:", document)
            self.assertIn("readinessProbe:", document)
            self.assertIn("livenessProbe:", document)
        self.assertIn("runAsUser: 10001", self.video)
        self.assertIn("runAsUser: 10002", self.converter)

    def test_converter_is_internal_on_canonical_port_and_gets_no_database_secret(self) -> None:
        self.assertIn("containerPort: 8090", self.converter)
        self.assertIn("port: 8090", self.services)
        self.assertNotIn("8191", self.converter + self.services)
        self.assertNotIn("DATABASE_URL", self.converter)
        self.assertNotIn("MINIO_", self.converter)
        self.assertIn("http://aiyolo-model-converter:8090", self.video)

    def test_storage_and_ingress_match_production_contract(self) -> None:
        self.assertIn("persistentVolumeClaim", self.video)
        self.assertIn("persistentVolumeClaim", self.converter)
        self.assertIn("path: /aiyoloapi", self.ingress)
        self.assertNotIn("rewrite-target", self.ingress)
        self.assertIn('proxy-read-timeout: "3600"', self.ingress)

    def test_examples_contain_no_real_credentials(self) -> None:
        self.assertIn("MINIO_BUCKET=yolo-system", self.config)
        self.assertIn("MINIO_ALERT_PREFIX=alerts", self.config)
        self.assertIn("CHANGE_ME_DB_HOST", self.secret)
        self.assertIn("CHANGE_ME_MINIO_HOST", self.secret)
        self.assertNotIn("113.44.", self.secret + self.config)


if __name__ == "__main__":
    unittest.main()
