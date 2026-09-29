"""Move inline alert images from PostgreSQL JSON payloads to MinIO.

This is an explicit operational migration. It is intentionally not run from
the container entrypoint because object uploads can take a long time and must
be observed independently from an application rollout.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alert_evidence import AlertEvidenceStore
from app.config import settings
from app.database import (
    AlertEventRecord,
    DatabaseManager,
    FalsePositiveFeedbackRecord,
)


def _inline_data_url(payload: dict[str, Any]) -> str | None:
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return None
    candidate = evidence.get("snapshotDataUrl")
    if isinstance(candidate, str) and candidate.startswith("data:image/"):
        return candidate
    candidate = evidence.get("snapshotUri")
    if isinstance(candidate, str) and candidate.startswith("data:image/"):
        return candidate
    return None


def _replace_feedback_data_urls(payload: dict[str, Any], snapshot_uri: str) -> dict[str, Any]:
    updated = deepcopy(payload)
    for key in ("image", "screenshot"):
        value = updated.get(key)
        if isinstance(value, str) and value.startswith("data:image/"):
            updated[key] = snapshot_uri
    return updated


def migrate(
    database: DatabaseManager,
    store: AlertEvidenceStore | None,
    *,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    if not database.enabled:
        raise ValueError("DATABASE_URL is required")
    if not dry_run and (store is None or not store.enabled):
        raise ValueError("MinIO configuration is required unless --dry-run is used")

    scanned = candidates = migrated = feedback_updated = selected = 0
    last_event_id: str | None = None
    stop = False
    while not stop:
        with database.session() as session:
            query = select(AlertEventRecord).order_by(AlertEventRecord.event_id).limit(batch_size)
            if last_event_id is not None:
                query = query.where(AlertEventRecord.event_id > last_event_id)
            rows = session.scalars(query).all()
            if not rows:
                break
            for row in rows:
                last_event_id = row.event_id
                scanned += 1
                payload = deepcopy(dict(row.payload))
                data_url = _inline_data_url(payload)
                if data_url is None:
                    continue
                if limit is not None and selected >= limit:
                    stop = True
                    break
                candidates += 1
                selected += 1
                if dry_run:
                    continue

                assert store is not None
                reference = store.store_data_url(row.event_id, data_url)
                evidence = dict(payload.get("evidence") or {})
                evidence.pop("snapshotDataUrl", None)
                if isinstance(evidence.get("snapshotUri"), str) and evidence["snapshotUri"].startswith("data:image/"):
                    evidence.pop("snapshotUri", None)
                evidence.update(reference)
                payload["evidence"] = evidence
                row.payload = payload

                feedback_rows = session.scalars(
                    select(FalsePositiveFeedbackRecord).where(
                        FalsePositiveFeedbackRecord.event_id == row.event_id
                    )
                ).all()
                for feedback in feedback_rows:
                    updated = _replace_feedback_data_urls(
                        dict(feedback.payload), reference["snapshotUri"]
                    )
                    if updated != feedback.payload:
                        feedback.payload = updated
                        feedback_updated += 1
                migrated += 1
            if len(rows) < batch_size:
                break
    return {
        "scanned": scanned,
        "candidates": candidates,
        "migrated": migrated,
        "feedbackUpdated": feedback_updated,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    database = DatabaseManager(
        args.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    store = None if args.dry_run else AlertEvidenceStore.from_settings(settings)
    try:
        if store is not None:
            store.validate()
        result = migrate(
            database,
            store,
            batch_size=args.batch_size,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        database.close()
    print(json.dumps({"dryRun": args.dry_run, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
