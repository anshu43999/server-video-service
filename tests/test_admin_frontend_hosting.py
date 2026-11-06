import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin_frontend import mount_admin_frontend
from app.config import Settings


class AdminHostingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.build = self.root / "dist"
        self.preview = self.root / "dist-preview"
        for folder, label in [(self.build, "vue"), (self.preview, "preview")]:
            (folder / "assets").mkdir(parents=True)
            (folder / "index.html").write_text(f"<html>{label}</html>", encoding="utf-8")
            (folder / "assets" / "index-Ab123456.js").write_text("console.log('asset')", encoding="utf-8")
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def client(self, mode="vue"):
        app = FastAPI()
        mount_admin_frontend(app, mode=mode, build_dir=self.build, preview_dir=self.preview)

        @app.get("/healthz")
        def health():
            return {"ok": True}

        @app.get("/aiyoloapi/probe", status_code=401)
        def probe():
            return {"detail": "authentication required"}

        client = TestClient(app)
        self.clients.append(client)
        return client

    def test_vue_is_default_and_preview_is_independent(self):
        self.assertEqual(Settings(_env_file=None).admin_frontend_mode, "vue")
        client = self.client()
        self.assertIn("vue", client.get("/admin/").text)
        self.assertIn("preview", client.get("/admin-next/").text)

    def test_vue_deep_links_and_head_are_html_without_cache(self):
        client = self.client()
        for path in ["/admin/", "/admin/index.html", "/admin/models?pane=upload", "/admin/streams/example", "/admin-next/engineering"]:
            with self.subTest(path=path):
                response = client.get(path, headers={"Accept": "text/html"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-cache")
                self.assertIn("text/html", response.headers["content-type"])
        response = client.head("/admin/models", headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_missing_assets_and_non_navigation_never_receive_html(self):
        client = self.client()
        for path in ["/admin/assets/missing.js", "/admin/assets/missing", "/admin/favicon.ico", "/admin/aiyoloapi/probe", "/admin/healthz", "/admin/.env", "/admin/%2e%2e/outside.js"]:
            with self.subTest(path=path):
                response = client.get(path, headers={"Accept": "text/html"})
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("<html>", response.text)
        self.assertEqual(client.get("/admin/models", headers={"Accept": "application/json"}).status_code, 404)
        self.assertEqual(client.post("/admin/models", headers={"Accept": "text/html"}).status_code, 405)

    def test_hashed_assets_are_cached_and_api_is_not_swallowed(self):
        client = self.client()
        asset = client.get("/admin/assets/index-Ab123456.js")
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(client.get("/healthz").json(), {"ok": True})
        self.assertEqual(client.get("/aiyoloapi/probe").status_code, 401)
        self.assertEqual(client.get("/aiyoloapi/missing").status_code, 404)

    def test_missing_vue_build_fails_and_absent_preview_is_not_mounted(self):
        (self.build / "index.html").unlink()
        with self.assertRaisesRegex(RuntimeError, "npm run build"):
            self.client()
        (self.build / "index.html").write_text("<html>vue</html>", encoding="utf-8")
        (self.preview / "index.html").unlink()
        client = self.client()
        self.assertEqual(client.get("/admin-next/").status_code, 404)
        self.assertIn("vue", client.get("/admin/").text)

    def test_rejects_unknown_mode(self):
        for mode in ["legacy", "unknown"]:
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    self.client(mode)
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, admin_frontend_mode=mode)


class RealAdminBuildTests(unittest.TestCase):
    def test_both_real_builds_are_hosted_with_their_own_bases(self):
        root = Path(__file__).resolve().parents[1]
        build, preview = root / "admin-web/dist", root / "admin-web/dist-preview"
        if not all((directory / "index.html").is_file() for directory in [build, preview]):
            self.skipTest("Run admin-web npm run build and npm run build:preview for real-build integration")
        app = FastAPI()
        mount_admin_frontend(app, mode="vue", build_dir=build, preview_dir=preview)
        with TestClient(app) as client:
            import re
            for base in ["/admin/", "/admin-next/"]:
                response = client.get(base + "engineering", headers={"Accept": "text/html"})
                self.assertEqual(response.status_code, 200)
                urls = re.findall(r'(?:src|href)="([^"]+/assets/[^"]+)"', response.text)
                self.assertGreater(len(urls), 0)
                for url in urls:
                    self.assertTrue(url.startswith(base), url)
                    asset = client.get(url)
                    self.assertEqual(asset.status_code, 200)
                    self.assertIn("immutable", asset.headers["cache-control"])
