"""
Vercel Python serverless entry for FastAPI.

Browser calls:  /api/auth/login, /api/health, …
This module strips the `/api` prefix and dispatches to backend routers.

IMPORTANT: `app` must remain a FastAPI instance (not a plain ASGI wrapper)
so Vercel's FastAPI framework detector accepts this entrypoint.
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
    """Fallback ASGI app with zero third-party deps."""
    is_prod = (os.getenv("APP_ENV") or "").lower() == "production"
    detail = f"{type(exc).__name__}: {exc}" if not is_prod else "Server failed to start"
    tb = traceback.format_exc()[-3500:]
    payload = {
        "ok": False,
        "error": "startup_failed",
        "detail": detail,
        "hint": (
            "Install requirements; set JWT_SECRET, DATABASE_URL, FRONTEND_URL, "
            "CORS_ORIGINS, APP_ENV=production in Vercel env."
        ),
    }
    if not is_prod:
        payload["traceback"] = tb
    body = json.dumps(payload).encode("utf-8")

    async def _app(scope, receive, send):
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

    return _app


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
            # Never leak full tracebacks in production
            is_prod = (os.getenv("APP_ENV") or "").lower() == "production"
            body = {
                "ok": False,
                "error": "startup_failed",
                "detail": detail if not is_prod else "Server failed to start. Check environment variables.",
                "hint": (
                    "Set JWT_SECRET (≥32 chars), DATABASE_URL (Postgres), "
                    "FRONTEND_URL, CORS_ORIGINS, APP_ENV=production in Vercel, then redeploy."
                ),
            }
            if not is_prod:
                body["traceback"] = tb[-3500:]
            return JSONResponse(status_code=500, content=body)

        return err_app
    except Exception:  # noqa: BLE001
        return _pure_asgi_error_app(exc)


try:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    from app.main import app  # FastAPI instance — required name for Vercel detection

    class StripApiPrefixMiddleware(BaseHTTPMiddleware):
        """/api/auth/login → /auth/login for backend routers."""

        async def dispatch(self, request: Request, call_next):
            path = request.scope.get("path") or "/"
            headers = {
                k.decode().lower(): v.decode()
                for k, v in (request.scope.get("headers") or [])
            }
            raw = headers.get("x-forwarded-uri") or headers.get("x-url") or ""
            if raw:
                if raw.startswith("http"):
                    path = urlparse(raw).path or path
                elif raw.startswith("/"):
                    path = raw

            if path == "/api":
                request.scope["path"] = "/health"
                if "raw_path" in request.scope:
                    request.scope["raw_path"] = b"/health"
            elif path.startswith("/api/"):
                new_path = path[4:] or "/"
                request.scope["path"] = new_path
                if "raw_path" in request.scope:
                    request.scope["raw_path"] = new_path.encode("utf-8")

            return await call_next(request)

    # Keeps `app` typed as FastAPI (add_middleware, not ASGI reassignment)
    app.add_middleware(StripApiPrefixMiddleware)

    # Serve Vite SPA from public/ (built into public during Vercel buildCommand)
    _public = _ROOT / "public"
    if not _public.is_dir():
        # Fallback: frontend/dist if present in the bundle
        _public = _ROOT / "frontend" / "dist"
    _index = _public / "index.html"
    _assets = _public / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    if _index.is_file():

        @app.get("/")
        async def spa_root():
            return FileResponse(str(_index))

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Never serve SPA HTML for API paths (login/register must stay JSON)
            api_prefixes = (
                "auth/", "billing/", "agents/", "conversations/", "ws/",
                "keys/", "org/", "admin/", "integrations/", "training/",
                "templates/", "dashboard/", "system/", "health", "api/",
                "humans/", "ops/", "business/",
            )
            low = (full_path or "").lstrip("/").lower()
            if low == "health" or any(low.startswith(p) for p in api_prefixes):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"ok": False, "error": "not_found", "path": full_path},
                    status_code=404,
                )
            # Prefer real static files when present (favicon, etc.)
            candidate = _public / full_path
            if candidate.is_file() and _public in candidate.resolve().parents:
                return FileResponse(str(candidate))
            return FileResponse(str(_index))

except Exception as _exc:  # noqa: BLE001
    app = _build_error_app(_exc)
