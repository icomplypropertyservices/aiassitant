"""Simple in-memory rate limiter for auth endpoints (production-safe defaults)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# key -> deque of timestamps
_hits: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(
    key: str,
    *,
    limit: int = 20,
    window_sec: int = 60,
) -> None:
    """Raise 429 if key exceeds `limit` hits within `window_sec`."""
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window_sec:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(
            429,
            f"Too many attempts. Try again in {int(window_sec - (now - q[0])) + 1}s.",
        )
    q.append(now)


def client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"
