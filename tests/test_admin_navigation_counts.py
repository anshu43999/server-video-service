from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminNavigationCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_navigation_does_not_show_page_numbers_or_mock_push_count(self):
        self.assertIn('data-view="overview"><span>⌂</span> 总览</button>', self.html)
        self.assertIn('data-view="dashboard"><span>▥</span> 数据看板</button>', self.html)
        self.assertIn('data-view="push"><span>⇧</span> 报警推送</button>', self.html)
        self.assertNotIn('id="nav-push-count"', self.html)
        self.assertNotIn("txt('nav-push-count'", self.js)

    def test_live_counts_use_placeholders_until_real_requests_succeed(self):
        self.assertIn('id="nav-stream-count">--</em>', self.html)
        self.assertIn('id="nav-alert-count">--</em>', self.html)
        self.assertIn("!state.demo&&state.streamsStatus==='ready'", self.js)
        self.assertIn("state.streamsStatus='ready'", self.js)
        self.assertIn("state.alertsStatus==='ready'?String(counts.all)", self.js)


if __name__ == "__main__":
    unittest.main()
