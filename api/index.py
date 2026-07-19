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

    # ── AgentBay (aibusinessagent.xyz/bay/api) ────────────────────────────
    # Browser: /bay/api/...  →  Vercel rewrite → /api/__bay__/...
    # Middleware strips /api → /__bay__/... which matches routers below.
    _ab_path = _ROOT / "agentbay_backend"
    if _ab_path.is_dir():
        if str(_ab_path) not in sys.path:
            sys.path.insert(0, str(_ab_path))
        try:
            from agentbay.database import init_db as _bay_init_db
            from agentbay.schema_migrate import migrate as _bay_migrate
            from agentbay.seed import seed as _bay_seed
            from agentbay.routers import (
                auth as bay_auth,
                listings as bay_listings,
                orders as bay_orders,
                chat as bay_chat,
                catalog as bay_catalog,
                media as bay_media,
                bridge as bay_bridge,
            )

            _BAY_PREFIX = "/__bay__"
            for _r in (
                bay_auth.router,
                bay_listings.router,
                bay_orders.router,
                bay_chat.router,
                bay_catalog.router,
                bay_media.router,
                bay_bridge.router,
            ):
                app.include_router(_r, prefix=_BAY_PREFIX)

            @app.get(f"{_BAY_PREFIX}/health")
            def _bay_health():
                from agentbay import config as bay_cfg

                issues = bay_cfg.config_issues()
                return {
                    "ok": True,
                    "app": "AgentBay Marketplace",
                    "path": "/bay/api",
                    "demo": False,
                    "ready": len(issues) == 0,
                    "issues": issues,
                    "stripe": bay_cfg.stripe_enabled(),
                }

            # Cold-start critical path: migrate is cheap when columns exist;
            # seed() fast-returns when catalogue already present (see seed.py).
            try:
                _bay_init_db()
                _bay_migrate()
                _bay_seed()
            except Exception as _bay_boot:  # noqa: BLE001
                print(f"[startup] AgentBay db boot: {_bay_boot}")
            print("[startup] AgentBay routers at /bay/api (via /api/__bay__)")
        except Exception as _bay_exc:  # noqa: BLE001
            print(f"[startup] AgentBay not loaded: {_bay_exc}")

    # Static layout (Vercel buildCommand → public/):
    #   /              marketing website
    #   /agents/*      product SPA  (UI — must NOT hit API routers at /agents)
    #   /api/*         product API  (middleware strips /api → backend routes)
    #   /bay/*         AgentBay SPA
    #   /bay/api/*     AgentBay API
    _public = _ROOT / "public"
    _website = _ROOT / "website"
    _agents_dir = (
        (_public / "agents")
        if (_public / "agents" / "index.html").is_file()
        else (_ROOT / "frontend" / "dist")
    )
    _bay_dir = (
        (_public / "bay")
        if (_public / "bay" / "index.html").is_file()
        else (_ROOT / "bay-dist")
    )
    _marketing_index = None
    for _cand in (
        _public / "index.html",
        _website / "index.html",
    ):
        if _cand.is_file():
            # Prefer marketing; skip if it looks like the product SPA only
            try:
                _head = _cand.read_text(encoding="utf-8", errors="ignore")[:800]
            except Exception:  # noqa: BLE001
                _head = ""
            if "data-site-header" in _head or "AI Business Agent" in _head or "section-kicker" in _head:
                _marketing_index = _cand
                break
            if _marketing_index is None and "id=\"root\"" not in _head:
                _marketing_index = _cand
    if _marketing_index is None and (_website / "index.html").is_file():
        _marketing_index = _website / "index.html"

    _marketing_root = _marketing_index.parent if _marketing_index else _public

    def _safe_file(base: Path, rel: str) -> Path | None:
        if not base or not base.is_dir():
            return None
        rel = (rel or "").lstrip("/").replace("\\", "/")
        if not rel or ".." in rel.split("/"):
            return None
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _file_response(path: Path):
        # Cache hashed assets aggressively; HTML briefly so deploys pick up quickly.
        ext = path.suffix.lower()
        name = path.name.lower()
        headers: dict[str, str] = {}
        if ext in {".js", ".css", ".woff", ".woff2", ".ttf", ".map"}:
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".webp"}:
            headers["Cache-Control"] = "public, max-age=86400"
        elif name.endswith(".webmanifest") or ext == ".webmanifest":
            headers["Cache-Control"] = "public, max-age=300"
        elif ext in {".html", ""} or name == "index.html":
            headers["Cache-Control"] = "public, max-age=60, s-maxage=60, stale-while-revalidate=300"
        return FileResponse(str(path), headers=headers)

    def _resolve_request_path(request: Request) -> str:
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
        return path or "/"

    class StripApiPrefixMiddleware(BaseHTTPMiddleware):
        """/api/auth/login → /auth/login for backend routers.
        /api/__bay__/listings → /__bay__/listings (AgentBay).
        Does NOT rewrite browser UI paths (/agents, /bay).
        """

        async def dispatch(self, request: Request, call_next):
            path = _resolve_request_path(request)

            # Normalize /bay/api/* if it reaches the function without rewrite
            if path == "/bay/api" or path.startswith("/bay/api/"):
                rest = path[len("/bay/api") :] or ""
                path = "/api/__bay__" + rest
                request.scope["path"] = path
                if "raw_path" in request.scope:
                    request.scope["raw_path"] = path.encode("utf-8")

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

    class UiStaticMiddleware(BaseHTTPMiddleware):
        """Serve marketing + SPAs for browser paths BEFORE API routers match.

        Critical: backend agents API is mounted at /agents after /api is stripped.
        Browser UI is also under /agents — without this middleware, GET /agents/console
        hits the API and returns {"detail":"Not authenticated"}.
        """

        async def dispatch(self, request: Request, call_next):
            if request.method not in ("GET", "HEAD"):
                return await call_next(request)

            path = _resolve_request_path(request)

            # Never intercept real API traffic
            if (
                path == "/api"
                or path.startswith("/api/")
                or path == "/bay/api"
                or path.startswith("/bay/api/")
            ):
                return await call_next(request)

            # Root-level PWA / browser assets (browsers and older manifests request these
            # at domain root; product files live under /agents/)
            _root_aliases = {
                "/favicon.ico": "favicon.ico",
                "/favicon.png": "favicon.png",
                "/favicon-16.png": "favicon-16.png",
                "/favicon-32.png": "favicon-32.png",
                "/manifest.webmanifest": "manifest.webmanifest",
                "/logo.png": "logo.png",
                "/logo-256.png": "logo-256.png",
            }
            if path in _root_aliases:
                f = _safe_file(_agents_dir, _root_aliases[path])
                if f is not None:
                    return _file_response(f)
            if path.startswith("/icons/"):
                f = _safe_file(_agents_dir, path.lstrip("/"))
                if f is not None:
                    return _file_response(f)

            # Product SPA: /agents and /agents/*
            if path == "/agents" or path.startswith("/agents/"):
                rel = path[len("/agents") :].lstrip("/")
                if rel:
                    f = _safe_file(_agents_dir, rel)
                    if f is not None:
                        return _file_response(f)
                agents_index = _agents_dir / "index.html"
                if agents_index.is_file():
                    return _file_response(agents_index)

            # AgentBay SPA: /bay (API already excluded above)
            if path == "/bay" or path.startswith("/bay/"):
                rel = path[len("/bay") :].lstrip("/")
                if rel:
                    f = _safe_file(_bay_dir, rel)
                    if f is not None:
                        return _file_response(f)
                bay_index = _bay_dir / "index.html"
                if bay_index.is_file():
                    return _file_response(bay_index)

            # Marketing site root + static pages
            if path == "/":
                if _marketing_index and _marketing_index.is_file():
                    return _file_response(_marketing_index)
            elif _marketing_root and _marketing_root.is_dir():
                rel = path.lstrip("/")
                f = _safe_file(_marketing_root, rel)
                if f is not None:
                    return _file_response(f)
                if "." not in Path(rel).name:
                    f_html = _safe_file(_marketing_root, f"{rel}.html")
                    if f_html is not None:
                        return _file_response(f_html)

            return await call_next(request)

    # Order: last added runs first. UI static must run before strip+API routers.
    app.add_middleware(StripApiPrefixMiddleware)
    app.add_middleware(UiStaticMiddleware)

    # Mounts for asset directories (middleware also serves files; mounts help WSGI tools)
    if (_agents_dir / "assets").is_dir():
        app.mount(
            "/agents/assets",
            StaticFiles(directory=str(_agents_dir / "assets")),
            name="agents-assets",
        )
    if (_bay_dir / "assets").is_dir():
        app.mount(
            "/bay/assets",
            StaticFiles(directory=str(_bay_dir / "assets")),
            name="bay-assets",
        )
    _legacy_assets = _public / "assets"
    if _legacy_assets.is_dir() and not (_agents_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_legacy_assets)), name="assets")

except Exception as _exc:  # noqa: BLE001
    app = _build_error_app(_exc)
