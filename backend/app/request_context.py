"""Per-request flags (contextvars) so chat never awaits multi-turn task runners."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

# When True, kick_queued_task leaves work queued (no inline LLM multi-turn).
_defer_task_runs: ContextVar[bool] = ContextVar("defer_task_runs", default=False)


def defer_task_runs() -> bool:
    return bool(_defer_task_runs.get())


@contextmanager
def chat_request_scope() -> Iterator[None]:
    """Mark this call stack as an interactive chat reply (must stay fast)."""
    token = _defer_task_runs.set(True)
    try:
        yield
    finally:
        _defer_task_runs.reset(token)
