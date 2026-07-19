"""
Autonomous task runner — single place for: load agent → LLM → skills → bill → complete.

Extracted from routers/agents.py so HTTP stays thin and the flow is one unit of work.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from . import models, channels
from .database import SessionLocal
from .agent_scaffold import map_model, resolve_runtime, repair_agent
from .agent_skills import run_skills_from_text
from .agent_prompts import build_task_prompt
from .llm import complete
from .pricing import estimate_tokens
from .usage_billing import charge_usage
from .user_keys import credentials_for_user
from .ws import manager

log = logging.getLogger("app.task_runner")


async def kick_queued_task(
    task_id: int,
    *,
    user_id: int | None = None,
    agent_id: int | None = None,
    description: str | None = None,
    agent_name: str | None = None,
) -> bool:
    """Schedule immediate execution for a queued task (do not wait for daily cron).

    Returns True if a run was scheduled. Safe to call after create_task / claim /
    goal-chain step unlock. No-ops if task missing, not queued, or agent paused.
    """
    from .async_jobs import schedule

    db = SessionLocal()
    try:
        t = db.get(models.Task, task_id)
        if not t:
            return False
        if (t.status or "") != "queued":
            return False
        aid = agent_id or t.agent_id
        if not aid:
            return False
        a = db.get(models.Agent, aid)
        if not a or (a.status or "") != "active":
            return False
        uid = user_id or t.user_id
        desc = description if description is not None else (t.description or t.title or "")
        name = agent_name or a.name or "Agent"
        # Claim the row immediately so a second kick cannot double-run
        t.status = "in_progress"
        t.updated_at = datetime.utcnow()
        db.commit()
        # Capture scalars before session close
        tid, a_id, u_id = t.id, a.id, uid
        aname, tdesc = name, desc
    except Exception as e:
        log.warning("kick_queued_task claim failed task=%s: %s", task_id, e)
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        db.close()

    try:
        await schedule(run_agent_task(a_id, u_id, tid, tdesc, aname))
        log.info("kicked task_id=%s agent_id=%s", tid, a_id)
        return True
    except Exception as e:
        log.warning("kick_queued_task schedule failed task=%s: %s", task_id, e)
        # Re-queue so autonomy can retry
        db2 = SessionLocal()
        try:
            t2 = db2.get(models.Task, tid)
            if t2 and (t2.status or "") == "in_progress" and not (t2.result or "").strip():
                t2.status = "queued"
                db2.commit()
        except Exception:
            try:
                db2.rollback()
            except Exception:
                pass
        finally:
            db2.close()
        return False


def mode_for_template(template_type: str | None) -> str:
    t = (template_type or "").lower()
    if t in ("coding", "developer", "engineer", "qa"):
        return "coding"
    if t in ("sales", "outreach", "lead"):
        return "sales"
    if t in ("support", "customer"):
        return "support"
    return "general"


async def log_activity(agent_id: int, user_id: int, kind: str, detail: str):
    """Persist agent activity. Model columns are type/message (not kind/detail)."""
    db = SessionLocal()
    try:
        db.add(models.ActivityLog(
            agent_id=agent_id,
            type=kind or "info",
            message=(detail or "")[:2000],
        ))
        db.commit()
        try:
            await manager.broadcast(
                f"agents:{user_id}",
                {
                    "event": "activity",
                    "agent_id": agent_id,
                    "entry": {
                        "type": kind or "info",
                        "message": (detail or "")[:500],
                    },
                },
            )
        except Exception:
            pass
    except Exception as e:
        log.warning("log_activity failed: %s", e)
        db.rollback()
    finally:
        db.close()


async def run_agent_task(
    agent_id: int,
    user_id: int,
    task_id: int,
    description: str,
    agent_name: str,
) -> None:
    """
    Execute one queued task end-to-end.
    Failures mark the task failed; partial skill results are still recorded in result text.
    """
    db = SessionLocal()
    cfg: dict = {}
    model = "fast"
    mode = "general"
    agent_name = agent_name or "Agent"
    task_title = ""
    task_priority = "medium"
    task_labels = ""
    try:
        t = db.get(models.Task, task_id)
        if not t:
            return
        t.status = "in_progress"
        t.updated_at = datetime.utcnow()
        a = db.get(models.Agent, agent_id)
        if not a:
            t.status = "failed"
            t.result = "Agent missing"
            t.completed_at = datetime.utcnow()
            # Keep auto-chain rollup/skip consistent even on early hard fails
            try:
                from .task_chain import on_task_finished
                await on_task_finished(db, t, final_status="failed", commit=False)
            except Exception as chain_err:
                log.warning("task_chain on agent-missing fail: %s", chain_err)
            db.commit()
            return
        # Hot path: no full-team rewrite — only ensure this agent can execute
        rt = resolve_runtime(a)
        if not rt.can_execute:
            # Light repair once if misconfigured (viewer / wrong model), not every time forever
            repair_agent(db, a, force_never_idle=False, expand_skills=True)
            db.commit()
            db.refresh(a)
            rt = resolve_runtime(a)
        if not rt.can_execute or rt.status != "active":
            t.status = "todo"
            t.result = "Agent cannot execute (paused or no permission)"
            db.commit()
            return

        try:
            cfg = json.loads(a.config or "{}")
        except Exception:
            cfg = {}
        model = rt.model
        mode = mode_for_template(a.template_type)
        labels = (getattr(t, "labels", None) or "")
        task_labels = labels
        task_title = (t.title or "")[:200]
        task_priority = t.priority or "medium"
        # Prefer DB description (has targets); fall back to arg
        description = (t.description or description or t.title or "").strip()
        # Autonomy / self-run background work → small tier only (protect RunPod VRAM)
        if "autonomy" in labels or "self-run" in labels:
            from . import config as app_config
            model = getattr(app_config, "AUTONOMY_MODEL", None) or "small"
        elif mode == "coding" and model in ("fast", "small", "medium"):
            # Prefer quality for coding, but never jump to "large" automatically
            model = "quality"
        agent_name = a.name or agent_name
        company_id = t.company_id or a.company_id
        project_id = t.project_id or a.project_id
        db.commit()
    finally:
        db.close()

    try:
        await log_activity(agent_id, user_id, "thinking", f"Working task #{task_id}: {(task_title or description)[:80]}")

        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
            agent_row = db.get(models.Agent, agent_id)
            creds = credentials_for_user(db, user_id)
            prompt = (
                build_task_prompt(
                    db,
                    agent_row,
                    description,
                    business_context=cfg,
                    task_id=task_id,
                    task_title=task_title,
                    priority=task_priority,
                    labels=task_labels,
                )
                if agent_row
                else (
                    f"TASK #{task_id}: {task_title or 'Work item'}\n\n"
                    f"{description}\n\n"
                    f"Do the work. End with ```skill\ncomplete_task\n"
                    f'{{"task_id": {task_id}, "result": "<what you delivered>"}}\n```'
                )
            )
            # Keep background prompts short to cut tokens / GPU time
            if "autonomy" in (labels or "") and len(prompt) > 6000:
                prompt = prompt[:6000] + "\n\n[truncated for GPU budget]"
        finally:
            db.close()

        output = await complete(
            [{"role": "user", "content": prompt}], model, mode, credentials=creds,
        )

        skill_results = []
        db = SessionLocal()
        try:
            agent_row = db.get(models.Agent, agent_id)
            user = db.get(models.User, user_id)
            if agent_row and user and output:
                try:
                    from .agent_scaffold import ensure_agent_skills
                    ensure_agent_skills(db, agent_row)
                except Exception:
                    pass
                clean, skill_results = await run_skills_from_text(db, agent_row, user, output)
                output = clean or output
                if skill_results:
                    lines = []
                    for r in skill_results[:12]:
                        mark = "ok" if r.get("ok") else "FAIL"
                        lines.append(
                            f"- [{mark}] {r.get('skill')}: "
                            f"{r.get('message') or r.get('error') or ''}"
                        )
                        await log_activity(
                            agent_id, user_id, "action",
                            f"Skill {r.get('skill')}: {str(r.get('message') or r.get('ok') or r.get('error'))[:120]}",
                        )
                    output = (
                        output
                        + "\n\n---\nSkill results:\n"
                        + "\n".join(lines)
                    )[:12000]
        finally:
            db.close()

        inp, out_tok = estimate_tokens(prompt), estimate_tokens(output)
        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
            t = db.get(models.Task, task_id)
            charged = charge_usage(
                db, user, model, inp, out_tok,
                company_id=company_id, project_id=project_id,
            )
            if t:
                t.tokens_used = (t.tokens_used or 0) + charged["tokens"]
                t.cost = (t.cost or 0) + charged["cost"]
                t.status = "completed"
                t.result = output
                t.completed_at = datetime.utcnow()
                # Auto-chain: roll up parent goal, queue next sibling.
                # commit=False — we own one transaction for billing + task + chain.
                try:
                    from .task_chain import on_task_finished
                    await on_task_finished(
                        db, t, final_status="completed", commit=False,
                    )
                except Exception as chain_err:
                    log.warning("task_chain on complete failed: %s", chain_err)
            # Single commit: task terminal state, usage, parent rollup, next sibling
            db.commit()
            cost = charged["cost"]
            tokens = charged["tokens"]
            period = charged.get("tokens_used_period")
        finally:
            db.close()

        if cfg.get("notify_email"):
            ok, detail = await channels.send_email(
                cfg["notify_email"], f"{agent_name}: task completed", output,
                credentials=creds,
            )
            await log_activity(agent_id, user_id, "email", detail)
        if cfg.get("notify_sms"):
            ok, detail = await channels.send_sms(
                cfg["notify_sms"], output[:300], credentials=creds,
            )
            await log_activity(agent_id, user_id, "sms", detail)

        await manager.broadcast(
            f"tokens:{user_id}",
            {
                "event": "usage",
                "tokens": tokens,
                "cost": cost,
                "model": model,
                "tokens_used_period": period,
            },
        )
        await log_activity(
            agent_id, user_id, "done",
            f"Task completed ({len(skill_results)} skills)",
        )
        await manager.broadcast(
            f"agents:{user_id}",
            {"event": "task_done", "agent_id": agent_id, "task_id": task_id},
        )
    except Exception as e:
        log.exception("run_agent_task failed task=%s", task_id)
        db = SessionLocal()
        try:
            t = db.get(models.Task, task_id)
            if t:
                t.status = "failed"
                t.result = str(e)[:500]
                t.completed_at = datetime.utcnow()
                # commit=False — single commit below for fail + chain rollup
                try:
                    from .task_chain import on_task_finished
                    await on_task_finished(
                        db, t, final_status="failed", commit=False,
                    )
                except Exception as chain_err:
                    log.warning("task_chain on fail failed: %s", chain_err)
                db.commit()
        finally:
            db.close()
        await log_activity(agent_id, user_id, "info", f"Task failed: {str(e)[:120]}")
        await manager.broadcast(
            f"agents:{user_id}",
            {"event": "task_done", "agent_id": agent_id, "task_id": task_id},
        )
