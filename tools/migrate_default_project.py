"""Offline default-project migration: inspect, prepare, verify, apply, reconcile, restore.

Set MIGRATION_DATABASE_URL explicitly. Credentials are never accepted on the
command line or printed. Restore uses MIGRATION_RESTORE_URL and never overwrites
the source. Bundles contain sensitive database/evidence backups.
"""
from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import project_migration as migration
from app.alert_evidence import AlertEvidenceStore
from app.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "prepare", "verify", "apply", "reconcile", "restore"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--evidence-root", action="append", type=Path, default=[])
    parser.add_argument("--maintenance", action="store_true")
    parser.add_argument("--archive-orphan-receipts", action="store_true",
                        help="apply only: preserve exact orphan rows in the verified bundle and remove them from online receipts")
    parser.add_argument("--evidence-bundle", type=Path,
                        help="prepare only: reuse hash-bound evidence from an explicitly selected verified backup")
    args = parser.parse_args()
    if args.archive_orphan_receipts and args.action != "apply":
        parser.error("--archive-orphan-receipts is only valid for apply")
    if args.evidence_bundle and args.action != "prepare":
        parser.error("--evidence-bundle is only valid for prepare")
    if args.action != "inspect" and args.bundle is None:
        parser.error("--bundle is required")
    env = "MIGRATION_RESTORE_URL" if args.action == "restore" else "MIGRATION_DATABASE_URL"
    url = os.environ.get(env)
    if args.action != "verify" and not url:
        parser.error(f"set {env} explicitly; .env DATABASE_URL is not selected automatically")
    try:
        if args.action == "inspect":
            with migration.database_connection(url) as connection:
                report = migration.preflight(connection)
                result = {"revision": report["revision"], "targetRevision": report["targetRevision"],
                          "tables": {k: v["count"] for k, v in report["tables"].items()},
                          "accountCount": len(report["accountMapping"]), "blockers": report["blockers"]}
        elif args.action == "prepare":
            result = migration.prepare(url, args.bundle, roots=args.evidence_root,
                                       store=AlertEvidenceStore.from_settings(settings), evidence_bundle=args.evidence_bundle)
        elif args.action == "verify":
            result = migration.summary(migration.verify_bundle(args.bundle), "backup-verified")
        elif args.action == "apply":
            result = migration.apply(url, args.bundle, maintenance=args.maintenance,
                                     archive_orphan_receipts=args.archive_orphan_receipts)
        elif args.action == "restore":
            result = migration.restore(url, args.bundle, maintenance=args.maintenance)
        else:
            manifest = migration.verify_bundle(args.bundle)
            with migration.database_connection(url) as connection:
                if migration.identity(connection) != manifest["source"]:
                    raise migration.MigrationError("backup belongs to another source")
                result = migration.reconcile(connection, args.bundle, manifest)
        print(json.dumps(result, ensure_ascii=False))
    except migration.MigrationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver and file exceptions may contain passwords, SQL payloads or URLs.
        print(json.dumps({"error": "migration operation failed", "type": type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
