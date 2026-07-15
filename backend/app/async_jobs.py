"""Schedule background work — await on serverless (Vercel), fire-and-forget locally."""
from __future__ import annotations

import asyncio
import os


def is_serverless() -> bool:
    return bool(
        os.getenv("VERCEL")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or os.getenv("VERCEL_ENV")
    )


async def schedule(coro) -> None:
    """
    Run an async job.
    On Vercel/Lambda the request ends when the handler returns, so we await
    agent tasks so LLM work finishes before the function freezes.
    Locally we fire-and-forget for snappy API responses.
    """
    if is_serverless():
        await coro
    else:
        asyncio.create_task(coro)
