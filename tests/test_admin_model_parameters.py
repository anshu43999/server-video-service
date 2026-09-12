from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminModelParameterViewTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.conversion_js = (ROOT / "app" / "static" / "conversion.js").read_text(encoding="utf-8")
        self.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    def test_parameter_editor_has_platform_detection_alert_and_audit_sections(self):
        for marker in (
            "model-parameter-dialog",
            "data-parameter-platform=\"android\"",
            "data-parameter-platform=\"server\"",
            "parameter-confidence",
            "parameter-iou",
            "parameter-max-detections",
            "model-parameter-rules",
            "model-parameter-audit",
        ):
            self.assertIn(marker, self.html)

    def test_editor_uses_real_profile_routes_and_revision(self):
        for marker in ("/parameters?platform=${platform}", "method:'PUT'", "method:'DELETE'", "expectedRevision"):
            self.assertIn(marker, self.js)

    def test_head_semantics_and_delivery_boundary_are_explicit(self):
        self.assertIn("PPE_NO_HELMET", self.js)
        self.assertIn("未佩戴安全帽", self.js)
        self.assertIn("Android 参数同步和识别事件自动告警投递尚未接通", self.html)

    def test_parameter_and_activation_actions_are_independent(self):
        self.assertIn("data-model-parameters=", self.js)
        self.assertIn("data-model-activate=", self.js)
        self.assertIn("querySelectorAll('[data-model-activate]')", self.conversion_js)
        self.assertNotIn("querySelectorAll('[data-model-id]')", self.conversion_js)
        self.assertIn("if(!state.demo)await refreshLiveModels()", self.html)
        self.assertIn("conversion.js?v=20260912-model-room", self.html)

    def test_detection_terms_have_accessible_explanations(self):
        for marker in (
            "installParameterTermHelp",
            "保留检测结果的最低模型评分",
            "IoU 是两个检测框交集面积与并集面积的比值",
            "每一帧图像经过筛选和去重后",
            "help.setAttribute('aria-label'",
            "help.setAttribute('aria-expanded','false')",
            "help.setAttribute('aria-describedby',tip.id)",
            "event.key==='Escape'",
        ):
            self.assertIn(marker, self.js)
        for marker in (".term-tooltip[hidden]", ".term-help:focus-visible", "width:min(280px,100%)"):
            self.assertIn(marker, self.css)

    def test_alert_rule_headers_have_accessible_explanations(self):
        for marker in (
            "parameter-header-enabled-help",
            "parameter-header-category-help",
            "parameter-header-display-name-help",
            "parameter-header-event-code-help",
            "parameter-header-confidence-help",
            "parameter-header-consecutive-help",
            "parameter-header-dwell-help",
            "parameter-header-cooldown-help",
            "parameter-header-severity-help",
            "是否启用该类别对应的告警规则",
            "模型输出的原始类别标签",
            "系统内部稳定使用的机器可读事件标识",
            "不能低于检测置信度",
            "可减少单帧误报",
            "目标持续满足条件的最短时间",
            "抑制同类重复告警的时间",
            "用于后续处置优先级",
            "parameter-rule-head .term-help",
        ):
            self.assertTrue(marker in self.html or marker in self.js or marker in self.css, marker)

    def test_parameter_ranges_defaults_and_client_validation_are_explicit(self):
        for marker in (
            "取值范围 0.01-0.99，默认值 0.35，步进 0.01",
            "取值范围 0.10-0.90，默认值 0.45，步进 0.01",
            "取值范围 1-300，默认值 100，步进 1",
            "取值范围 0.01-0.99，默认值 0.55，步进 0.01",
            "取值范围 1-120，默认值 4，步进 1",
            "取值范围 0-600000，默认值 800，步进 100",
            "取值范围 0-86400000，默认值 60000，步进 1000",
            "input.dataset.default=meta.value",
            "必须在 ${min}-${max} 范围内",
        ):
            self.assertIn(marker, self.js)
        for marker in (
            'id="parameter-confidence" type="number" min="0.01" max="0.99" step="0.01"',
            'id="parameter-iou" type="number" min="0.10" max="0.90" step="0.01"',
            'id="parameter-max-detections" type="number" min="1" max="300" step="1"',
        ):
            self.assertIn(marker, self.html)

    def test_parameter_editor_has_desktop_and_mobile_layouts(self):
        for marker in (".model-card-actions", ".model-parameter-dialog", ".parameter-rule-row", "@media(max-width:600px)"):
            self.assertIn(marker, self.css)

    def test_parameter_editor_separates_still_image_and_camera_rules(self):
        for marker in (
            "parameter-common-section",
            "parameter-image-section",
            "parameter-camera-section",
            "类别通用参数",
            "现场拍照 · 图片识别告警参数",
            "相机巡检告警参数",
            "单张图片完成识别；此区域明确不配置连续帧和停留时间",
            "视频帧按连续帧、停留时间和冷却时间共同判定",
            "image.minimumConfidence",
            "image.cooldownMs",
            "camera.minimumConfidence",
            "camera.minimumConsecutiveFrames",
            "camera.minimumDwellTimeMs",
            "camera.cooldownMs",
            "schemaVersion:2",
        ):
            self.assertIn(marker, self.js)

    def test_image_rule_does_not_collect_camera_only_fields(self):
        image_start = self.js.index("const image=profile.alertRules.map")
        image_end = self.js.index("const camera=profile.alertRules.map", image_start)
        image_renderer = self.js[image_start:image_end]
        self.assertNotIn("minimumConsecutiveFrames", image_renderer)
        self.assertNotIn("minimumDwellTimeMs", image_renderer)
        self.assertIn("image.minimumConfidence", image_renderer)
        self.assertIn("image.cooldownMs", image_renderer)

    def test_parameter_ranges_and_migration_are_visible_for_v2(self):
        for marker in (
            "_migratedFromV1",
            "已按 v1 兼容规则映射到图片识别 / 相机巡检参数",
            "取值范围 0.01-0.99，默认值 0.55，步进 0.01",
            "取值范围 1-120，默认值 4，步进 1",
            "取值范围 0-600000，默认值 800，步进 100",
            "取值范围 0-86400000，默认值 60000，步进 1000",
            "参数校验失败 · ${error.message}",
            "保存失败 · ${error.message}",
        ):
            self.assertIn(marker, self.js)


if __name__ == "__main__":
    unittest.main()
