"""
Vercel Python serverless entry for the FastAPI app.

All API routes (auth, agents, billing, …) are served from this single ASGI app.
The Vite SPA is served as static files; vercel.json rewrites API paths here.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Put backend/ on sys.path so `import app` works on Vercel
_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.main import app  # noqa: E402  — FastAPI instance exported for Vercel
