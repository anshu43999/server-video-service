from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminModelMarketViewTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.conversion_js = (ROOT / "app" / "static" / "conversion.js").read_text(encoding="utf-8")

    def test_model_market_and_stream_binding_panels_are_present(self):
        for marker in ("MODEL CONTROL ROOM", "model-scenario-filter", "model-catalog-state", "stream-binding-list", "model-detail-dialog"):
            self.assertIn(marker, self.html)

    def test_live_catalog_and_binding_routes_are_used(self):
        self.assertIn("fetch('/api/models')", self.js)
        self.assertIn("/api/streams/${encodeURIComponent(streamId)}/model", self.js)
        self.assertIn("method:'PUT'", self.js)
        self.assertIn("refreshLiveModels", self.js)

    def test_model_assets_have_no_mock_fallback(self):
        self.assertIn("function modelRows(){return state.models;}", self.js)
        self.assertIn("modelRows = () => state.models", self.conversion_js)
        self.assertNotIn("state.demo ? MOCK.models", self.conversion_js)
        self.assertNotIn("demoModelParameterProfile", self.js)
        self.assertIn("/parameters?platform=${platform}", self.js)
        self.assertIn("/parameters?platform=${state.parameterPlatform}", self.js)
        self.assertIn("refreshLiveModels();", self.conversion_js)
        self.assertIn("等待加载真实模型目录", self.html)
        self.assertIn("模型资产始终读取真实目录", self.html)
        self.assertIn("由真实服务校验路径、哈希和输出契约", self.html)

    def test_binding_projection_contains_scenario_and_purpose(self):
        self.assertIn("model.scenario", self.js)
        self.assertIn("model.purpose", self.js)
        self.assertIn("renderStreamBindings", self.js)

    def test_admin_page_does_not_render_registry_paths_or_tokens(self):
        self.assertNotIn("registry_path", self.js)
        self.assertNotIn("window.ADMIN_TOKEN=", self.js)
        self.assertNotIn("admin-secret", self.js)
        self.assertNotIn("absolute_path", self.js)

    def test_conversion_connects_automatically_without_legacy_button(self):
        self.assertNotIn("id=\"conversion-connect\"", self.conversion_js)
        self.assertNotIn("连接并读取配置", self.conversion_js)
        self.assertIn("byId('conversion-token').addEventListener('change'", self.conversion_js)
        self.assertIn("connect();", self.conversion_js)

    def test_model_catalog_has_search_summary_and_real_detail_projection(self):
        for marker in ("model-total", "model-server-ready", "model-android-ready", "model-active-count", "model-search-input"):
            self.assertIn(marker, self.html)
        for marker in ("function openModelDetails", "modelReadiness", "model-detail-artifacts", "data-model-detail"):
            self.assertIn(marker, self.js)


if __name__ == "__main__":
    unittest.main()
