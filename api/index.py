"""
Vercel Python serverless entry for FastAPI.

Browser calls:  /api/auth/login, /api/health, …
This module strips the `/api` prefix and dispatches to backend routers.
"""
from __future__ import annotations

import json
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


def _pure_asgi_error_app(exc: BaseException):
    """Fallback ASGI app with zero third-party deps (works even if fastapi missing)."""
    detail = f"{type(exc).__name__}: {exc}"
    tb = traceback.format_exc()[-3500:]
    body = json.dumps(
        {
            "ok": False,
            "error": "startup_failed",
            "detail": detail,
            "hint": (
                "Build must run: python -m pip install -r requirements.txt. "
                "Also set JWT_SECRET, DATABASE_URL (Postgres), FRONTEND_URL, CORS_ORIGINS "
                "in Vercel Project Settings → Environment Variables, then redeploy."
            ),
            "traceback": tb,
        }
    ).encode("utf-8")

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def _build_error_app(exc: BaseException):
    try:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        err_app = FastAPI(title="AI Assistant — startup error")
        detail = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()

        @err_app.api_route(
            "/{full_path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
        @err_app.api_route(
            "/",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
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
    except Exception:  # noqa: BLE001
        return _pure_asgi_error_app(exc)


try:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from app.main import app as _backend_app

    def _resolve_path(scope: Scope) -> str:
        path = scope.get("path") or "/"
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        raw = headers.get("x-forwarded-uri") or headers.get("x-url") or ""
        if raw:
            if raw.startswith("http"):
                path = urlparse(raw).path or path
            elif raw.startswith("/"):
                path = raw
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
                    scope["path"] = "/health"
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
