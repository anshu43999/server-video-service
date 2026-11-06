"""Set an audited, time-bounded sample-retention marker for alert evidence."""
import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alerts.evidence_retention import retain_alert_evidence
from app.config import settings
from app.database import DatabaseManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--evidence-type", choices=("thumbnail", "original"), required=True)
    parser.add_argument("--content-version", type=int, required=True)
    parser.add_argument("--until", required=True, help="timezone-aware ISO-8601 timestamp")
    parser.add_argument("--actor", required=True, help="operator identity for the audit trail")
    args = parser.parse_args()
    database = DatabaseManager(settings.database_url,
                               connect_timeout_seconds=settings.database_connect_timeout_seconds)
    try:
        result = retain_alert_evidence(
            database, project_id=args.project_id, event_id=args.event_id,
            evidence_type=args.evidence_type, content_version=args.content_version,
            until=datetime.fromisoformat(args.until.replace("Z", "+00:00")), actor=args.actor,
        )
        print(json.dumps(result, sort_keys=True))
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
