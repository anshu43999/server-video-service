"""Real HTTP application worker; only filesystem/configuration are isolated."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    runtime = Path(os.environ["TIERED_ACCEPTANCE_RUNTIME"]).resolve()
    if runtime != Path.cwd().resolve() or not runtime.name.startswith("m37-acceptance-"):
        raise RuntimeError("worker requires its explicitly isolated runtime directory")
    from sqlalchemy.engine import make_url
    if not str(make_url(os.environ["DATABASE_URL"]).query.get("options", "")).startswith("-csearch_path=m37_acceptance_"):
        raise RuntimeError("worker must never connect to the business schema")
    for key in ("ADMIN_TOKEN", "MOBILE_TOKEN", "VERIFICATION_PROVIDER_ENDPOINT",
                "VERIFICATION_PROVIDER_API_KEY"):
        os.environ.pop(key, None)
    os.environ["CALIBRATION_ROOT"] = str(runtime / "calibration")
    os.environ["DEPLOYMENT_ENV"] = "production"
    registry = runtime / "models" / "registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"schemaVersion": 1, "models": []}), encoding="utf-8")
    from app.model_catalog import ModelCatalog
    original_init = ModelCatalog.__init__

    def isolated_init(self, registry_path=None):
        original_init(self, registry)

    # Redirect the model filesystem, not routes, auth, database or object storage.
    ModelCatalog.__init__ = isolated_init
    import uvicorn
    from app.main import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1",
        port=int(os.environ["TIERED_ACCEPTANCE_PORT"]), access_log=False, log_level="warning"))

    def stop_on_stdin():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop_on_stdin, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
