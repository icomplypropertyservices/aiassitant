"""
After each human ↔ agent chat turn, ensure work continues autonomously.

- If the agent already started a goal/task via skills, we only attach a light
  follow-through note when useful.
- Otherwise we create a concrete self-assigned workflow task with DONE WHEN
  targets and kick it immediately so the agent keeps working without the human.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .task_status import initial_task_status

log = logging.getLogger("app.post_conversation")

# Small talk / pure Q&A that does not need a board workflow
_SKIP_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|great|bye|good\s*morning|"
    r"good\s*afternoon|good\s*evening|how are you|who are you|what can you do)\b",
    re.I,
)

_ACTION_RE = re.compile(
    r"\b(do|make|create|build|draft|send|call|email|fix|update|delete|add|"
    r"remove|schedule|book|research|plan|run|execute|complete|finish|follow\s*up|"
    r"chase|remind|prepare|write|summarise|summarize|analyse|analyze|list|"
    r"find|get|check|review|prepare|launch|set\s*up|setup|organise|organize|"
    r"need|want|please|can you|could you|should|must|todo|task|workflow)\b",
    re.I,
)

_SKILLS_THAT_MEAN_WORK = frozenset({
    "create_task", "execute_goal", "announce_plan", "claim_task",
    "create_customer", "create_deal", "open_meeting", "invite_to_meeting",
    "message_agent", "spawn_agent", "extract_meeting_tasks",
})


def _skill_started_work(skill_results: list[dict] | None) -> bool:
    for r in skill_results or []:
        if not r.get("ok"):
            continue
        sid = str(r.get("skill") or "")
        if sid in _SKILLS_THAT_MEAN_WORK:
            return True
        if r.get("task_id") or r.get("parent_task_id"):
            return True
    return False


def _looks_actionable(user_text: str, assistant_text: str = "") -> bool:
    u = (user_text or "").strip()
    if len(u) < 8:
        return False
    if _SKIP_RE.match(u) and len(u) < 48:
        return False
    if _ACTION_RE.search(u):
        return True
    # Longer substantive prompts usually imply work even without verbs
    if len(u) >= 60:
        return True
    # Agent promised next steps
    a = (assistant_text or "").lower()
    if any(x in a for x in ("i will", "i'll", "next i", "follow up", "working on", "create a task")):
        return True
    return False


def _compose_workflow_brief(
    *,
    agent: models.Agent,
    user_text: str,
    assistant_text: str,
    conversation_id: int | None,
) -> tuple[str, str]:
    """Return (title, description) for the post-chat workflow task."""
    head = (user_text or "").strip().split("\n")[0][:80] or "conversation follow-through"
    title = f"After chat · {head}"[:160]
    desc = f"""You just finished a live conversation with the human owner.

YOUR JOB NOW (autonomous — do not wait for them):
1) Orient: list_tasks mine=true, list_activity, read_workspace if needed.
2) Extract every commitment / open loop from the chat below.
3) Do the real work: drafts, CRM create/update, deals, meetings, research, message_agent teammates.
4) Create any extra child tasks with success_criteria if multi-step.
5) status_update or notify_human with a short progress note if material.
6) complete_task this task with evidence of what you delivered.

HUMAN SAID:
{(user_text or '')[:2500]}

YOU REPLIED:
{(assistant_text or '')[:2000]}

