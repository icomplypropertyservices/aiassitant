"""
Mega skill packs: 20 domain packs × 50 skills = 1000 catalog entries.

Loaded from pack_*.json next to this module (and optional MEGA_CATALOG.json).
Handlers default to catalog_deliverable (see agent_skills._skill_catalog_deliverable).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
_CACHE: list[dict[str, Any]] | None = None


def load_mega_skills(*, force: bool = False) -> list[dict[str, Any]]:
    """Load all skill pack JSON files and return a flat skill list."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    skills: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Prefer individual packs (easier for subagents to edit one domain)
    pack_files = sorted(_DIR.glob("[0-9][0-9]_*.json"))
    if not pack_files:
        mega = _DIR / "MEGA_CATALOG.json"
        if mega.exists():
            data = json.loads(mega.read_text(encoding="utf-8"))
            pack_skills = data.get("skills") or []
            if isinstance(pack_skills, list):
                for s in pack_skills:
                    if isinstance(s, dict) and s.get("id") and s["id"] not in seen:
                        seen.add(s["id"])
                        skills.append(s)
                _CACHE = skills
                return skills

    for path in pack_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pack_id = data.get("pack") or path.stem
        category = data.get("category")
        for s in data.get("skills") or []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            sid = str(s["id"])
            if sid in seen:
                continue
            seen.add(sid)
            entry = dict(s)
            entry.setdefault("pack", pack_id)
            if category and not entry.get("category"):
                entry["category"] = category
            entry.setdefault("handler", "catalog_deliverable")
            # Normalize roles
            roles = entry.get("roles") or ["orchestrator", "lead", "member", "specialist"]
            entry["roles"] = list(roles)
            entry.setdefault("args", ["context", "goal", "audience", "constraints"])
            skills.append(entry)

    _CACHE = skills
    return skills


def mega_skill_count() -> int:
    return len(load_mega_skills())


def mega_packs_summary() -> list[dict[str, Any]]:
    packs: dict[str, int] = {}
    cats: dict[str, str] = {}
    for s in load_mega_skills():
        p = s.get("pack") or "unknown"
        packs[p] = packs.get(p, 0) + 1
        if s.get("category"):
            cats[p] = s["category"]
    return [
        {"pack": p, "count": packs[p], "category": cats.get(p)}
        for p in sorted(packs.keys())
    ]
