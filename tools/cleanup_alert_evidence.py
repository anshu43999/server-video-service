"""Operator-invoked, dry-run-by-default alert evidence retention job."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alert_evidence import AlertEvidenceStore
from app.alerts.evidence_retention import cleanup_alert_evidence
from app.config import settings
from app.database import DatabaseManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist marks/deletions (default: dry-run)")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--retention-days", type=int, default=settings.alert_evidence_retention_days)
    parser.add_argument("--grace-hours", type=int, default=settings.alert_evidence_delete_grace_hours)
    parser.add_argument("--after-project-id")
    parser.add_argument("--after-event-id")
    args = parser.parse_args()
    database = DatabaseManager(settings.database_url,
                               connect_timeout_seconds=settings.database_connect_timeout_seconds)
    store = AlertEvidenceStore.from_settings(settings)
    if bool(args.after_project_id) != bool(args.after_event_id):
        parser.error("--after-project-id and --after-event-id must be supplied together")
    after = (args.after_project_id, args.after_event_id) if args.after_project_id else None
    result = cleanup_alert_evidence(database, store, apply=args.apply,
                                    batch_size=args.batch_size, after=after,
                                    retention_days=args.retention_days,
                                    grace_hours=args.grace_hours)
    print(json.dumps(result, sort_keys=True))
    database.close()
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