Conversation id: {conversation_id or 'n/a'}
Agent: {agent.name} (#{agent.id})

---
DONE WHEN: All action items from this chat are done or tracked as open board tasks with owners.
TARGET: At least one concrete deliverable (draft, CRM change, task, or clear status note) saved.
When finished, call complete_task with task_id and a result that proves the target.
"""
    return title, desc[:8000]


async def schedule_post_conversation_workflow(
    db: Session,
    user: models.User,
    agent: models.Agent,
    *,
    user_text: str,
    assistant_text: str,
    skill_results: list[dict] | None = None,
    conversation_id: int | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """
    Create + kick a self-run workflow after a chat turn when useful.
    Returns summary dict or None if skipped.
    """
    if not agent or not user:
        return None
    if (agent.status or "") != "active":
        return None

    if not force:
        if not _looks_actionable(user_text, assistant_text):
            return None
        # Already spinning up work from skills — still add a light monitor task only if multi-step goal missing
        if _skill_started_work(skill_results):
            # Memory breadcrumb so future autonomy knows context
            try:
                db.add(models.AgentMemory(
                    agent_id=agent.id,
                    user_id=user.id,
                    kind="conversation",
                    title=f"Chat note · {(user_text or '')[:60]}",
                    content=(
                        f"User: {(user_text or '')[:800]}\n\nYou: {(assistant_text or '')[:800]}"
                    )[:4000],
                    tags="post-chat,auto",
                ))
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            return {
                "ok": True,
                "skipped": True,
                "reason": "skills_already_started_work",
                "message": "Follow-through covered by skill actions",
            }

    # Dedupe: don't spam identical post-chat tasks in the last few minutes
    head = (user_text or "").strip()[:60]
    if head:
        recent = (
            db.query(models.Task)
            .filter(
                models.Task.user_id == user.id,
                models.Task.agent_id == agent.id,
                models.Task.labels.contains("post-chat"),
                models.Task.status.in_(("todo", "queued", "in_progress")),
            )
            .order_by(models.Task.id.desc())
            .limit(5)
            .all()
        )
        for t in recent:
            if head in (t.description or "") or head in (t.title or ""):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "duplicate_open_workflow",
                    "task_id": t.id,
                    "message": f"Workflow already open (#{t.id})",
                }

    title, description = _compose_workflow_brief(
        agent=agent,
        user_text=user_text,
        assistant_text=assistant_text,
        conversation_id=conversation_id,
    )
    status = initial_task_status(
        agent=agent,
        assignee_type="agent",
        run_now=True,
    )
    t = models.Task(
        user_id=user.id,
        agent_id=agent.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        title=title,
        description=description,
        status=status if status in ("queued", "todo") else "queued",
        priority="high",
        labels="post-chat,auto-workflow,self-assigned,self-run",
        assignee_type="agent",
    )
    db.add(t)
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id,
            type="workflow",
            message=f"Post-chat workflow queued: {title[:120]}",
        ))
        db.add(models.AgentMemory(
            agent_id=agent.id,
            user_id=user.id,
            kind="conversation",
            title=f"Chat · {title[:80]}",
            content=f"User: {(user_text or '')[:1200]}\n\nYou: {(assistant_text or '')[:1200]}"[:4000],
            tags="post-chat,auto",
        ))
    except Exception:
        pass
    db.commit()
    db.refresh(t)

    kicked = False
    if (t.status or "") == "queued":
        try:
            from .task_runner import kick_queued_task
            kicked = await kick_queued_task(
                t.id,
                user_id=user.id,
                agent_id=agent.id,
                description=t.description,
                agent_name=agent.name,
            )
        except Exception as e:
            log.warning("post-chat kick failed task=%s: %s", t.id, e)

    try:
        from .live_ops import emit_ops
        await emit_ops(
            user.id,
            kind="plan",
            status="running" if kicked else "queued",
            title=f"After chat · {agent.name}",
            detail=title[:200],
            agent_id=agent.id,
            task_id=t.id,
            db=db,
        )
    except Exception:
        pass

    try:
        from .ws import manager
        from .agent_serialize import task_dict
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_updated", "task": task_dict(t, db)},
        )
        await manager.broadcast(
            f"agents:{user.id}",
            {
                "event": "post_chat_workflow",
                "task_id": t.id,
                "agent_id": agent.id,
                "run_started": kicked,
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "task_id": t.id,
        "status": t.status,
        "run_started": kicked,
        "title": title,
        "message": (
            f"Post-chat workflow #{t.id} "
            + ("started — agent continues on its own" if kicked else "queued")
        ),
    }
