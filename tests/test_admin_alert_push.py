from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminAlertPushPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        cls.requirements = (ROOT / "PRODUCT_REQUIREMENTS.md").read_text(encoding="utf-8")

    def test_push_page_has_required_columns(self):
        self.assertIn('data-view="push"', self.html)
        self.assertIn('id="view-push"', self.html)
        for column in ("名称", "推送", "地址", "状态", "操作"):
            self.assertIn(f"<span>{column}</span>", self.html)

    def test_push_prototype_supports_management_and_test_delivery(self):
        for marker in ("pushTargets", "renderPushTargets", "simulatePush", "data-push-toggle", "data-push-test"):
            self.assertIn(marker, self.script)
        self.assertIn("push-form", self.script)

    def test_dialog_close_guards_are_installed_before_save_handlers(self):
        self.assertIn("close-btn", self.script)
        self.assertIn("submitter?.value==='cancel'", self.script)
        self.assertIn("closest('dialog')?.close()", self.script)

    def test_requirement_defines_event_driven_non_blocking_delivery(self):
        for requirement in ("有效事件", "已启用", "不得阻塞", "有限次数", "冷却和去重"):
            self.assertIn(requirement, self.requirements)


if __name__ == "__main__":
    unittest.main()
