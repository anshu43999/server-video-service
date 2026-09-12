from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminRemoteConversionTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / "app" / "static" / "conversion.js").read_text(encoding="utf-8")

    def test_remote_mode_fields_and_config_payload_are_present(self):
        for marker in (
            'option value="remote"', "conversion-remote-endpoint", "conversion-remote-token-env",
            "conversion-remote-verifier", "conversion-remote-http", "remote_poll_interval_seconds",
        ):
            self.assertIn(marker, self.script)

    def test_page_never_collects_or_embeds_remote_token_value(self):
        self.assertNotIn("conversion-remote-token-value", self.script)
        self.assertNotIn("Authorization: Bearer", self.script)
        self.assertIn("令牌环境变量名", self.script)
        self.assertIn("页面不输入也不回显令牌", self.script)


if __name__ == "__main__":
    unittest.main()
