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
from .llm import complete_with_usage
from .pricing import estimate_tokens, estimate_messages_tokens
from .usage_billing import charge_usage, bill_llm_turn
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
    run_inline: bool | None = None,
    timeout_sec: float | None = None,
) -> bool:
    """Schedule immediate execution for a queued task (do not wait for daily cron).

    Returns True if a run was scheduled (or left queued safely). Safe after
    create_task / claim / goal-chain unlock. No-ops if missing/paused.

    run_inline:
      None  → auto (serverless: short budget; local: background)
      True  → claim + run via schedule() with timeout
      False → leave status=queued only (cron/tick will pick it up) — use from chat
              so the HTTP reply is never blocked by multi-turn task LLM work
    """
    from .async_jobs import schedule, is_serverless

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
        labels = (getattr(t, "labels", None) or "")

        # Never start multi-turn runner inside interactive chat (504 / browser timeouts).
        # Logs showed POST /agents/*/chat running 5× quality LLM turns + re-queue in one request.
        from .request_context import defer_task_runs
        defer = (
            run_inline is False
            or defer_task_runs()
            or (
                run_inline is None
                and is_serverless()
                and any(
                    tag in labels
                    for tag in (
                        "post-chat", "auto-workflow", "self-run", "autonomy",
                        "auto-chain", "goal", "self-assigned",
                    )
                )
            )
            # Serverless default: queue only unless caller forces run_inline=True
            or (run_inline is None and is_serverless())
        )
        if defer:
            t.updated_at = datetime.utcnow()
            db.commit()
            log.info(
                "kick deferred (queued) task_id=%s labels=%s chat_scope=%s",
                task_id, labels[:80], defer_task_runs(),
            )
            return True

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
        # Short budget on serverless so API handlers still return
        budget = timeout_sec
        if budget is None and is_serverless():
            budget = 25.0
        await schedule(run_agent_task(a_id, u_id, tid, tdesc, aname), timeout_sec=budget)
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
        elif model in ("fast", "small", "medium"):
            # Multi-skill board work (CRM, outreach, coding, auto-chain) needs quality+
            heavy = (
                mode in ("coding", "sales")
                or "auto-chain" in labels
                or "goal" in labels
                or any(
                    k in (description or "").lower()
                    for k in (
                        "create_customer", "create_deal", "crm", "pipeline",
                        "send_email", "outreach", "sales target", "lead",
                    )
                )
            )
            if heavy or mode == "coding":
                model = "quality"
        agent_name = a.name or agent_name
        company_id = t.company_id or a.company_id
        project_id = t.project_id or a.project_id
        db.commit()
    finally:
        db.close()

    try:
        await log_activity(
            agent_id, user_id, "thinking",
            f"Working task #{task_id}: {(task_title or description)[:80]}",
        )

        from . import config as app_config
        from .orchestration.finalize import (
            finalize_task_after_run,
            skill_closed_task,
            skill_persisted_data,
        )

        is_autonomy = "autonomy" in (labels or "") or "self-run" in (labels or "")
        is_post_chat = "post-chat" in (labels or "") or "auto-workflow" in (labels or "")
        max_turns = int(
            getattr(app_config, "TASK_RUNNER_AUTONOMY_MAX_TURNS", 3)
            if is_autonomy or is_post_chat
            else getattr(app_config, "TASK_RUNNER_MAX_TURNS", 5)
        )
        # Serverless: keep turns low so a kicked job cannot outlive the HTTP budget
        try:
            from .async_jobs import is_serverless
            if is_serverless():
                max_turns = min(max_turns, 2 if not is_post_chat else 1)
        except Exception:
            pass
        max_turns = max(1, min(8, max_turns))

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
            if is_autonomy and len(prompt) > 6000:
                prompt = prompt[:6000] + "\n\n[truncated for GPU budget]"
        finally:
            db.close()

        messages: list[dict] = [{"role": "user", "content": prompt}]
        all_skill_results: list[dict] = []
        output = ""
        cost = 0.0
        tokens = 0
        period = None
        meter_payload: dict = {}
        charged: dict = {"tokens": 0, "cost": 0.0, "tokens_used_period": None, "credits": None}
        final_status = "in_progress"
        final_reason = "started"

        for turn in range(max_turns):
            turn_n = turn + 1
            await log_activity(
                agent_id, user_id, "thinking",
                f"Task #{task_id} turn {turn_n}/{max_turns}",
            )
            turn_out, turn_usage = await complete_with_usage(
                messages, model, mode, credentials=creds,
            )
            turn_out = turn_out or ""
            output = turn_out

            turn_skills: list[dict] = []
            db = SessionLocal()
            try:
                agent_row = db.get(models.Agent, agent_id)
                user = db.get(models.User, user_id)
                if agent_row and user and turn_out:
                    try:
                        from .agent_scaffold import ensure_agent_skills
                        ensure_agent_skills(db, agent_row)
                    except Exception:
                        pass
                    clean, turn_skills = await run_skills_from_text(
                        db, agent_row, user, turn_out,
                    )
                    output = clean or turn_out
                    # Ensure any skill that only flushed still persists
                    try:
                        db.commit()
                    except Exception:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                    if turn_skills:
                        lines = []
                        for r in turn_skills[:16]:
                            mark = "ok" if r.get("ok") else "FAIL"
                            lines.append(
                                f"- [{mark}] {r.get('skill')}: "
                                f"{r.get('message') or r.get('error') or ''}"
                            )
                            await log_activity(
                                agent_id, user_id, "action",
                                f"Skill {r.get('skill')}: "
                                f"{str(r.get('message') or r.get('ok') or r.get('error'))[:120]}",
                            )
                        output = (
                            output
                            + "\n\n---\nSkill results (turn "
                            + f"{turn_n}):\n"
                            + "\n".join(lines)
                        )[:12000]
            finally:
                db.close()

            all_skill_results.extend(turn_skills)

            more_turns = turn_n < max_turns
            closed = skill_closed_task(turn_skills) or skill_closed_task(all_skill_results)

            db = SessionLocal()
            try:
                user = db.get(models.User, user_id)
                t = db.get(models.Task, task_id)
                # Bill FULL conversation (all turns) + reply — not just last user line
                charged = bill_llm_turn(
                    db, user, model, messages, output,
                    company_id=company_id, project_id=project_id,
                    usage=turn_usage,
                )
                cost += float(charged.get("cost") or 0)
                tokens += int(charged.get("tokens") or 0)
                period = charged.get("tokens_used_period")
                if t:
                    t.tokens_used = (t.tokens_used or 0) + int(charged.get("tokens") or 0)
                    t.cost = (t.cost or 0) + float(charged.get("cost") or 0)
                    t.updated_at = datetime.utcnow()
                    # Keep busy while looping
                    if (t.status or "").lower() not in ("completed", "failed", "review"):
                        t.status = "in_progress"
                        t.completed_at = None
                    try:
                        agent_row = db.get(models.Agent, agent_id)
                        fin = await finalize_task_after_run(
                            db, t,
                            agent=agent_row,
                            output=output,
                            skill_results=all_skill_results,
                            require_close_skill=True,
                            more_turns_available=more_turns and not closed,
                        )
                        final_status = str(fin.get("status") or t.status or "in_progress")
                        final_reason = str(fin.get("reason") or "")
                        log.info(
                            "finalize task=%s turn=%s status=%s reason=%s skills=%s persisted=%s",
                            task_id, turn_n, final_status, final_reason,
                            len(all_skill_results), fin.get("persisted"),
                        )
                    except Exception as fin_err:
                        log.warning("finalize_task_after_run failed: %s", fin_err)
                        # Never fake-complete without a close skill
                        cur = (t.status or "").lower()
                        if cur not in ("review", "failed", "completed"):
                            t.status = "in_progress"
                            t.result = (output or "")[:12000]
                            t.completed_at = None
                            final_status = "in_progress"
                            final_reason = "finalize_error_keep_busy"
                db.commit()
                try:
                    from .usage_billing import meter_snapshot
                    if user:
                        meter_payload = meter_snapshot(db, user)
                except Exception:
                    meter_payload = {
                        "tokens_used_period": period,
                        "credits": charged.get("credits"),
                    }
            finally:
                db.close()

            await manager.broadcast(
                f"tokens:{user_id}",
                {
                    "event": "usage",
                    "tokens": int(charged.get("tokens") or 0),
                    "cost": float(charged.get("cost") or 0),
                    "model": model,
                    "tokens_used_period": period,
                    "credits": charged.get("credits"),
                    "meter": meter_payload or None,
                    "source": "task_runner",
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "turn": turn_n,
                },
            )

            # Stop when task is closed/review, or no more turns
            if final_status in ("completed", "failed", "review") or closed:
                break
            if not more_turns:
                break

            # Continue working — feed skill outcomes back into the model
            skill_summary = ""
            if turn_skills:
                skill_summary = "\n".join(
                    f"- {'ok' if r.get('ok') else 'FAIL'} {r.get('skill')}: "
                    f"{(r.get('message') or r.get('error') or '')[:200]}"
                    for r in turn_skills[:20]
                )
            else:
                skill_summary = "(no skill blocks executed last turn)"

            messages.append({"role": "assistant", "content": (turn_out or "")[:8000]})
            messages.append({
                "role": "user",
                "content": (
                    f"CONTINUE task #{task_id} (turn {turn_n + 1}/{max_turns}). "
                    f"You are still IN PROGRESS — do not stop until the work is done.\n\n"
                    f"Last skill results:\n{skill_summary}\n\n"
                    f"Rules:\n"
                    f"1) If data still needs saving (CRM, memory, deals, fields), emit those skill blocks now.\n"
                    f"2) When DONE WHEN / CHECKLIST are satisfied, you MUST call:\n"
                    f"```skill\ncomplete_task\n"
                    f'{{"task_id": {task_id}, "result": "<what you delivered>"}}\n```\n'
                    f"3) If blocked after a real attempt, set_task_status failed with a clear note.\n"
                    f"4) Do not only chat — use skills to persist data and close the task."
                ),
            })
            # Cap conversation growth
            if len(messages) > 8:
                messages = [messages[0]] + messages[-6:]

        # If still open after all turns, re-queue so the agent stays busy until done
        db = SessionLocal()
        try:
            t = db.get(models.Task, task_id)
            if t and (t.status or "").lower() == "in_progress":
                prior_requeues = (t.result or "").count("[AUTO-REQUEUE]")
                # Cap requeues to avoid infinite GPU burn; stuck escalator handles longer stalls
                if (
                    all_skill_results
                    and not skill_closed_task(all_skill_results)
                    and prior_requeues < 2
                ):
                    t.status = "queued"
                    t.updated_at = datetime.utcnow()
                    saved = sorted(
                        {
                            str(r.get("skill"))
                            for r in all_skill_results
                            if r.get("ok") and r.get("skill")
                        }
                    )
                    note = (
                        f"\n\n[AUTO-REQUEUE] Still working after {max_turns} turn(s); "
                        f"queued for next run (#{prior_requeues + 1}). "
                        f"Saved skills so far: {', '.join(saved) or 'none'}."
                    )
                    t.result = ((t.result or "") + note)[:12000]
                    db.commit()
                    final_status = "queued"
                    final_reason = "requeued_continue"
                    log.info(
                        "task=%s re-queued to continue work (requeue=%s)",
                        task_id, prior_requeues + 1,
                    )
                    try:
                        # One immediate continue for board work (not self-run fluff).
                        # Never chain-await multi-turn on serverless (blocks chat/API).
                        from .async_jobs import schedule, is_serverless
                        if not is_autonomy and prior_requeues == 0 and not is_serverless():
                            await schedule(
                                run_agent_task(
                                    agent_id, user_id, task_id,
                                    t.description or description, agent_name,
                                )
                            )
                    except Exception as cont_err:
                        log.warning("continue schedule failed: %s", cont_err)
                else:
                    # Stay in_progress — agent still "busy" until complete_task or escalate
                    t.updated_at = datetime.utcnow()
                    if prior_requeues >= 2:
                        stall = (
                            "\n\n[NEEDS ATTENTION] Multiple continue attempts without "
                            "complete_task. Lead can review_task or agent will be re-kicked "
                            "by autonomy/stuck checks."
                        )
                        t.result = ((t.result or "") + stall)[:12000]
                    db.commit()
        finally:
            db.close()

        if cfg.get("notify_email") and final_status in ("completed", "failed", "review"):
            ok, detail = await channels.send_email(
                cfg["notify_email"],
                f"{agent_name}: task {final_status}",
                output,
                credentials=creds,
            )
            await log_activity(agent_id, user_id, "email", detail)
        if cfg.get("notify_sms") and final_status in ("completed", "failed", "review"):
            ok, detail = await channels.send_sms(
                cfg["notify_sms"], output[:300], credentials=creds,
            )
            await log_activity(agent_id, user_id, "sms", detail)

        done_label = (
            f"Task {final_status} ({len(all_skill_results)} skills"
            f"{', data saved' if skill_persisted_data(all_skill_results) else ''})"
        )
        await log_activity(agent_id, user_id, "done" if final_status == "completed" else "action", done_label)
        await manager.broadcast(
            f"agents:{user_id}",
            {
                "event": "task_done" if final_status in ("completed", "failed", "review") else "task_updated",
                "agent_id": agent_id,
                "task_id": task_id,
                "status": final_status,
                "reason": final_reason,
            },
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
