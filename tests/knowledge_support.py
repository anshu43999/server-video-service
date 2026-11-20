"""Knowledge test fixtures only; no product seeding or project write path."""
from copy import deepcopy
from datetime import datetime, timezone
from app.alert_advice_knowledge import ACTIVE, MOCK_SOURCE
from app.database import AlertAdviceKnowledgeEntryRecord, AlertAdviceKnowledgeRevisionRecord


def helmet_mock_seed() -> dict:
    return {
        "entryId": "mock-ppe-no-helmet-head",
        "alertTypeId": "PPE_NO_HELMET",
        "recognitionCategoryId": "HEAD",
        "status": ACTIVE,
        "payload": {
            "title": "未佩戴安全帽处置建议（模拟）",
            "riskDescription": "人员在指定作业区域未佩戴安全帽，可能暴露于坠物或碰撞风险。",
            "adviceTemplate": {
                "title": "未佩戴安全帽处置建议（模拟）",
                "steps": [
                    {"stepId": "pause-work", "order": 1, "title": "提醒并暂停相关作业", "instruction": "请现场人员先离开可能存在坠物或碰撞风险的作业区域。"},
                    {"stepId": "wear-helmet", "order": 2, "title": "佩戴合规安全帽", "instruction": "按现场要求正确佩戴并检查帽带等防护部件。"},
                    {"stepId": "review", "order": 3, "title": "复查并记录结果", "instruction": "确认防护措施落实后恢复作业，并按现场流程记录处理情况。"},
                ],
                "cautions": ["请结合现场条件和适用制度核实；本建议不构成违规认定。"],
            },
            "references": [{
                "referenceId": "mock-ppe-management-v1", "documentTitle": "个人防护用品管理制度（模拟资料）",
                "documentNumber": None, "documentVersion": "demo-v1", "chapter": None,
                "clauseId": "模拟条款 PPE-01", "excerpt": "进入指定作业区域时，应按现场要求正确佩戴适用的个人防护用品。",
                "sourceName": "AI YOLO 演示模拟知识库", "sourceType": MOCK_SOURCE, "effectiveDate": None,
            }],
            "applicability": "仅用于 PPE_NO_HELMET + HEAD 精确匹配的演示告警。",
            "sourceType": MOCK_SOURCE,
        },
    }

def add_legacy_knowledge(database, project_id, payload):
    now = datetime.now(timezone.utc)
    snapshot = {**deepcopy(payload), "entryId": "legacy-private", "projectId": project_id,
                "matchKey": {"alertTypeId": "PPE_NO_HELMET", "recognitionCategoryId": "HEAD"},
                "status": "INACTIVE", "revision": 1, "createdBy": "old-owner", "updatedBy": "old-owner",
                "createdAt": now.isoformat(), "updatedAt": now.isoformat()}
    with database.session() as session:
        session.add(AlertAdviceKnowledgeEntryRecord(project_id=project_id, entry_id="legacy-private",
            alert_type_id="PPE_NO_HELMET", recognition_category_id="HEAD", status="INACTIVE",
            revision=1, payload=deepcopy(payload), created_by="old-owner", updated_by="old-owner",
            created_at=now, updated_at=now))
        session.flush()
        session.add(AlertAdviceKnowledgeRevisionRecord(project_id=project_id, entry_id="legacy-private",
            revision=1, action="CREATE", actor="old-owner", snapshot=deepcopy(snapshot)))
    return snapshot


def assert_legacy_knowledge(test, database, project_id, snapshot):
    with database.session() as session:
        row = session.get(AlertAdviceKnowledgeEntryRecord, (project_id, "legacy-private"))
        test.assertEqual("INACTIVE", row.status)
        test.assertEqual(snapshot["title"], row.payload["title"])
        revision = session.get(AlertAdviceKnowledgeRevisionRecord, (project_id, "legacy-private", 1))
        test.assertEqual(snapshot, revision.snapshot)
