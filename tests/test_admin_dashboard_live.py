from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminDashboardLiveContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_dashboard_reads_real_statistics_and_health(self):
        self.assertIn("/api/dashboard/stats?range=", self.js)
        self.assertIn("fetch('/healthz')", self.js)
        self.assertIn("state.dashboardStats", self.js)
        self.assertIn("dataSource", self.js)
        self.assertIn('id="overview-live-summary"', self.html)
        self.assertIn("txt('overview-live-summary'", self.js)

    def test_fixed_dashboard_statistics_are_removed(self):
        for marker in ("events:'128'", "alerts:'06'", "resolution:'67%'", "VERIFICATION_USAGE_MOCK"):
            self.assertNotIn(marker, self.js)
        for marker in (">128<", ">92<", ">38%<", "SQLite · 12.4 MB"):
            self.assertNotIn(marker, self.html)
        self.assertNotIn("服务器正在守护 4 路视频", self.html)

    def test_real_empty_and_error_states_are_visible(self):
        for marker in ("暂无告警事件", "当前没有视频流会话", "统计不可用", "正在读取真实数据"):
            self.assertIn(marker, self.js + self.html)

    def test_missing_gpu_metric_is_not_coerced_to_zero(self):
        self.assertIn("item[1]==null||item[1]===''?null:Number(item[1])", self.js)
        self.assertIn("value===null?'不可用'", self.js)


if __name__ == "__main__":
    unittest.main()
