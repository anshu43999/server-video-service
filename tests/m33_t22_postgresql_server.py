"""M33-T22 full FastAPI worker bound to an explicit isolated PostgreSQL URL.

The parent acceptance runner starts this module from a temporary working directory
without a .env file.  Model files are redirected before app.main is imported so
the complete application can start without reading or mutating the repository's
business model registry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

database_url = os.environ.get("M33_T22_DATABASE_URL", "")
runtime_root = Path(os.environ.get("M33_T22_RUNTIME_ROOT", "")).resolve()
if not database_url.startswith("postgresql+psycopg://"):
    raise RuntimeError("M33_T22_DATABASE_URL must be an explicit psycopg PostgreSQL URL")
if not runtime_root.is_dir():
    raise RuntimeError("M33_T22_RUNTIME_ROOT must be an existing isolated directory")

os.environ["DATABASE_URL"] = database_url
os.environ["DEPLOYMENT_ENV"] = "production"
os.environ["ADMIN_FRONTEND_MODE"] = "vue"
os.environ["LEGACY_APPROVAL_ORIGIN"] = os.environ["M33_T22_ORIGIN"]
os.environ["CALIBRATION_ROOT"] = str(runtime_root / "calibration")
os.environ.pop("ADMIN_TOKEN", None)
os.environ.pop("MOBILE_TOKEN", None)
for key in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
    os.environ.pop(key, None)

models = runtime_root / "models"
models.mkdir(parents=True, exist_ok=True)
registry = models / "registry.json"
registry.write_text(json.dumps({"schemaVersion": 1, "models": []}) + "\n", encoding="utf-8")
(runtime_root / "calibration").mkdir(parents=True, exist_ok=True)

from app.model_catalog import ModelCatalog

_original_init = ModelCatalog.__init__


def _isolated_init(self, registry_path=None):
    _original_init(self, registry)


ModelCatalog.__init__ = _isolated_init

from app.main import app  # noqa: E402,F401  complete app imported only after isolation
