"""Single owner of task terminal status after LLM + skills (task_runner path)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .acceptance import (
    evaluate_skill_evidence,
    task_requires_review,
    pack_acceptance,
    extract_checklist,
)

log = logging.getLogger("app.orchestration.finalize")

# Skills that intentionally close (or intentionally fail) a board task
_CLOSE_SKILLS = frozenset({
    "complete_task",
    "set_task_status",
    "respond_to_task",
    "review_task",
})

# Skills that persist business data (agent "can save data")
_PERSIST_SKILLS = frozenset({
    "save_memory", "save_training", "save_lesson", "save_pattern", "create_pattern",
    "create_customer", "update_customer", "create_deal", "update_deal", "move_deal",
    "create_product", "update_product", "write_product", "read_product",
    "list_products", "search_products", "set_product_offer", "archive_product",
    "log_customer_activity", "log_communication",
    "set_agent_custom_field", "set_agent_custom_fields", "set_agent_field",
    "create_task", "update_task", "draft_email", "send_email", "draft_sms", "send_sms",
    "status_update", "notify_human", "message_agent",
})


def apply_task_result(task: models.Task, output: str, *, append: bool = False) -> None:
    out = (output or "")[:12000]
    if append and (task.result or "").strip():
        task.result = f"{(task.result or '').rstrip()}\n\n---\n{out}"[:12000]
    else:
        task.result = out


def skill_closed_task(skill_results: list[dict] | None) -> bool:
    """True when a skill intentionally moved the task to a terminal/review state."""
    for r in skill_results or []:
        if not r.get("ok"):
            continue
        sid = str(r.get("skill") or "").lower()
        if sid in _CLOSE_SKILLS:
            return True
    return False


def skill_persisted_data(skill_results: list[dict] | None) -> bool:
    for r in skill_results or []:
        if not r.get("ok"):
            continue
        sid = str(r.get("skill") or "").lower()
        if sid in _PERSIST_SKILLS or sid.startswith("create_") or sid.startswith("update_"):
            return True
        if sid.startswith("save_") or sid.startswith("set_"):
            return True
    return False


async def finalize_task_after_run(
    db: Session,
    task: models.Task,
    *,
    agent: models.Agent | None,
    output: str,
    skill_results: list[dict] | None = None,
    force_status: str | None = None,
    require_close_skill: bool = True,
    more_turns_available: bool = False,
) -> dict[str, Any]:
    """
    Decide completed | review | failed | in_progress after a task runner cycle.

    Rules (in order):
      1. If skills already set review/failed/completed (complete_task etc.), keep it
      2. force_status if provided
      3. Without a close skill, keep in_progress (agent stays busy) unless force_status
      4. Active checklist evaluation from skill_results
      5. requires_review labels → review (unless agent is lead completing own work)
      6. Else completed + chain unlock
    """
    from ..agent_roles import is_lead_agent, is_orchestrator

    cur = (task.status or "").lower()
    closed = skill_closed_task(skill_results)
    evidence = evaluate_skill_evidence(task, skill_results)
    _store_check_results(task, evidence)

    # Skill path already decided terminal / review
    if cur in ("review", "failed", "completed") and force_status is None and closed:
        apply_task_result(task, output, append=True)
        if cur == "completed" and not task.completed_at:
            task.completed_at = datetime.utcnow()
            try:
                from ..task_chain import on_task_finished
                await on_task_finished(db, task, final_status="completed", commit=False)
            except Exception as e:
                log.warning("on_task_finished skill-completed path: %s", e)
        return {
            "status": cur,
            "reason": "skill_locked",
            "evidence": evidence,
            "chain": cur in ("completed", "failed"),
            "persisted": skill_persisted_data(skill_results),
        }

    # Agent still working — do NOT auto-complete after a chatty reply
    if require_close_skill and force_status is None and not closed:
        if more_turns_available:
            task.status = "in_progress"
            task.completed_at = None
            apply_task_result(task, output, append=True)
            task.updated_at = datetime.utcnow()
            return {
                "status": "in_progress",
                "reason": "continue_working",
                "evidence": evidence,
                "chain": False,
                "persisted": skill_persisted_data(skill_results),
            }
        # Out of turns: stay busy (in_progress) so autonomy/stuck logic can re-kick
        # or human sees incomplete work — never fake "completed" without complete_task
        note = (
            "\n\n[STILL IN PROGRESS] Agent did not call complete_task yet. "
            "Data skills may have saved; task remains open until finished."
        )
        task.status = "in_progress"
        task.completed_at = None
        apply_task_result(task, (output or "") + note, append=False)
        task.updated_at = datetime.utcnow()
        return {
            "status": "in_progress",
            "reason": "awaiting_complete_task",
            "evidence": evidence,
            "chain": False,
            "persisted": skill_persisted_data(skill_results),
        }

    is_lead = bool(
        agent
        and (
            is_orchestrator(agent)
            or is_lead_agent(agent)
            or (agent.hierarchy_role or "") in ("lead", "orchestrator")
            or (agent.permission_level or "") in ("lead", "admin")
        )
    )

    verdict = (force_status or evidence.get("verdict") or "pass").lower()
    if force_status in ("completed", "failed", "review", "in_progress"):
        verdict = force_status

    if verdict == "in_progress":
        task.status = "in_progress"
        task.completed_at = None
        apply_task_result(task, output, append=True)
        return {
            "status": "in_progress",
            "reason": "forced_in_progress",
            "evidence": evidence,
            "chain": False,
            "persisted": skill_persisted_data(skill_results),
        }

    if verdict == "fail" and evidence.get("failed"):
        # Soft-fail → review with failed checks (lead can reject or accept)
        # Hard fail only if all skills failed and no deliverable
        if not (output or "").strip() and not evidence.get("skills_ok"):
            task.status = "failed"
            apply_task_result(task, output or "Failed active checks; no deliverable.")
            task.completed_at = datetime.utcnow()
            try:
                from ..task_chain import on_task_finished
                await on_task_finished(db, task, final_status="failed", commit=False)
            except Exception as e:
                log.warning("on_task_finished fail path: %s", e)
            return {"status": "failed", "reason": "active_check_fail", "evidence": evidence, "chain": True}

        task.status = "review"
        apply_task_result(
            task,
            (output or "")
            + "\n\n[ACTIVE CHECK] Failed items: "
            + ", ".join(evidence.get("failed") or [])
            + " — awaiting lead review_task.",
            append=False,
        )
        return {"status": "review", "reason": "active_check_partial_fail", "evidence": evidence, "chain": False}

    if verdict == "review" or (task_requires_review(task) and not is_lead and closed):
        task.status = "review"
        apply_task_result(
            task,
            (output or "")
            + "\n\n[Submitted for lead review — checklist / needs-review. "
            "Lead: review_task approve or reject.]",
            append=False,
        )
        # Notify parent lead lightly
        try:
            if agent and agent.parent_id:
                db.add(models.ActivityLog(
                    agent_id=agent.parent_id,
                    type="review_needed",
                    message=f"Task #{task.id} “{(task.title or '')[:80]}” ready for review",
                ))
        except Exception:
            pass
        return {"status": "review", "reason": "requires_review", "evidence": evidence, "chain": False}

    # Pass → completed (only when close skill ran or force_status=completed)
    task.status = "completed"
    apply_task_result(task, output)
    task.completed_at = datetime.utcnow()
    try:
        from ..task_chain import on_task_finished
        await on_task_finished(db, task, final_status="completed", commit=False)
    except Exception as e:
        log.warning("on_task_finished complete path: %s", e)
    return {
        "status": "completed",
        "reason": "pass",
        "evidence": evidence,
        "chain": True,
        "persisted": skill_persisted_data(skill_results),
    }


def _store_check_results(task: models.Task, evidence: dict[str, Any]) -> None:
    """Write check statuses into acceptance_json when column exists."""
    try:
        checks = evidence.get("checks") or []
        if not checks and not extract_checklist(task):
            return
        payload = pack_acceptance(
            done_when="",
            checklist=[c.get("label") for c in checks if isinstance(c, dict)],
            require_review=task_requires_review(task),
        )
        data = __import__("json").loads(payload)
        data["checks"] = checks
        data["last_verdict"] = evidence.get("verdict")
        data["skills_ok"] = evidence.get("skills_ok") or []
        data["skills_fail"] = evidence.get("skills_fail") or []
        blob = __import__("json").dumps(data, ensure_ascii=False)
        if hasattr(task, "acceptance_json"):
            task.acceptance_json = blob
    except Exception:
        pass
