"""Schedule background work — await on serverless (Vercel), fire-and-forget locally."""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("app.async_jobs")


def is_serverless() -> bool:
    return bool(
        os.getenv("VERCEL")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or os.getenv("VERCEL_ENV")
    )


async def schedule(coro, *, timeout_sec: float | None = None) -> None:
    """
    Run an async job.

    Locally: fire-and-forget (snappy API).
    On Vercel/Lambda: the process freezes when the HTTP handler returns, so we
    must await — but with a hard budget so chat/API never waits on multi-turn
    agent tasks (that was freezing agent replies past the client timeout).

    timeout_sec:
      None → default 20s on serverless, unlimited local background task
      0    → fire-and-forget even on serverless (job may be truncated; prefer queue)
      >0   → wait up to that many seconds then abandon remaining work
    """
    if not is_serverless():
        asyncio.create_task(coro)
        return

    # Serverless
    if timeout_sec == 0:
        # Caller explicitly chose not to block (work should already be persisted as queued)
        try:
            asyncio.create_task(coro)
        except Exception:
            pass
        return

    budget = 20.0 if timeout_sec is None else max(1.0, float(timeout_sec))
    try:
        await asyncio.wait_for(coro, timeout=budget)
    except asyncio.TimeoutError:
        log.warning("schedule: serverless job hit %.0fs budget — continuing without await", budget)
    except Exception as e:
        log.warning("schedule: job failed: %s", e)
