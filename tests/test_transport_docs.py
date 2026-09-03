import unittest
from pathlib import Path


class TransportDecisionDocsTests(unittest.TestCase):
    """输出传输协议决策文档的契约测试。

    M04-T01 时这里断言 ADR-001 处于 ``accepted-for-MVP``。ADR-002 取代 ADR-001
    之后，契约变为：ADR-002 记录生效决策，ADR-001 明确标记为被取代。
    """

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.comparison = (root / "docs/transport-comparison.md").read_text(
            encoding="utf-8"
        )
        cls.adr_001 = (root / "docs/adr-001-output-protocol.md").read_text(
            encoding="utf-8"
        )
        cls.adr_002 = (root / "docs/adr-002-production-transport.md").read_text(
            encoding="utf-8"
        )

    def test_comparison_keeps_the_options_and_the_gate(self) -> None:
        for token in ("WebRTC", "LL-HLS", "SRT", "验证门禁"):
            self.assertIn(token, self.comparison)

    def test_comparison_points_at_the_current_decision(self) -> None:
        self.assertIn("adr-002-production-transport.md", self.comparison)

    def test_adr_001_is_marked_superseded(self) -> None:
        self.assertIn("superseded", self.adr_001)
        self.assertIn("不得作为实现依据", self.adr_001)
        self.assertIn("adr-002-production-transport.md", self.adr_001)
        self.assertNotIn("accepted-for-MVP", self.adr_001)

    def test_adr_002_freezes_the_protocol_layering(self) -> None:
        for token in ("WHEP", "LL-HLS", "RTSP", "MJPEG", "MediaMTX"):
            self.assertIn(token, self.adr_002)
        self.assertIn("取代", self.adr_002)

    def test_adr_002_pins_the_h264_constraints(self) -> None:
        for token in ("Baseline", "bf=0", "tune=zerolatency", "GOP"):
            self.assertIn(token, self.adr_002)

    def test_adr_002_keeps_the_unverified_items_explicit(self) -> None:
        self.assertIn("未验证项", self.adr_002)
        for token in ("libwebrtc", "NAT", "并发容量", "延迟"):
            self.assertIn(token, self.adr_002)


if __name__ == "__main__":
    unittest.main()
