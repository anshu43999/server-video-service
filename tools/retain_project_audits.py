"""Dry-run by default. Back up audits before explicitly using --apply."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.audit_retention import retain_audits
from app.database import database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--hold-project', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = retain_audits(database, days=args.days, batch_size=args.batch_size,
                               apply=args.apply, held_projects=args.hold_project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as error:
        parser.error(str(error))
    finally:
        database.close()


if __name__ == '__main__':
    main()
