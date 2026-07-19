"""Shared task workflow statuses for agents + org task APIs."""

from __future__ import annotations

from typing import Any

ALLOWED = frozenset({"todo", "queued", "in_progress", "review", "completed", "failed"})


def initial_task_status(
    *,
    agent: Any | None = None,
    human_id: int | None = None,
    assignee_type: str | None = None,
    run_now: bool = True,
) -> str:
    """Pick create-time status so autonomy can pick up work.

    Rules:
    - human assignee → ``todo`` (humans are not autonomy-driven)
    - ``run_now=False`` → ``todo`` (explicit opt-out of the queue)
    - agent assigned and ``status == "active"`` and run_now → ``queued``
    - otherwise → ``todo`` (paused / missing / unassigned)
    """
    at = (assignee_type or "").strip().lower()
    if human_id is not None or at == "human":
        return "todo"
    if not run_now:
        return "todo"
    if agent is not None and getattr(agent, "status", None) == "active":
        return "queued"
    return "todo"


def normalize_status(status: str | None, *, default: str | None = None) -> str:
    """Return a canonical status or raise ValueError if invalid.

    If status is None/empty and default is provided, returns default.
    """
    if status is None or (isinstance(status, str) and not status.strip()):
        if default is not None:
            if default not in ALLOWED:
                raise ValueError(f"Status must be one of {sorted(ALLOWED)}")
            return default
        raise ValueError(f"Status must be one of {sorted(ALLOWED)}")
    s = status.strip().lower().replace("-", "_").replace(" ", "_")
    # common aliases
    aliases = {
        "done": "completed",
        "complete": "completed",
        "inprogress": "in_progress",
        "in_progress": "in_progress",
        "doing": "in_progress",
        "pending": "todo",
        "open": "todo",
        "to_do": "todo",
        "error": "failed",
        "fail": "failed",
    }
    s = aliases.get(s, s)
    if s not in ALLOWED:
        raise ValueError(f"Status must be one of {sorted(ALLOWED)}")
    return s
