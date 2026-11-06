"""Isolated real business routes for browser tests, without production lifespan.

All catalog/profile/calibration/evidence paths live under TemporaryDirectory.
No inference, conversion workers, external delivery or database is started.
Authorization dependencies and business handlers are the production objects.
"""
import importlib
import hashlib
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def mount_business(app, admin):
    from app import auth, config
    database_module = importlib.import_module("app.database")
    database_module.database = auth.database
    from app.model_catalog import ModelCatalog
    from app.model_parameters import ModelParameterStore
    from app.project_management import (
        _create_project, _create_membership,
        ProjectCreateRequest, MembershipCreateRequest,
    )
    from app.project_auth import ProjectContext, PROJECT_OWNER_CAPABILITIES
    from app.stream_config import StreamConfiguration
    temp = tempfile.TemporaryDirectory(prefix="aiyolo-business-browser-")
    app.state.business_temp = temp
    root = Path(temp.name)
    models = root / "models"
    models.mkdir()
    rows = []
    for version in ("1.0.0", "2.0.0"):
        artifact = models / (version + ".pt")
        artifact.write_bytes(("browser-test-asset-" + version).encode())
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        rows.append({
            "modelId": "helmet", "name": "安全帽检测", "version": version, "scenario": "ppe",
            "purpose": "test", "runtime": "server-pt", "format": "pt", "path": "models/" + artifact.name,
            "sizeBytes": artifact.stat().st_size, "sha256": digest, "labels": ["head"],
            "releaseEligible": True, "status": "PUBLISHED",
            "artifacts": [{"artifactId": "server", "format": "pt", "platform": "server",
                          "path": "models/" + artifact.name, "sizeBytes": artifact.stat().st_size, "sha256": digest}],
        })
    # Independent dual-target release for M36-T08. Existing PC-only fixtures stay unchanged.
    dual_pc = models / "dual.pt"
    dual_pc.write_bytes(b"isolated-dual-pc")
    dual_mobile = models / "dual.tflite"
    dual_mobile.write_bytes(b"isolated-dual-mobile")
    rows.append({"modelId": "dual", "name": "双端验收模型", "version": "1.0.0", "scenario": "dual-ppe",
        "runtime": "server-pt", "format": "pt", "path": "models/dual.pt", "labels": ["head"],
        "sizeBytes": dual_pc.stat().st_size, "sha256": hashlib.sha256(dual_pc.read_bytes()).hexdigest(),
        "supportedTargets": ["pc", "mobile"], "status": "PUBLISHED", "releaseEligible": True,
        "androidReady": True, "androidConverted": True, "signatureStatus": "signed",
        "artifacts": [{"artifactId": name, "platform": platform, "format": fmt, "path": "models/" + path.name,
            "sizeBytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, platform, fmt, path in (("server", "server", "pt", dual_pc), ("android", "android", "tflite", dual_mobile))]})
    registry = models / "registry.json"
    registry.write_text(json.dumps({"models": rows}), encoding="utf-8")
    catalog, profiles = ModelCatalog(registry), ModelParameterStore(models / "profiles.json")
    config.settings = auth.settings.model_copy(update={"calibration_root": str(root / "calibration")})
    # Construction only is redirected; no business handler or guard is mocked.
    with patch("app.model_catalog.ModelCatalog", return_value=catalog), patch("app.model_parameters.ModelParameterStore", return_value=profiles):
        main = importlib.import_module("app.main")
    main.model_catalog, main.model_parameter_store = catalog, profiles
    # FastAPI may retain include_router() entries as lazy _IncludedRouter
    # objects.  The selective route-copy loop below intentionally copies only
    # concrete product routes, so mount this router explicitly for the browser
    # fixture instead of depending on FastAPI's internal wrapper shape.
    from app.project_scenes import create_scene_router
    app.include_router(create_scene_router(lambda: main.project_scenes))
    allowed = ("/aiyoloapi/projects/{project_id}/", "/aiyoloapi/platform/models/", "/aiyoloapi/models",
               "/aiyoloapi/streams", "/aiyoloapi/rules", "/aiyoloapi/verification", "/aiyoloapi/alerts", "/aiyoloapi/metrics", "/aiyoloapi/conversion")
    existing = {getattr(route, "path", "") for route in app.routes}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if path.startswith(allowed) and path not in existing:
            app.router.routes.append(route)

    # M34-T05 browser fixture ONLY: insert a confirmed event, not a model result.
    # Production never mounts this module or this test-only endpoint.
    from fastapi import Depends
    from app.project_auth import PROJECT_SETTINGS_MANAGE, require_project_capability

    @app.post("/__test__/projects/{project_id}/confirmed-alert/{event_id}")
    async def confirmed_alert(project_id: str, event_id: str,
                              context=Depends(require_project_capability(PROJECT_SETTINGS_MANAGE))):
        try:
            event = main.alert_disposition_store.get(event_id, context.project_id)
        except KeyError:
            now = time.time_ns() // 1000
            event = main.alert_disposition_store.register({
                "eventId": event_id, "origin": "SERVER_STREAM", "streamId": "test-camera",
                "sourceId": "test-camera", "ruleId": "test-person", "label": "person",
                "displayName": "测试人员告警", "state": "CONFIRMED", "severity": "MAJOR",
                "startedAtUs": now, "confirmedAtUs": now, "lastSeenAtUs": now,
                "disposition": {"status": "OPEN"},
            }, project_id=context.project_id)
        main.alert_delivery.dispatch(event, ["management", "app"], project_id=context.project_id)
        await main.alert_delivery.drain()
        return event
    for suffix in ("1440", "390", "security", "reporting1440", "reporting390", "scene1440", "scene390", "dual1440", "dual390", "lifecycle1440", "lifecycle390"):
        owner = auth._create_account("business-owner-" + suffix, "business-test-password", auth.ROLE_OPERATOR)
        user = auth._create_account("business-user-" + suffix, "business-test-password", auth.ROLE_OPERATOR)
        project = _create_project(ProjectCreateRequest(projectCode="business-" + suffix,
            displayName="业务验收 " + suffix, ownerAccountId=owner.account_id), admin, "business-fixture")
        pid = project["projectId"]
        if suffix in {"scene1440", "scene390"}:
            for version in ("1.0.0", "2.0.0"):
                main.project_model_assignments.save(
                    pid, "helmet", version, "pc", 0, True, 0,
                    audit_reason="isolated scene browser fixture", _audit=False,
                )
        _create_membership(pid, MembershipCreateRequest(accountId=user.account_id),
                           ProjectContext(admin, pid, project["projectCode"], "ACTIVE", None,
                                          PROJECT_OWNER_CAPABILITIES, None, 1, True), "business-fixture")
        main.stream_config_store.create(StreamConfiguration(stream_id="gate", display_name="现场入口",
            source_type="websocket", source_url=None, model_id=None, yolo_enabled=False, confidence=0.25,
            max_fps=20, overlay_enabled=True, enabled=False, project_id=pid))
        main.rule_registry.upsert({"ruleId":"helmet-rule","name":"未戴安全帽告警","enabled":True,
            "operator":"PRESENCE","subjectKind":"track","requires":[],"targetLabels":["head"],
            "thresholds":{"minimumConfidence":0.5}}, expected_revision=0, project_id=pid)
        now = time.time_ns() // 1000
        main.alert_disposition_store.register({"eventId":"business-alert","ruleId":"helmet-rule",
            "sourceId":"gate","label":"head","state":"CONFIRMED","severity":"MAJOR",
            "notifySeverity":"MAJOR","startedAtUs":now,"confirmedAtUs":now,"lastSeenAtUs":now,
            "subjectKey":"track-1"}, project_id=pid)
