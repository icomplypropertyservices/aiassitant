"""Unified multi-agent workflow start (create_workflow / run_pattern / presets)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..patterns import (
    normalize_checklist,
    format_checklist_block,
    save_pattern,
    get_pattern,
)
from ..task_chain import pick_assignee, start_goal_chain
from ..agent_roles import is_lead_agent, is_orchestrator
from .acceptance import (
    embed_acceptance,
    pack_acceptance,
    merge_labels,
)

log = logging.getLogger("app.orchestration.workflow_run")


def _compose_step_description(
    sdesc: str,
    *,
    title: str,
    done_when: str,
    checklist: list[str],
    owner_name: str,
    require_review: bool,
) -> str:
    from ..patterns import format_checklist_block as fcb

    body = (sdesc or title or "Step").strip()
    lines = [
        body,
        "",
        "---",
        "ACCEPTANCE (must satisfy to complete):",
        f"DONE WHEN: {done_when or f'Complete: {title}'}",
        f"TARGET: {done_when or title}",
    ]
    if checklist:
        lines.append(fcb(checklist))
        lines.append("Lead will verify every checklist item.")
    if owner_name:
        lines.append(f"Assigned by: {owner_name}")
    lines.append(
        "When finished, complete_task with evidence for each checklist item. "
        "If rejected with WHAT'S WRONG, fix and re-complete."
    )
    acc = pack_acceptance(
        done_when=done_when,
        checklist=checklist,
        require_review=require_review or bool(checklist),
    )
    return embed_acceptance("\n".join(lines), acc)


async def start_workflow(
    db: Session,
    user: models.User,
    owner: models.Agent,
    *,
    title: str,
    description: str = "",
    steps: list[Any],
    checklist: list[str] | None = None,
    priority: str = "high",
    company_id: int | None = None,
    project_id: int | None = None,
    require_review: bool = True,
    save_as_pattern: bool = False,
    pattern_name: str = "",
    category: str = "custom",
) -> dict[str, Any]:
    """
    Create sequential multi-agent workflow with atomic labels + acceptance.
    """
    if not steps:
        return {"ok": False, "error": "steps required"}

    parent_checklist = normalize_checklist(checklist)
    goal_text = (description or title).strip()
    if parent_checklist:
        goal_text = (
            f"{goal_text}\n\n"
            f"{format_checklist_block(parent_checklist, heading='WORKFLOW CHECKLIST (lead verifies)')}"
        )

    chain_steps: list[dict[str, Any]] = []
    for i, s in enumerate(list(steps)[:12]):
        if isinstance(s, str):
            stitle, sdesc = s[:120], s
            role_hint, pref_id = None, None
            checks = []
            done_when = f"Complete: {s[:160]}"
        elif isinstance(s, dict):
            stitle = str(s.get("title") or s.get("description") or f"Step {i + 1}")[:120]
            sdesc = str(s.get("description") or s.get("text") or stitle)
            role_hint = s.get("role_hint") or s.get("role") or s.get("template_type")
            pref_id = s.get("agent_id")
            checks = normalize_checklist(
                s.get("checklist") or s.get("checks") or s.get("must_check") or s.get("verify")
            )
            done_when = str(
                s.get("done_when") or s.get("success_criteria") or s.get("target")
                or f"Complete: {stitle}"
            )
        else:
            continue

        pref_agent_id = None
        try:
            if pref_id not in (None, ""):
                pref_agent_id = int(pref_id)
        except (TypeError, ValueError):
            pref_agent_id = None

        assignee = pick_assignee(
            db, user,
            owner=owner,
            step_index=i,
            step_text=f"{stitle} {sdesc}",
            preferred_agent_id=pref_agent_id,
            preferred_role=str(role_hint).strip() if role_hint else None,
        )
        step_require = require_review or bool(checks)
        brief = _compose_step_description(
            sdesc,
            title=stitle,
            done_when=done_when,
            checklist=checks,
            owner_name=owner.name or "",
            require_review=step_require,
        )
        extra_labels = ["lead-workflow", "auto-chain"]
        if step_require:
            extra_labels.extend(["needs-review", "lead-assigned", "requires-review"])
        if checks:
            extra_labels.append("has-checklist")

        chain_steps.append({
            "title": stitle,
            "description": brief,
            "done_when": done_when,
            "role_hint": role_hint,
            "agent_id": pref_agent_id or assignee.id,
            "checklist": checks,
            "labels": merge_labels(*extra_labels),
            "require_review": step_require,
            "acceptance_json": pack_acceptance(
                done_when=done_when,
                checklist=checks,
                require_review=step_require,
            ),
        })

    if not chain_steps:
        return {"ok": False, "error": "no valid steps"}

    result = await start_goal_chain(
        db,
        user,
        owner,
        goal_text,
        title=title[:160],
        company_id=company_id or owner.company_id,
        project_id=project_id or owner.project_id,
        priority=priority or "high",
        steps=chain_steps,
        max_steps=len(chain_steps),
        auto_queue=True,
        child_label_prefix="lead-workflow",
        require_review_default=require_review,
    )

    pattern_out = None
    if save_as_pattern or pattern_name:
        pattern_out = save_pattern(
            db, user, owner,
            name=str(pattern_name or title),
            description=goal_text[:2000],
            steps=[
                {
                    "title": s["title"],
                    "description": s.get("description") or s["title"],
                    "done_when": s.get("done_when"),
                    "checklist": s.get("checklist") or [],
                    "role_hint": s.get("role_hint"),
                    "agent_id": s.get("agent_id"),
                }
                for s in chain_steps
            ],
            checklist=parent_checklist,
            category=category or "custom",
            tags="lead-workflow",
        )

    try:
        db.add(models.ActivityLog(
            agent_id=owner.id,
            type="workflow",
            message=f"Created workflow “{title}” with {len(chain_steps)} steps",
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    out = {
        "ok": True,
        "message": (
            f"Workflow “{title}” created with {len(chain_steps)} steps. "
            f"Each step has DONE WHEN + checklist; lead uses review_task if wrong."
        ),
        "workflow": result,
        "parent_task_id": result.get("parent_task_id") if isinstance(result, dict) else None,
        "children": result.get("children") if isinstance(result, dict) else [],
        "checklist": parent_checklist or None,
        "lead_can_review": is_orchestrator(owner) or is_lead_agent(owner),
    }
    if pattern_out:
        out["pattern"] = pattern_out
    return out


async def run_pattern(
    db: Session,
    user: models.User,
    owner: models.Agent,
    pattern_id: Any,
    *,
    title: str = "",
    priority: str = "high",
    company_id: int | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    got = get_pattern(db, user, pattern_id)
    if not got.get("ok"):
        return got
    pat = got["pattern"]
    steps = pat.get("steps") or []
    if not steps:
        return {"ok": False, "error": "pattern has no steps"}
    return await start_workflow(
        db, user, owner,
        title=title or pat.get("name") or "Pattern run",
        description=pat.get("description") or "",
        steps=steps,
        checklist=pat.get("checklist"),
        priority=priority or "high",
        company_id=company_id,
        project_id=project_id,
        require_review=True,
        save_as_pattern=False,
    )
