"""
Reusable work patterns created by agents (especially leads).

A pattern is a named multi-step recipe: who does what, DONE WHEN targets,
and a checklist of what must be verified before accepting work.

Stored as AgentMemory (kind=workflow_pattern) so no DB migration is required.
"""
from __future__ import annotations

import json
import re
import logging
from typing import Any

from sqlalchemy.orm import Session

from . import models

log = logging.getLogger("app.patterns")

PATTERN_KIND = "workflow_pattern"
PATTERN_TAG = "workflow-pattern"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "pattern")[:80]


def normalize_checklist(raw: Any) -> list[str]:
    """Accept list, newline string, or comma string → clean checklist lines."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[\n;]+", raw)
        if len(parts) == 1 and "," in raw and "\n" not in raw:
            parts = [p.strip() for p in raw.split(",")]
        items = [p.strip(" -•*\t") for p in parts if p and p.strip()]
        return [i for i in items if len(i) >= 2][:40]
    if isinstance(raw, (list, tuple)):
        out = []
        for x in raw:
            if isinstance(x, dict):
                t = x.get("text") or x.get("item") or x.get("check") or x.get("title") or ""
                t = str(t).strip()
            else:
                t = str(x).strip()
            if t:
                out.append(t[:300])
        return out[:40]
    return []


def format_checklist_block(items: list[str], *, heading: str = "CHECKLIST (verify before complete)") -> str:
    if not items:
        return ""
    lines = [f"---", heading + ":", *[f"  [ ] {c}" for c in items]]
    return "\n".join(lines)


def format_feedback_block(
    feedback: str,
    *,
    checks_failed: list[str] | None = None,
    reviewer: str = "",
) -> str:
    lines = [
        "",
        "=== WHAT'S WRONG (lead feedback — fix then re-complete) ===",
    ]
    if reviewer:
        lines.append(f"Reviewed by: {reviewer}")
    lines.append((feedback or "Work does not meet acceptance criteria.").strip()[:2000])
    failed = normalize_checklist(checks_failed)
    if failed:
        lines.append("Failed checks:")
        for c in failed:
            lines.append(f"  [x] {c}")
    lines.append("Re-do the work to satisfy DONE WHEN + CHECKLIST, then complete_task again.")
    lines.append("===")
    return "\n".join(lines)


def pattern_payload(
    *,
    name: str,
    description: str = "",
    steps: list[dict[str, Any]] | None = None,
    checklist: list[str] | None = None,
    category: str = "general",
    tags: str = "",
) -> dict[str, Any]:
    norm_steps: list[dict[str, Any]] = []
    for i, s in enumerate(steps or []):
        if isinstance(s, str):
            norm_steps.append({
                "title": s[:120],
                "description": s,
                "checklist": [],
                "role_hint": None,
            })
            continue
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or s.get("description") or s.get("step") or f"Step {i + 1}")[:120]
        desc = str(s.get("description") or s.get("text") or title)
        norm_steps.append({
            "title": title,
            "description": desc[:4000],
            "done_when": str(s.get("done_when") or s.get("success_criteria") or s.get("target") or "")[:500],
            "checklist": normalize_checklist(
                s.get("checklist") or s.get("checks") or s.get("must_check") or s.get("verify")
            ),
            "role_hint": s.get("role_hint") or s.get("role") or s.get("template_type"),
            "agent_id": s.get("agent_id"),
            "priority": s.get("priority") or "medium",
        })
    return {
        "name": (name or "pattern")[:120],
        "slug": _slug(name),
        "description": (description or "")[:2000],
        "category": (category or "general")[:40],
        "tags": (tags or "")[:200],
        "checklist": normalize_checklist(checklist),
        "steps": norm_steps,
        "version": 1,
    }


def save_pattern(
    db: Session,
    user: models.User,
    agent: models.Agent,
    *,
    name: str,
    description: str = "",
    steps: list | None = None,
    checklist: list | str | None = None,
    category: str = "general",
    tags: str = "",
    pattern_id: int | None = None,
) -> dict[str, Any]:
    """Create or update a workspace pattern (AgentMemory row)."""
    payload = pattern_payload(
        name=name,
        description=description,
        steps=steps or [],
        checklist=normalize_checklist(checklist),
        category=category,
        tags=tags,
    )
    if not payload["steps"] and not payload["checklist"]:
        return {"ok": False, "error": "pattern needs steps and/or checklist"}

    tag_blob = f"{PATTERN_TAG},{payload['slug']},{payload['category']}"
    if tags:
        tag_blob = f"{tag_blob},{tags}"

    row = None
    if pattern_id:
        row = db.get(models.AgentMemory, int(pattern_id))
        if not row or row.user_id != user.id:
            return {"ok": False, "error": "pattern not found"}
    else:
        # Upsert by slug in workspace
        candidates = (
            db.query(models.AgentMemory)
            .filter_by(user_id=user.id, kind=PATTERN_KIND)
            .order_by(models.AgentMemory.id.desc())
            .limit(80)
            .all()
        )
        for m in candidates:
            try:
                data = json.loads(m.content or "{}")
            except Exception:
                continue
            if isinstance(data, dict) and data.get("slug") == payload["slug"]:
                row = m
                break

    content = json.dumps(payload, ensure_ascii=False)
    if row:
        row.title = payload["name"][:200]
        row.content = content
        row.tags = tag_blob[:300]
        row.agent_id = agent.id
        row.kind = PATTERN_KIND
        db.commit()
        db.refresh(row)
        return {
            "ok": True,
            "message": f"Pattern “{payload['name']}” updated (#{row.id})",
            "pattern_id": row.id,
            "pattern": payload,
            "updated": True,
        }

    row = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind=PATTERN_KIND,
        title=payload["name"][:200],
        content=content,
        tags=tag_blob[:300],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "message": f"Pattern “{payload['name']}” saved (#{row.id})",
        "pattern_id": row.id,
        "pattern": payload,
        "updated": False,
    }


def list_patterns(
    db: Session,
    user: models.User,
    *,
    q: str = "",
    category: str = "",
    limit: int = 40,
) -> dict[str, Any]:
    rows = (
        db.query(models.AgentMemory)
        .filter_by(user_id=user.id, kind=PATTERN_KIND)
        .order_by(models.AgentMemory.id.desc())
        .limit(120)
        .all()
    )
    q = (q or "").strip().lower()
    cat = (category or "").strip().lower()
    out = []
    for m in rows:
        try:
            data = json.loads(m.content or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        name = data.get("name") or m.title or f"pattern-{m.id}"
        desc = data.get("description") or ""
        steps = data.get("steps") or []
        if q and q not in name.lower() and q not in desc.lower() and q not in (m.tags or "").lower():
            continue
        if cat and (data.get("category") or "").lower() != cat:
            continue
        out.append({
            "id": m.id,
            "name": name,
            "slug": data.get("slug") or _slug(name),
            "description": desc[:400],
            "category": data.get("category") or "general",
            "tags": m.tags or data.get("tags") or "",
            "step_count": len(steps) if isinstance(steps, list) else 0,
            "checklist": data.get("checklist") or [],
            "steps_preview": [
                (s.get("title") if isinstance(s, dict) else str(s))[:80]
                for s in (steps[:6] if isinstance(steps, list) else [])
            ],
            "created_by_agent_id": m.agent_id,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        })
        if len(out) >= limit:
            break
    return {"ok": True, "count": len(out), "patterns": out}


def get_pattern(db: Session, user: models.User, pattern_id: int | str) -> dict[str, Any]:
    row = None
    try:
        pid = int(pattern_id)
        row = db.get(models.AgentMemory, pid)
    except (TypeError, ValueError):
        pid = None
    if row and row.user_id == user.id and row.kind == PATTERN_KIND:
        pass
    else:
        # lookup by slug/name
        slug = _slug(str(pattern_id))
        rows = (
            db.query(models.AgentMemory)
            .filter_by(user_id=user.id, kind=PATTERN_KIND)
            .order_by(models.AgentMemory.id.desc())
            .limit(80)
            .all()
        )
        row = None
        for m in rows:
            try:
                data = json.loads(m.content or "{}")
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("slug") == slug or (data.get("name") or "").lower() == str(pattern_id).lower():
                row = m
                break
    if not row or row.user_id != user.id or row.kind != PATTERN_KIND:
        return {"ok": False, "error": "pattern not found"}
    try:
        data = json.loads(row.content or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["id"] = row.id
    data["created_by_agent_id"] = row.agent_id
    return {"ok": True, "pattern": data, "pattern_id": row.id}


def delete_pattern(db: Session, user: models.User, pattern_id: int) -> dict[str, Any]:
    row = db.get(models.AgentMemory, int(pattern_id))
    if not row or row.user_id != user.id or row.kind != PATTERN_KIND:
        return {"ok": False, "error": "pattern not found"}
    name = row.title
    db.delete(row)
    db.commit()
    return {"ok": True, "message": f"Pattern “{name}” deleted", "pattern_id": pattern_id}
