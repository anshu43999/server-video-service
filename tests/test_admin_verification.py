from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminVerificationDashboardTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_verification_navigation_and_config_fields_exist(self):
        for marker in ("data-view=\"verification\"", "verification-provider", "verification-limit", "verification-image-consent"):
            self.assertIn(marker, self.html)

    def test_alert_review_conclusions_are_rendered(self):
        for marker in ("renderAlertVerification", "/verification", "verification-chip", "复核结论只做标注"):
            self.assertIn(marker, self.js)
        self.assertNotIn("VERIFICATION_MOCK", self.js)

    def test_usage_dashboard_has_all_required_breakdowns(self):
        for marker in ("verification-used", "verification-limit-display", "verification-conclusions", "verification-failures", "verification-before-rate", "verification-after-rate"):
            self.assertIn(marker, self.html)
        for marker in ("/api/dashboard/stats?range=", "today", "7d", "30d", "renderBreakdown"):
            self.assertIn(marker, self.js)

    def test_usage_ranges_use_real_stats_without_mock_fallback(self):
        self.assertIn("state.dashboardStats", self.js)
        self.assertIn("verification.used", self.js)
        self.assertIn("verification.limit", self.js)
        self.assertNotIn("VERIFICATION_USAGE_MOCK", self.js)


if __name__ == "__main__":
    unittest.main()
