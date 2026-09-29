import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AdminLiveFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_production_first_paint_does_not_render_demo_business_data(self):
        self.assertIn("LIVE MODE", self.html)
        self.assertIn("if(!state.demo){$('push-table')", self.js)
        self.assertIn("Array.isArray(rows)&&!state.demo", self.js)
        self.assertIn("正在读取真实规则", self.js)

    def test_verification_form_has_no_example_credentials_or_endpoint(self):
        self.assertNotIn("gpt-4.1-mini", self.html)
        self.assertNotIn("https://api.example.com/v1", self.html)
        self.assertNotIn("Mock：尚未测试", self.html)


if __name__ == "__main__":
    unittest.main()
