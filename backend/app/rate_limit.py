"""Rate limiter for auth endpoints (production-safe defaults).

When ``REDIS_URL`` or ``UPSTASH_REDIS_URL`` is set, counters use Redis
``INCR`` + ``EXPIRE`` so limits are shared across instances (Vercel,
multi-worker). If Redis is unset, import fails, or a call errors, falls
back to per-process in-memory deques (not shared across instances).
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# key -> deque of timestamps (per-process only; used when Redis unavailable)
_hits: dict[str, deque[float]] = defaultdict(deque)

_redis_client: Any | None = None
_redis_checked: bool = False
_redis_failed: bool = False


def _redis_url() -> str | None:
    return (
        os.getenv("REDIS_URL")
        or os.getenv("UPSTASH_REDIS_URL")
        or None
    )


def _get_redis() -> Any | None:
    """Lazy-connect Redis; cache client or permanent failure for this process."""
    global _redis_client, _redis_checked, _redis_failed
    if _redis_failed:
        return None
    if _redis_client is not None:
        return _redis_client
    if _redis_checked and _redis_client is None:
        return None

    url = _redis_url()
    if not url:
        _redis_checked = True
        return None

    try:
        import redis  # type: ignore

        client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        _redis_client = client
        _redis_checked = True
        logger.info("rate_limit: using Redis backend")
        return _redis_client
    except Exception as e:
        _redis_checked = True
        _redis_failed = True
        logger.warning("rate_limit: Redis unavailable, using in-memory: %s", e)
        return None


def _check_rate_limit_redis(
    client: Any,
    key: str,
    *,
    limit: int,
    window_sec: int,
) -> None:
    rkey = f"rl:{key}"
    # INCR then set EXPIRE only on first hit in the window
    count = int(client.incr(rkey))
    if count == 1:
        client.expire(rkey, window_sec)
    if count > limit:
        ttl = client.ttl(rkey)
        retry = int(ttl) if ttl and ttl > 0 else window_sec
        raise HTTPException(
            429,
            f"Too many attempts. Try again in {retry}s.",
        )


def _check_rate_limit_memory(
    key: str,
    *,
    limit: int,
    window_sec: int,
) -> None:
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


def check_rate_limit(
    key: str,
    *,
    limit: int = 20,
    window_sec: int = 60,
) -> None:
    """Raise 429 if key exceeds `limit` hits within `window_sec`."""
    client = _get_redis()
    if client is not None:
        try:
            _check_rate_limit_redis(client, key, limit=limit, window_sec=window_sec)
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("rate_limit: Redis error, falling back to memory: %s", e)
            # one bad call: keep trying redis later unless connect was hard-failed
    _check_rate_limit_memory(key, limit=limit, window_sec=window_sec)


def client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"
