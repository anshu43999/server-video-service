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
        for marker in ("VERIFICATION_MOCK", "verification-chip", "复核结论只做标注"):
            self.assertIn(marker, self.js)

    def test_usage_dashboard_has_all_required_breakdowns(self):
        for marker in ("verification-used", "verification-limit-display", "verification-conclusions", "verification-failures", "verification-before-rate", "verification-after-rate"):
            self.assertIn(marker, self.html)
        for marker in ("VERIFICATION_USAGE_MOCK", "today", "7d", "30d", "renderBreakdown"):
            self.assertIn(marker, self.js)

    def test_daily_limit_and_ranges_share_one_mock_source(self):
        self.assertIn("verification.limit", self.js)
        self.assertIn("VERIFICATION_USAGE_MOCK[range]", self.js)
        self.assertIn("verification.used/verification.limit", self.js)


if __name__ == "__main__":
    unittest.main()
