from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminAlertCenterLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    def test_alert_center_has_no_fixed_or_mock_alerts(self):
        self.assertNotIn("MOCK.alerts", self.js)
        self.assertNotIn("VERIFICATION_MOCK", self.js)
        self.assertNotIn("alerts: [[", self.js)
        self.assertIn('id="nav-alert-count">--</em>', self.html)
        self.assertIn("txt('nav-alert-count'", self.js)
        for marker in ("全部 <b>06</b>", "严重 <b>02</b>", "重要 <b>03</b>", "一般 <b>01</b>"):
            self.assertNotIn(marker, self.html)

    def test_counts_and_rows_use_live_events(self):
        for identifier in ("alert-count-all", "alert-count-critical", "alert-count-important", "alert-count-normal"):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("txt(`alert-count-${key}`", self.js)
        self.assertIn("const all=Array.isArray(state.liveAlerts)?state.liveAlerts:[]", self.js)
        self.assertIn("data-event-id", self.js)

    def test_loading_empty_and_error_states_are_explicit(self):
        for marker in ("正在读取真实告警", "当前没有告警事件", "告警数据不可用", "重新加载"):
            self.assertIn(marker, self.js)
        self.assertIn("state.liveAlerts=[];state.alertsStatus='error'", self.js)

    def test_details_and_actions_bind_real_event_id(self):
        for marker in (
            "state.liveAlerts.find(item=>item.eventId===eventId)",
            "state.selectedAlert=event.eventId",
            "submitLiveDisposition(state.selectedAlert,'ACKNOWLEDGED')",
            "submitLiveDisposition(state.selectedAlert,'FALSE_POSITIVE')",
            "requestLiveVerification(event.eventId)",
        ):
            self.assertIn(marker, self.js)


if __name__ == "__main__":
    unittest.main()
