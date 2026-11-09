"""Static administration hosting, independent of business services and storage."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class AdminSPA(StaticFiles):
    """Only HTML navigation may fall back; missing assets stay real 404s."""

    async def get_response(self, path: str, scope):
        path = path.replace("\\", "/")
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            parts = Path(path).parts
            navigation = (
                scope["method"] in {"GET", "HEAD"}
                and "text/html" in dict(scope.get("headers", [])).get(b"accept", b"").decode()
                and not Path(path).suffix
                and not any(part.startswith(".") for part in parts)
                and not any(part in {"assets", "aiyoloapi", "healthz"} for part in parts)
            )
            if exc.status_code != 404 or not navigation:
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("assets/") and re.search(r"-[\w-]{8,}\.[\w.]+$", path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_admin_frontend(
    app: FastAPI,
    *,
    mode: str,
    build_dir: Path,
    preview_dir: Path,
) -> None:
    if mode != "vue":
        raise ValueError("ADMIN_FRONTEND_MODE must be vue; retired frontend requires restoring its local archive")
    if not (build_dir / "index.html").is_file():
        raise RuntimeError("ADMIN_FRONTEND_MODE=vue requires admin-web/dist/index.html; run npm run build")
    def mount(base: str, directory: Path, name: str) -> None:
        async def trailing_slash(request: Request):
            # A relative Location preserves the browser's HTTPS origin and any
            # prefix stripped by a proxy; do not trust forwarded headers here.
            target = base.lstrip("/") + "/"
            if request.url.query:
                target += "?" + request.url.query
            return RedirectResponse(target, status_code=307)

        app.add_api_route(base, trailing_slash, methods=["GET", "HEAD"],
                          include_in_schema=False, name=f"{name}-slash")
        app.mount(base, AdminSPA(directory=directory, html=True), name=name)

    mount("/admin", build_dir, "admin")
    if (preview_dir / "index.html").is_file():
        mount("/admin-next", preview_dir, "admin-preview")
