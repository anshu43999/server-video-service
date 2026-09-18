from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminLoginViewTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.conversion = (ROOT / "app" / "static" / "conversion.js").read_text(encoding="utf-8")
        self.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    def test_login_gate_and_first_admin_setup_are_present(self):
        for marker in ("auth-gate", "auth-form", "auth-username", "auth-password", "admin-user-button"):
            self.assertIn(marker, self.html)
        for marker in ("/api/auth/status", "/api/auth/setup", "/api/auth/login", "/api/auth/logout"):
            self.assertIn(marker, self.js)
        self.assertIn("auth-locked", self.css)

    def test_business_boot_waits_for_authenticated_session(self):
        self.assertIn("function startAuthenticatedAdmin", self.js)
        self.assertIn("if(!adminAuth.ready||window.__aiyoloAdminStarted)return", self.js)
        self.assertIn("startAuthenticatedAdmin();", self.js)
        self.assertIn("Business data is rendered only after the authentication gate opens", self.js)
        self.assertNotIn("localStorage", self.js)

    def test_logout_stops_realtime_channels_and_allows_a_clean_login(self):
        self.assertIn("function disconnectAuthenticatedRealtime", self.js)
        self.assertIn("window.__aiyoloAdminStarted=false", self.js)
        self.assertIn("if(!adminAuth.ready || state.demo", self.js)
        self.assertIn("configureAuthForm(false)", self.js)

    def test_conversion_uses_shared_login_and_has_no_manual_token_input(self):
        self.assertIn("当前管理员登录会话", self.conversion)
        self.assertIn("aiyolo-authenticated", self.conversion)
        self.assertNotIn("conversion-token", self.conversion)
        self.assertNotIn("管理员令牌（仅当前页面内存）", self.conversion)


if __name__ == "__main__":
    unittest.main()
