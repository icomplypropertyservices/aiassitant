"""
Move skill *implementations* out of agent_skills.py into skills/handlers_all.py.

agent_skills keeps: catalog, enable/list helpers, HANDLER_TABLE, execute_skill, dispatch.
handlers_all keeps: all async def _skill_* (+ small parse helpers used only by them).

Bridge helpers avoid circular imports (catalog / premium charge).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "app" / "agent_skills.py"
PKG = ROOT / "backend" / "app" / "skills"


def main():
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # First implementation after execute_skill / run_skills_from_text
    past = False
    start = None
    for i, line in enumerate(lines):
        if line.startswith("async def execute_skill") or line.startswith("async def run_skills_from_text"):
            past = True
        if past and re.match(r"^(async )?def _skill_\w+\(", line):
            start = i
            break
    if start is None:
        raise SystemExit("handler start not found")

    # Include nearby private helpers immediately above first _skill_
    helper_start = start
    for j in range(start - 1, max(0, start - 100), -1):
        s = lines[j]
        if re.match(r"^(async )?def _\w+\(", s):
            helper_start = j
            continue
        if s.strip().startswith("#") or s.strip() == "":
            helper_start = j
            continue
        break
    # Prefer section banner if present
    for j in range(helper_start, max(0, helper_start - 30), -1):
        if "Individual skills" in lines[j] or lines[j].startswith("# ─"):
            helper_start = j
            break

    head = "".join(lines[:helper_start]).rstrip() + "\n"
    body = "".join(lines[helper_start:])

    # Rewrite body references to avoid circular imports at module load
    body = body.replace("from .", "from ..")  # relative packages one level up
    # Undo double-dot accidents for skills package internal (none yet)
    # Map same-module symbols to bridge
    body = re.sub(r"\b_charge_premium\b", "charge_premium", body)
    body = re.sub(r"\bSKILL_CATALOG\b", "get_skill_catalog()", body)
    # Fix get_skill_catalog()() double
    body = body.replace("get_skill_catalog()()", "get_skill_catalog()")
    body = re.sub(r"\benabled_skill_ids\b", "get_enabled_skill_ids", body)

    # enabled_skill_ids is a function - was enabled_skill_ids(agent, db)
    # get_enabled_skill_ids(agent, db) OK if bridge defines it that way

    PKG.mkdir(parents=True, exist_ok=True)
    (PKG / "__init__.py").write_text(
        '"""Skill implementation package. Catalog/dispatch remain in agent_skills."""\n',
        encoding="utf-8",
    )
    (PKG / "bridge.py").write_text(
        '''"""Late-bind helpers so handlers can use catalog without circular import."""
from __future__ import annotations


def get_skill_catalog():
    from ..agent_skills import SKILL_CATALOG
    return SKILL_CATALOG


def charge_premium(db, user, skill_meta, default_cost=0.02, text: str = "", *, already_billed: bool = False):
    from ..agent_skills import _charge_premium
    return _charge_premium(db, user, skill_meta, default_cost, text=text, already_billed=already_billed)


def get_enabled_skill_ids(agent, db):
    from ..agent_skills import enabled_skill_ids
    return enabled_skill_ids(agent, db)
''',
        encoding="utf-8",
    )

    header = '''"""All _skill_* implementations (split from agent_skills for maintainability)."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from .. import models
from ..agent_roles import is_orchestrator, normalize_role, role_matches_skill
from ..live_ops import emit_ops
from .. import channels
from ..usage_billing import charge_usage, charge_event, bill_skill_execution, bill_llm_turn
from ..permissions import can_execute, can_delegate, can_manage, normalize_permission
from .bridge import get_skill_catalog, charge_premium, get_enabled_skill_ids

'''

    handlers_path = PKG / "handlers_all.py"
    handlers_path.write_text(header + body, encoding="utf-8")

    # agent_skills: keep head + import handlers into globals
    tail = '''

# ── Load implementations from skills.handlers_all into this module ─────────
from .skills import handlers_all as _handlers_all  # noqa: E402

def _load_skill_handlers_into_globals() -> None:
    g = globals()
    for name, val in vars(_handlers_all).items():
        if name.startswith("_skill_") or name.startswith("_parse_") or name.startswith("_meeting_"):
            g[name] = val

_load_skill_handlers_into_globals()
'''
    SRC.write_text(head + tail, encoding="utf-8")

    print("agent_skills.py lines", head.count("\n") + tail.count("\n"))
    print("handlers_all.py lines", (header + body).count("\n"))
    print("handler start was line", helper_start + 1)


if __name__ == "__main__":
    main()
