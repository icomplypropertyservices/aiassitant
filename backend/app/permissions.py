"""Shared permission levels + escalation policy for agents and humans."""
from __future__ import annotations

PERMISSION_LEVELS = [
    {
        "id": "viewer",
        "label": "Viewer",
        "rank": 10,
        "description": "Read-only visibility; cannot execute or change work.",
        "can_execute": False,
        "can_delegate": False,
        "can_manage": False,
        "can_admin": False,
    },
    {
        "id": "operator",
        "label": "Operator",
        "rank": 30,
        "description": "Execute assigned work, use linked apps, save data.",
        "can_execute": True,
        "can_delegate": False,
        "can_manage": False,
        "can_admin": False,
    },
    {
        "id": "lead",
        "label": "Lead",
        "rank": 60,
        "description": "Delegate, escalate, spawn helpers, assign humans.",
        "can_execute": True,
        "can_delegate": True,
        "can_manage": True,
        "can_admin": False,
    },
    {
        "id": "admin",
        "label": "Admin",
        "rank": 100,
        "description": "Full control within the workspace (pipelines, team, autonomy).",
        "can_execute": True,
        "can_delegate": True,
        "can_manage": True,
        "can_admin": True,
    },
]

ESCALATE_WHEN = [
    {"id": "never", "label": "Never auto-escalate", "description": "Only escalate when explicitly asked."},
    {"id": "on_failure", "label": "On failure", "description": "When a task fails or errors."},
    {"id": "on_blocked", "label": "When blocked", "description": "Missing info, apps, or permissions."},
    {"id": "high_priority", "label": "High / urgent priority", "description": "Escalate high and urgent work for review."},
    {"id": "sla_breach", "label": "SLA / stuck too long", "description": "Task stuck in progress past the workspace limit."},
    {"id": "customer_vip", "label": "VIP / tagged customers", "description": "Work involving VIP or priority customers."},
    {"id": "value_threshold", "label": "High deal value", "description": "Deals or tasks above value threshold."},
    {"id": "always_review", "label": "Always review", "description": "Every completed deliverable escalates for sign-off."},
    {"id": "custom", "label": "Custom rule", "description": "Use the free-text escalate reason as the rule."},
]

ESCALATE_TO = [
    {"id": "parent", "label": "Reporting lead / parent agent"},
    {"id": "orchestrator", "label": "Main orchestrator"},
    {"id": "human", "label": "Assigned human (or escalate_human)"},
    {"id": "owner", "label": "Workspace owner (subscriber)"},
]

_LEVEL_BY_ID = {p["id"]: p for p in PERMISSION_LEVELS}
_WHEN_BY_ID = {e["id"]: e for e in ESCALATE_WHEN}


def normalize_permission(level: str | None) -> str:
    lid = (level or "operator").strip().lower()
    if lid in ("member", "execute", "user"):
        return "operator"
    if lid in ("manager", "lead_perm"):
        return "lead"
    if lid in _LEVEL_BY_ID:
        return lid
    return "operator"


def normalize_escalate_when(when: str | None) -> str:
    w = (when or "on_failure").strip().lower()
    return w if w in _WHEN_BY_ID else "on_failure"


def normalize_escalate_to(to: str | None) -> str:
    t = (to or "parent").strip().lower()
    return t if t in {x["id"] for x in ESCALATE_TO} else "parent"


def level_meta(level: str | None) -> dict:
    return _LEVEL_BY_ID.get(normalize_permission(level), _LEVEL_BY_ID["operator"])


def can_execute(level: str | None) -> bool:
    return bool(level_meta(level).get("can_execute"))


def can_delegate(level: str | None) -> bool:
    return bool(level_meta(level).get("can_delegate"))


def can_manage(level: str | None) -> bool:
    return bool(level_meta(level).get("can_manage"))


def can_admin(level: str | None) -> bool:
    return bool(level_meta(level).get("can_admin"))


def catalog() -> dict:
    return {
        "permission_levels": PERMISSION_LEVELS,
        "escalate_when": ESCALATE_WHEN,
        "escalate_to": ESCALATE_TO,
    }
