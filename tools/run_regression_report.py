"""Run an unchanged unittest suite, preserving full diagnostics in a local report."""
import argparse
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="tests")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / args.suite), pattern="test_*.py")
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".log").write_text(output.getvalue(), encoding="utf-8")
    report = {"at": datetime.now(timezone.utc).isoformat(), "suite": args.suite, "tests": result.testsRun,
              "failures": [str(test) for test, _ in result.failures], "errors": [str(test) for test, _ in result.errors],
              "skipped": [str(test) for test, _ in result.skipped], "passed": result.wasSuccessful()}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
