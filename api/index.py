"""
Vercel Python serverless entry for FastAPI.

Browser calls:  /api/auth/login, /api/health, …
This module strips the `/api` prefix and dispatches to backend routers.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("VERCEL", "1")


def _build_error_app(exc: BaseException):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    err_app = FastAPI(title="AI Assistant — startup error")
    detail = f"{type(exc).__name__}: {exc}"
    tb = traceback.format_exc()

    @err_app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @err_app.api_route("/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def startup_failed(full_path: str = ""):
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "startup_failed",
                "detail": detail,
                "hint": (
                    "In Vercel Project Settings → Environment Variables set at least: "
                    "JWT_SECRET, DATABASE_URL (Postgres), FRONTEND_URL, CORS_ORIGINS. "
                    "Redeploy after changing env. Check Function logs for full traceback."
                ),
                "traceback": tb[-3500:],
            },
        )

    return err_app


try:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from app.main import app as _backend_app

    def _resolve_path(scope: Scope) -> str:
        path = scope.get("path") or "/"
        # Recover original path if a rewrite collapsed it to /api
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        for key in ("x-forwarded-uri", "x-invoke-path", "x-matched-path", "x-vercel-forwarded-for"):
            # x-forwarded-uri may be full path
            pass
        raw = headers.get("x-forwarded-uri") or headers.get("x-url") or ""
        if raw:
            if raw.startswith("http"):
                path = urlparse(raw).path or path
            elif raw.startswith("/"):
                path = raw
        # Also check query url= (unlikely)
        return path

    class StripApiPrefix:
        """ASGI middleware: /api/auth/login → /auth/login for FastAPI routers."""

        def __init__(self, app: ASGIApp):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] in ("http", "websocket"):
                path = _resolve_path(scope)
                if path == "/api":
                    scope = dict(scope)
                    scope["path"] = "/health"  # bare /api → health
                    if "raw_path" in scope:
                        scope["raw_path"] = b"/health"
                elif path.startswith("/api/"):
                    new_path = path[4:] or "/"
                    scope = dict(scope)
                    scope["path"] = new_path
                    if "raw_path" in scope:
                        scope["raw_path"] = new_path.encode("utf-8")
            await self.app(scope, receive, send)

    app = StripApiPrefix(_backend_app)

except Exception as _exc:  # noqa: BLE001
    app = _build_error_app(_exc)
