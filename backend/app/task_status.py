"""Shared task workflow statuses for agents + org task APIs."""

ALLOWED = frozenset({"todo", "queued", "in_progress", "review", "completed", "failed"})


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
