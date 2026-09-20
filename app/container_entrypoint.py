from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping
from urllib.parse import urlparse


TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _public_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.hostname not in {"127.0.0.1", "localhost", "mediamtx"}
    )


def validate_environment(environ: Mapping[str, str]) -> list[str]:
    """Return production configuration errors without exposing secret values."""
    if environ.get("DEPLOYMENT_ENV", "development").strip().lower() != "production":
        return []

    errors: list[str] = []
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        errors.append("DATABASE_URL must be a PostgreSQL URL")

    for name in ("ADMIN_TOKEN", "MOBILE_TOKEN"):
        if environ.get(name, "").strip():
            errors.append(f"{name} must not be set in production; use account sessions")

    if not _enabled(environ.get("MEDIAMTX_ENABLED"), default=False):
        errors.append("MEDIAMTX_ENABLED must be true")
    for name in ("MEDIAMTX_WHEP_URL", "MEDIAMTX_LLHLS_URL"):
        if not _public_http_url(environ.get(name)):
            errors.append(f"{name} must be a client-reachable public HTTP(S) origin")

    if _enabled(environ.get("REQUIRE_YOLO_MODEL"), default=True):
        model_path = Path(environ.get("YOLO_MODEL_PATH", ""))
        if not model_path.is_file():
            errors.append("YOLO_MODEL_PATH must reference a readable model file")
    converter_endpoint = environ.get("CONVERSION_REMOTE_ENDPOINT", "").strip()
    if converter_endpoint:
        token_name = environ.get(
            "CONVERSION_REMOTE_TOKEN_ENV", "AIYOLO_REMOTE_CONVERSION_TOKEN"
        )
        if len(environ.get(token_name, "")) < 24:
            errors.append(f"{token_name} must contain at least 24 characters")
        verifier = Path(environ.get("CONVERSION_VERIFIER_PYTHON", ""))
        if not verifier.is_file():
            errors.append("CONVERSION_VERIFIER_PYTHON must reference the verifier Python")
        if not environ.get("CONVERSION_CALIBRATION_DATA", "").strip():
            errors.append("CONVERSION_CALIBRATION_DATA is required")
    return errors


def main() -> None:
    errors = validate_environment(os.environ)
    if errors:
        for error in errors:
            print(f"configuration error: {error}", file=sys.stderr)
        raise SystemExit(78)

    if os.environ.get("DATABASE_URL") and _enabled(
        os.environ.get("RUN_DATABASE_MIGRATIONS"), default=True
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
        )

    command = sys.argv[1:] or [sys.executable, "run.py"]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
