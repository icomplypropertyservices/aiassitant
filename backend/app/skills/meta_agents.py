"""Agent spawn / team / notify / task orchestration skill handlers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..agent_roles import is_orchestrator, normalize_role
from ..live_ops import emit_ops
from ..usage_billing import bill_llm_turn
from .bridge import (
    get_skill_catalog,
    get_enabled_skill_ids,
    set_enabled_skills,
    skills_for_template,
    skill_pack_for_template,
    skills_for_pack,
)


async def _skill_spawn(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    name = (args.get("name") or "New agent").strip()[:120]
    if not name:
        return {"ok": False, "error": "name is required"}
    template = (args.get("template_type") or "custom").strip()[:80] or "custom"
    personality = (args.get("personality") or "Professional, helpful, concise.").strip()
    hrole = (args.get("hierarchy_role") or "member").strip()
    if hrole not in ("lead", "member", "specialist", "orchestrator"):
        hrole = "member"
    # UI spawn always creates a report under the parent agent unless orchestrator child
    parent_id = args.get("parent_id")
    if parent_id is None:
        # Hang new agent under the spawner (orchestrators may leave parent null only if requested)
        parent_id = agent.id
    else:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            parent_id = agent.id
    if parent_id == 0:
        parent_id = None

    # Plan cap (skill path used by chat + UI)
    try:
        from ..plans import plan_limits
        count = db.query(models.Agent).filter_by(user_id=user.id).count()
        max_agents = int(plan_limits(user.plan).get("agents") or 0)
        if user.role != "admin" and max_agents and count >= max_agents:
            return {
                "ok": False,
                "error": f"Plan limit: {max_agents} agents. Upgrade or delete an agent first.",
            }
    except Exception:
        pass

    from ..agent_scaffold import map_model, repair_agent

    child = models.Agent(
        user_id=user.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        parent_id=parent_id,
        hierarchy_role=hrole,
        is_lead=hrole == "lead",
        name=name,
        template_type=template,
        personality=personality,
        model=map_model(agent.model or "fast"),
        status="active",
        idle_mode="never_idle",
        permission_level="lead" if hrole == "lead" else "operator",
        config=json.dumps({"autonomy": "full", "spawned_by": agent.id}),
        escalate_when="on_failure",
        escalate_to="parent",
    )
    db.add(child)
    db.flush()
    # expand_skills → ensure_agent_skills: role + template_type pack
    repair_agent(db, child, force_never_idle=True, expand_skills=True)
    from ..agent_scaffold import ensure_agent_skills
    ensure_agent_skills(db, child)
    # Layer complete template pack (never domain-keywords-only)
    pack_skills = skills_for_template(template, get_skill_catalog(), role=hrole)
    if pack_skills:
        set_enabled_skills(db, child, pack_skills)
    db.commit()
    db.refresh(child)
    return {
        "ok": True,
        "message": f"Spawned autonomous agent {child.name} (id={child.id})",
        "agent": {
            "id": child.id,
            "name": child.name,
            "hierarchy_role": child.hierarchy_role,
            "model": child.model,
            "idle_mode": child.idle_mode,
            "permission_level": child.permission_level,
        },
    }

async def _skill_message(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        to_id = int(args.get("to_agent_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "to_agent_id required"}
    target = db.get(models.Agent, to_id)
    if not target or target.user_id != user.id:
        return {"ok": False, "error": "Target agent not found"}
    content = (args.get("message") or "").strip()
    if not content:
        return {"ok": False, "error": "message required"}

    pair = sorted([agent.id, target.id])
    thread_key = f"{pair[0]}-{pair[1]}"
    # Build kwargs only for columns that exist (older DBs may lack status/meta_json)
    msg_kwargs: dict[str, Any] = {
        "user_id": user.id,
        "from_agent_id": agent.id,
        "to_agent_id": target.id,
        "thread_key": thread_key,
        "content": content,
    }
    if hasattr(models.AgentMessage, "status"):
        msg_kwargs["status"] = "sent"
    msg = models.AgentMessage(**msg_kwargs)
    db.add(msg)
    db.commit()
    db.refresh(msg)

    reply_text = None
    a2a_usage = None
    if args.get("expect_reply", True):
        # Lightweight auto-reply from target using their personality (no nested skill loop)
        from ..llm import complete
        from ..user_keys import credentials_for_user
        from ..agent_prompts import build_agent_system_prompt

        system = build_agent_system_prompt(db, target)
        prompt = (
            f"You received an internal message from teammate agent "
            f"{agent.name} (id={agent.id}):\n\n{content}\n\n"
            "Reply helpfully in 1-3 short paragraphs. Do not emit skill blocks."
        )
        creds = credentials_for_user(db, user.id)
        try:
            reply_text = await complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                target.model or "quality",
                "general",
                credentials=creds,
            )
            reply_text = (reply_text or "").strip()
            if reply_text:
                reply = models.AgentMessage(
                    user_id=user.id,
                    from_agent_id=target.id,
                    to_agent_id=agent.id,
                    thread_key=thread_key,
                    content=reply_text,
                )
                db.add(reply)
                db.commit()
                # Agent-to-agent LLM always meters tokens
                try:
                    a2a_usage = bill_llm_turn(
                        db, user, target.model or "fast",
                        [{"role": "user", "content": prompt}],
                        reply_text,
                    )
                except Exception:
                    a2a_usage = None
        except Exception as e:
            reply_text = f"(auto-reply failed: {e})"
            a2a_usage = None

    out = {
        "ok": True,
        "message": f"Messaged {target.name}",
        "thread_key": thread_key,
        "message_id": msg.id,
        "reply": reply_text,
    }
    if a2a_usage:
        out["usage"] = a2a_usage
    return out

async def _skill_assign_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    # Default to account "My Human" when human_id omitted
    human = None
    raw_hid = args.get("human_id")
    if raw_hid in (None, "", 0, "0"):
        try:
            from ..human_service import ensure_my_human
            human = ensure_my_human(db, user)
            db.flush()
        except Exception:
            human = None
    else:
        try:
            human_id = int(raw_hid)
        except (TypeError, ValueError):
            return {"ok": False, "error": "human_id required (or omit to use My Human)"}
        human = db.get(models.Human, human_id)
    if not human or human.owner_user_id != user.id:
        return {"ok": False, "error": "Human not found — open Team to create My Human"}
    title = (args.get("title") or args.get("description") or "Work item")[:120]
    description = (args.get("description") or title).strip()
    priority = args.get("priority") or "medium"
    if (human.status or "").lower() != "active":
        return {
            "ok": False,
            "error": f"Human '{human.name}' is not active — activate them to assign and notify",
        }
    t = models.Task(
        user_id=user.id,
        agent_id=agent.id,
        human_id=human.id,
        assignee_type="human",
        company_id=human.company_id or agent.company_id,
        project_id=human.project_id or agent.project_id,
        title=title,
        description=f"[Assigned by agent {agent.name}] {description}",
        status="todo",
        priority=priority,
        labels="human,allocated" + (",my-human" if getattr(human, "is_my_human", False) else ""),
    )
    db.add(t)
    db.flush()
    try:
        from ..human_service import post_human_message
        post_human_message(
            db,
            user=user,
            human_id=human.id,
            content=f"[{agent.name}] Assigned: {title}\n{description}"[:4000],
            sender_role="agent",
            sender_agent_id=agent.id,
            task_id=t.id,
            kind="task_delegate",
        )
    except Exception:
        pass
    db.commit()
    db.refresh(t)
    try:
        from ..human_notify import notify_human
        notify = await notify_human(
            db, user,
            title=f"New work: {title}",
            details=description,
            human_id=human.id,
            agent=agent,
            force_email=True,
            force_sms=True,
            link_path="/humans",
        )
    except Exception as e:
        notify = {"ok": False, "error": str(e)}
    await emit_ops(
        user.id,
        kind="human",
        status="queued",
        title=f"Work for {human.name}",
        detail=title,
        agent_id=agent.id,
        human_id=human.id,
        task_id=t.id,
        db=db,
    )
    return {
        "ok": True,
        "message": f"Assigned to {human.name}" + (" (My Human)" if getattr(human, "is_my_human", False) else ""),
        "task_id": t.id,
        "human": {
            "id": human.id,
            "name": human.name,
            "email": human.email,
            "phone": getattr(human, "phone", ""),
            "is_my_human": bool(getattr(human, "is_my_human", False)),
        },
        "notify": notify,
    }

async def _skill_save_memory(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "content required"}
    mem = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind=(args.get("kind") or "note")[:40],
        title=(args.get("title") or content[:60])[:200],
        content=content,
        tags=(args.get("tags") or "")[:200],
    )
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return {"ok": True, "message": "Saved to agent data vault", "memory_id": mem.id}

async def _skill_save_training(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "content required"}
    title = (args.get("title") or f"From {agent.name}")[:200]
    folder_id = args.get("folder_id")
    try:
        folder_id = int(folder_id) if folder_id is not None else None
    except (TypeError, ValueError):
        folder_id = None

    try:
        from ..storage_quota import assert_storage_allows
        assert_storage_allows(db, user, len(content.encode("utf-8")))
    except Exception as e:
        detail = getattr(e, "detail", None)
        if isinstance(detail, dict):
            return {"ok": False, "error": detail.get("message") or "storage limit reached", "storage": detail.get("storage")}
        return {"ok": False, "error": str(detail or e)}

    kf = models.KnowledgeFile(
        user_id=user.id,
        folder_id=folder_id,
        name=title,
        description=f"Saved by agent {agent.name}",
        tags=(args.get("tags") or "agent-saved")[:200],
        kind="note",
        storage="local",
        mime_type="text/plain",
        size_bytes=len(content.encode("utf-8")),
        content_text=content,
        status="ready",
    )
    db.add(kf)
    db.flush()
    # Grant this agent access
    db.add(models.AgentKnowledgeAccess(
        agent_id=agent.id,
        resource_type="file",
        resource_id=kf.id,
        permission="read",
    ))
    # Also keep a memory pointer
    mem = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind="training_candidate",
        title=title,
        content=content[:2000],
        tags="training",
        knowledge_file_id=kf.id,
    )
    db.add(mem)
    db.commit()
    db.refresh(kf)
    return {
        "ok": True,
        "message": f"Saved to training library as '{title}'",
        "knowledge_file_id": kf.id,
    }

async def _skill_execute_goal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """One prompt → parent goal + hierarchy-delegated subtasks + queue + monitor."""
    from ..task_chain import start_goal_chain

    goal = (args.get("goal") or args.get("prompt") or args.get("description") or args.get("title") or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required"}
    try:
        max_steps = min(12, max(2, int(args.get("max_steps") or 6)))
    except (TypeError, ValueError):
        max_steps = 6
    company_id = args.get("company_id")
    project_id = args.get("project_id")
    try:
        company_id = int(company_id) if company_id not in (None, "") else None
    except (TypeError, ValueError):
        company_id = None
    try:
        project_id = int(project_id) if project_id not in (None, "") else None
    except (TypeError, ValueError):
        project_id = None
    steps = args.get("steps")
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("\n") if s.strip()]
    return await start_goal_chain(
        db,
        user,
        agent,
        goal,
        title=(args.get("title") or None),
        company_id=company_id,
        project_id=project_id,
        priority=(args.get("priority") or "high"),
        steps=steps if isinstance(steps, list) else None,
        max_steps=max_steps,
        auto_queue=True,
    )

def _compose_task_brief(
    description: str,
    *,
    title: str = "",
    success_criteria: str = "",
    done_when: str = "",
    target: str = "",
    owner_name: str = "",
) -> str:
    """Attach measurable DONE WHEN / TARGET lines so agents finish for real."""
    body = (description or title or "Task").strip()
    sc = (success_criteria or done_when or "").strip()
    tgt = (target or "").strip()
    if not sc and not tgt:
        # Auto target from title when agent forgot criteria
        sc = f"Deliver a concrete output for: {(title or body)[:160]}"
    lines = [body, "", "---", "ACCEPTANCE (must satisfy to complete):"]
    if sc:
        lines.append(f"DONE WHEN: {sc}")
    if tgt:
        lines.append(f"TARGET: {tgt}")
    if owner_name:
        lines.append(f"Owner agent: {owner_name}")
    lines.append("When finished, call complete_task with task_id and a result that proves the target.")
    return "\n".join(lines)[:8000]


async def _skill_create_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or args.get("description") or "Task")[:120]
    raw_desc = (args.get("description") or title).strip()
    success_criteria = (
        args.get("success_criteria")
        or args.get("done_when")
        or args.get("acceptance")
        or ""
    )
    target_metric = args.get("target") or args.get("goal_target") or ""
    description = _compose_task_brief(
        raw_desc,
        title=title,
        success_criteria=str(success_criteria),
        done_when=str(args.get("done_when") or ""),
        target=str(target_metric),
        owner_name=agent.name or "",
    )
    # Default: assign to self (agents can give themselves work)
    agent_id = args.get("agent_id")
    if agent_id in (None, "", "self", "me"):
        agent_id = agent.id
    human_id = args.get("human_id")
    try:
        agent_id = int(agent_id) if agent_id is not None else agent.id
    except (TypeError, ValueError):
        agent_id = agent.id
    try:
        human_id = int(human_id) if human_id is not None else None
    except (TypeError, ValueError):
        human_id = None

    # run_now=false forces todo (skip autonomy queue); default True
    run_now_raw = args.get("run_now", True)
    if isinstance(run_now_raw, str):
        run_now = run_now_raw.strip().lower() not in ("0", "false", "no", "off", "")
    else:
        run_now = bool(run_now_raw) if run_now_raw is not None else True

    target = db.get(models.Agent, agent_id)
    if not target or target.user_id != user.id:
        return {"ok": False, "error": "agent not found"}

    if human_id is not None:
        human = db.get(models.Human, human_id)
        if not human or human.owner_user_id != user.id:
            return {"ok": False, "error": "human not found"}

    # Status: human → todo; active agent (and run_now) → queued for autonomy; else todo
    from ..task_status import initial_task_status

    assignee_type = "human" if human_id is not None else "agent"
    status = initial_task_status(
        agent=target if human_id is None else None,
        human_id=human_id,
        assignee_type=assignee_type,
        run_now=run_now,
    )

    labels = "skill-created"
    if agent_id == agent.id:
        labels = f"{labels},self-assigned"
    task_kwargs: dict[str, Any] = {
        "user_id": user.id,
        "agent_id": target.id,
        "human_id": human_id,
        "assignee_type": assignee_type,
        "company_id": target.company_id,
        "project_id": target.project_id,
        "title": title,
        "description": description,
        "status": status,
        "priority": args.get("priority") or "medium",
        "labels": labels,
    }

    # Optional DAG / meeting origin (only if model columns exist)
    if hasattr(models.Task, "meeting_id"):
        try:
            mid = args.get("meeting_id")
            task_kwargs["meeting_id"] = int(mid) if mid is not None and mid != "" else None
        except (TypeError, ValueError):
            task_kwargs["meeting_id"] = None
    if hasattr(models.Task, "parent_task_id"):
        try:
            pid = args.get("parent_task_id")
            task_kwargs["parent_task_id"] = int(pid) if pid is not None and pid != "" else None
        except (TypeError, ValueError):
            task_kwargs["parent_task_id"] = None
        # Validate parent belongs to same user when set
        parent_id = task_kwargs.get("parent_task_id")
        if parent_id is not None:
            parent = db.get(models.Task, parent_id)
            if not parent or parent.user_id != user.id:
                return {"ok": False, "error": "parent_task not found"}
            parent_labels = (parent.labels or "")
            chain_parent = (
                "goal" in parent_labels
                or "auto-chain" in parent_labels
                or "plan" in parent_labels
            )
            # Under a goal/auto-chain parent: track with auto-chain labels and
            # respect sequential unlock (only queue when nothing is in flight
            # and no earlier sibling is still waiting as todo).
            if chain_parent:
                if "auto-chain" not in labels:
                    labels = f"{labels},auto-chain" if labels else "auto-chain"
                    task_kwargs["labels"] = labels
                siblings = (
                    db.query(models.Task)
                    .filter(models.Task.parent_task_id == parent_id)
                    .all()
                )
                in_flight = any((s.status or "") in ("queued", "in_progress") for s in siblings)
                waiting_todo = any((s.status or "") == "todo" for s in siblings)
                if (
                    human_id is None
                    and getattr(target, "status", None) == "active"
                    and not in_flight
                    and not waiting_todo
                ):
                    task_kwargs["status"] = "queued"
                elif human_id is None:
                    task_kwargs["status"] = "todo"
            elif human_id is None and getattr(target, "status", None) == "active":
                # Non-chain DAG children: queue for autonomy pickup
                task_kwargs["status"] = "queued"

    t = models.Task(**task_kwargs)
    db.add(t)
    db.commit()
    db.refresh(t)

    kicked = False
    if (t.status or "") == "queued" and human_id is None:
        try:
            from ..task_runner import kick_queued_task
            kicked = await kick_queued_task(
                t.id,
                user_id=user.id,
                agent_id=target.id,
                description=t.description,
                agent_name=target.name,
            )
        except Exception:
            kicked = False

    # Best-effort live UI update
    try:
        from ..ws import manager
        from ..agent_serialize import task_dict
        await manager.broadcast(
            f"agents:{user.id}",
            {"event": "task_updated", "task": task_dict(t, db)},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "message": (
            f"Task #{t.id} created → {target.name} [{t.status}]"
            + (" · run started" if kicked else "")
        ),
        "task_id": t.id,
        "status": t.status,
        "assignee_type": t.assignee_type,
        "agent_id": target.id,
        "agent_name": target.name,
        "run_started": kicked,
        "success_criteria": str(success_criteria or target_metric or "")[:300] or None,
    }

async def _skill_announce_plan(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Publish plan to live ops and create parent + child Task rows.

    Backward compatible: string steps stay on the announcing agent.
    Dict steps may carry agent_id / role (also role_hint, template_type);
    those are assigned via task_chain.pick_assignee. Active assignees are queued.
    """
    title = (args.get("title") or "Plan")[:200]
    steps = args.get("steps") or []
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("\n") if s.strip()]
    if not isinstance(steps, list):
        steps = []
    plan_id = f"plan-{uuid.uuid4().hex[:10]}"

    from ..task_chain import pick_assignee
    from ..task_status import initial_task_status

    # Normalize steps: strings stay simple (backward compat); dicts may carry agent_id / role
    normalized: list[dict[str, Any]] = []
    for s in steps[:20]:
        if isinstance(s, str):
            text = s.strip()
            if text:
                normalized.append({"_raw": text, "title": text, "description": text, "_string": True})
        elif isinstance(s, dict):
            stitle = (
                s.get("title") or s.get("description") or s.get("text") or s.get("step") or ""
            )
            stitle = str(stitle).strip() if stitle is not None else ""
            sdesc = s.get("description") or s.get("text") or s.get("step") or stitle
            sdesc = str(sdesc).strip() if sdesc is not None else stitle
            if not stitle and not sdesc:
                stitle = sdesc = json.dumps(s)[:200]
            entry = dict(s)
            entry["title"] = stitle or sdesc or "Step"
            entry["description"] = sdesc or stitle
            entry["_string"] = False
            entry["_raw"] = entry["description"]
            normalized.append(entry)
        else:
            text = str(s)
            normalized.append({"_raw": text, "title": text, "description": text, "_string": True})

    # Resolve assignees, then persist Task DAG, then emit ops (with task_ids).
    resolved: list[dict[str, Any]] = []
    for i, step in enumerate(normalized):
        step_text = f"{step.get('title') or ''} {step.get('description') or ''}".strip()
        is_string = bool(step.get("_string"))
        pref_id = step.get("agent_id")
        try:
            pref_id = int(pref_id) if pref_id is not None and pref_id != "" else None
        except (TypeError, ValueError):
            pref_id = None
        preferred_role = (
            step.get("role_hint") or step.get("role") or step.get("template_type") or None
        )
        if preferred_role is not None:
            preferred_role = str(preferred_role).strip() or None

        has_assignee_hint = bool(pref_id or preferred_role)

        # String steps (no agent_id/role): keep announcer — backward compatible.
        # Dict steps with agent_id / role: pick_assignee with that preference.
        # Other dicts: pick_assignee for hierarchy / keyword routing.
        if is_string and not has_assignee_hint:
            assignee = agent
        elif has_assignee_hint or not is_string:
            assignee = pick_assignee(
                db,
                user,
                owner=agent,
                step_index=i,
                step_text=step_text,
                preferred_agent_id=pref_id,
                preferred_role=preferred_role,
            )
        else:
            assignee = agent

        status = initial_task_status(agent=assignee, assignee_type="agent", run_now=True)
        resolved.append(
            {
                "index": i + 1,
                "title": (step.get("title") or f"Step {i + 1}")[:120],
                "description": (step.get("description") or step.get("_raw") or "")[:2000],
                "assignee": assignee,
                "status": status,
            }
        )

    # Parent plan (todo / monitor) + plan-step children (queued when assignee active)
    parent = models.Task(
        user_id=user.id,
        agent_id=agent.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        title=f"Plan: {title}"[:200],
        description=f"{len(resolved)} steps · plan_id={plan_id}",
        status="todo",
        labels="plan",
        assignee_type="agent",
    )
    db.add(parent)
    db.flush()
    child_ids: list[int] = []
    assignments: list[dict[str, Any]] = []
    for item in resolved:
        a = item["assignee"]
        child = models.Task(
            user_id=user.id,
            agent_id=a.id,
            company_id=a.company_id or agent.company_id,
            project_id=a.project_id or agent.project_id,
            parent_task_id=parent.id,
            title=f"Step {item['index']}: {item['title'][:100]}"[:200],
            description=item["description"][:2000],
            status=item["status"],
            labels="plan-step",
            assignee_type="agent",
        )
        db.add(child)
        db.flush()
        child_ids.append(child.id)
        assignments.append(
            {
                "task_id": child.id,
                "title": child.title,
                "agent_id": a.id,
                "agent_name": a.name,
                "status": child.status,
            }
        )
    db.commit()
    db.refresh(parent)

    await emit_ops(
        user.id,
        kind="plan",
        status="running",
        title=title,
        detail=f"{len(resolved)} steps",
        agent_id=agent.id,
        task_id=parent.id,
        plan_id=plan_id,
        payload={"steps": steps[:20], "assignments": assignments},
        db=db,
    )
    for item, assignment in zip(resolved, assignments):
        a = item["assignee"]
        detail = item["description"][:500]
        if a.id != agent.id:
            detail = f"→ {a.name}: {detail}"[:500]
        await emit_ops(
            user.id,
            kind="step",
            status="queued" if item["status"] == "queued" else item["status"],
            title=f"Step {item['index']}: {item['title']}"[:120],
            detail=detail,
            agent_id=a.id,
            task_id=assignment["task_id"],
            plan_id=plan_id,
            db=db,
        )

    return {
        "ok": True,
        "message": f"Plan announced ({len(resolved)} steps)",
        "plan_id": plan_id,
        "task_id": parent.id,
        "step_task_ids": child_ids,
        "assignments": assignments,
    }

async def _skill_notify_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Always email + SMS short cut to an active human (SMTP + Twilio required)."""
    from ..human_notify import notify_human
    title = (args.get("title") or args.get("subject") or "Agent update").strip()
    details = (
        args.get("details")
        or args.get("message")
        or args.get("body")
        or args.get("highlights")
        or ""
    )
    human_id = args.get("human_id")
    try:
        human_id = int(human_id) if human_id not in (None, "") else None
    except (TypeError, ValueError):
        human_id = None
    return await notify_human(
        db,
        user,
        title=title,
        details=str(details),
        human_id=human_id,
        agent=agent,
        force_email=True,
        force_sms=True,
        link_path=args.get("link_path") or "/tasks",
    )

async def _skill_status_update(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Status report + default notify human via email+SMS shortcuts."""
    project = args.get("project") or ""
    period = args.get("period") or "now"
    highlights = args.get("highlights") or args.get("message") or ""
    rag = (args.get("status") or "amber").strip().lower()
    title = f"Status {rag.upper()}: {project or agent.name}"[:120]
    details = f"Period: {period}\n{highlights}"
    notify_raw = args.get("notify", True)
    if isinstance(notify_raw, str):
        notify = notify_raw.strip().lower() not in ("0", "false", "no", "off")
    else:
        notify = bool(notify_raw)
    out = {
        "ok": True,
        "status": rag,
        "project": project,
        "period": period,
        "highlights": highlights,
        "report": f"[{rag.upper()}] {project or 'Work'} ({period}): {str(highlights)[:400]}",
    }
    if notify:
        note = await _skill_notify_human(db, agent, user, {
            "human_id": args.get("human_id"),
            "title": title,
            "details": details,
        })
        out["notify"] = note
        if not note.get("ok"):
            out["notify_warning"] = note.get("error") or note.get("message")
    return out

async def _skill_escalate_to_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    assigned = await _skill_assign_human(db, agent, user, {
        "human_id": args.get("human_id"),
        "title": args.get("title"),
        "description": args.get("details"),
        "priority": args.get("urgency", "high"),
    })
    # Always notify active human by SMS + email short cut
    notify = await _skill_notify_human(db, agent, user, {
        "human_id": args.get("human_id"),
        "title": args.get("title") or "Escalation from agent",
        "details": args.get("details") or assigned.get("message") or "Work assigned to you",
    })
    return {
        "ok": bool(assigned.get("ok") or assigned.get("task_id")),
        "assigned": assigned,
        "notify": notify,
        "message": "Escalated and notified human" if notify.get("ok") else "Escalated but notify incomplete",
    }

async def _skill_set_agent_status(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    if args.get("idle_mode"):
        agent.idle_mode = args["idle_mode"]
    if args.get("permission_level"):
        agent.permission_level = args["permission_level"]
    db.commit()
    return {"ok": True, "updated": {"idle_mode": agent.idle_mode, "permission_level": agent.permission_level}}

async def _skill_create_reminder(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return await _skill_create_task(db, agent, user, {
        "title": args.get("title"),
        "description": args.get("title"),
        "agent_id": args.get("for_agent_id"),
        "human_id": args.get("for_human_id"),
        "priority": "medium",
        "run_now": False,  # reminders stay todo; do not auto-queue autonomy
    })

async def _skill_spawn_team(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Spawn N agents quickly with optional preset skills. Core engine for building big teams."""
    try:
        count = max(1, min(80, int(args.get("count") or 5)))
    except Exception:
        count = 5
    base = (args.get("base_name") or "Specialist").strip() or "Specialist"
    templates = args.get("template_types") or ["member"]
    if isinstance(templates, str):
        templates = [t.strip() for t in templates.split(",") if t.strip()]
    parent_id = args.get("parent_id")
    if parent_id is None:
        parent_id = agent.id if not is_orchestrator(agent) else None
    preset = (args.get("enable_preset") or "full").lower()

    from ..agent_scaffold import scaffold_agent, map_model

    created = []
    for i in range(count):
        ttype = templates[i % len(templates)] if templates else "member"
        name = f"{base} {i+1}"
        while db.query(models.Agent).filter_by(user_id=user.id, name=name).first():
            name = f"{base} {i+1}-{uuid.uuid4().hex[:4]}"

        hrole = "lead" if ttype in ("lead", "orchestrator") else ("specialist" if ttype == "specialist" else "member")
        child = models.Agent(
            user_id=user.id,
            company_id=agent.company_id,
            project_id=agent.project_id,
            parent_id=parent_id,
            hierarchy_role=hrole,
            is_lead=hrole in ("lead", "orchestrator"),
            name=name,
            template_type=ttype,
            personality="Autonomous specialist created by " + agent.name,
            model=map_model(agent.model),
            status="active",
            idle_mode="never_idle",
            permission_level="lead" if hrole == "lead" else "operator",
            config=json.dumps({"autonomy": "full", "spawned_by": agent.id, "spawn_team": True}),
            escalate_when="on_failure",
            escalate_to="parent",
        )
        db.add(child)
        db.flush()
        scaffold_agent(db, child, full_skills=True)
        from ..agent_scaffold import ensure_agent_skills
        ensure_agent_skills(db, child)
        # Prefer template_type pack when preset is full/default; otherwise named pack
        if preset and preset not in ("full", "all", ""):
            await _apply_preset_skills(db, child, preset)
        else:
            # template_type → complete pack (sales/marketing/support/coding/…)
            pack_ids = skills_for_template(ttype, get_skill_catalog(), role=hrole)
            set_enabled_skills(db, child, pack_ids)
        created.append({"id": child.id, "name": child.name, "role": hrole})
    db.commit()
    return {"ok": True, "count": len(created), "agents": created, "message": f"Spawned team of {len(created)} agents."}

async def _apply_preset_skills(db: Session, target: models.Agent, preset: str):
    """Helper used by spawn + bulk_enable.

    Maps preset → skill pack (sales, marketing, support, coding, research,
    orchestrator, lead, full). Always includes the full role/core pack so
    create_task / execute_goal / message_agent / open_meeting stay ON.
    """
    from ..agent_scaffold import ensure_agent_skills
    from ..agent_roles import normalize_role

    preset = (preset or "").lower().strip()
    role = normalize_role(target)
    # Alias legacy preset names → canonical packs
    pack = skill_pack_for_template(preset) or preset
    if preset in ("engineering", "eng"):
        pack = "coding"
    elif preset in ("content", "growth"):
        pack = "marketing"
    elif preset in ("comms", "communication"):
        pack = "sales"
    elif preset in ("full", "all"):
        pack = "full"
    elif not pack:
        # Fall back to agent's own template_type pack
        pack = skill_pack_for_template(getattr(target, "template_type", None)) or ""

    if pack:
        to_enable = skills_for_pack(pack, get_skill_catalog(), role=role)
    else:
        to_enable = skills_for_template(
            getattr(target, "template_type", None), get_skill_catalog(), role=role
        )

    ensure_agent_skills(db, target)
    set_enabled_skills(db, target, list(to_enable)[:240])

async def _skill_spawn_specialist(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    domain = (args.get("domain") or "specialist").strip()
    name = (args.get("name") or f"{domain.title()} Specialist").strip()
    parent_id = args.get("parent_id") or (agent.id if not is_orchestrator(agent) else None)
    extra = args.get("skills") or []

    from ..agent_scaffold import scaffold_agent, map_model

    child = models.Agent(
        user_id=user.id,
        company_id=agent.company_id,
        project_id=agent.project_id,
        parent_id=parent_id,
        hierarchy_role="specialist",
        is_lead=False,
        name=name,
        template_type=domain.lower()[:40],
        personality=f"World-class specialist in {domain}. Created by {agent.name}.",
        model=map_model(agent.model),
        status="active",
        idle_mode="never_idle",
        permission_level="operator",
        config=json.dumps({"autonomy": "full", "domain": domain, "spawned_by": agent.id}),
        escalate_when="on_failure",
        escalate_to="parent",
    )
    db.add(child)
    db.flush()
    # Full free role pack + domain pack from template_type (domain)
    scaffold_agent(db, child, full_skills=True)

    from ..agent_scaffold import ensure_agent_skills
    ensure_agent_skills(db, child)
    wanted = set(skills_for_template(child.template_type, get_skill_catalog(), role="specialist"))
    for sid in (extra or []):
        if sid in {s["id"] for s in get_skill_catalog()}:
            wanted.add(sid)
    set_enabled_skills(db, child, list(wanted))
    db.commit()
    db.refresh(child)
    return {"ok": True, "agent": {"id": child.id, "name": child.name}, "message": f"Spawned specialist {name}"}

async def _skill_clone_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        src_id = int(args.get("source_agent_id"))
    except Exception:
        return {"ok": False, "error": "source_agent_id required"}
    src = db.get(models.Agent, src_id)
    if not src or src.user_id != user.id:
        return {"ok": False, "error": "Source agent not found"}

    new_name = (args.get("new_name") or (src.name + " (clone)"))[:120]
    parent = args.get("parent_id") or src.parent_id

    from ..agent_scaffold import scaffold_agent, map_model
    clone = models.Agent(
        user_id=user.id,
        company_id=src.company_id,
        project_id=src.project_id,
        parent_id=parent,
        hierarchy_role=src.hierarchy_role,
        is_lead=src.is_lead,
        name=new_name,
        template_type=src.template_type,
        personality=src.personality,
        model=map_model(src.model),
        status="active",
        idle_mode=src.idle_mode or "never_idle",
        permission_level=src.permission_level,
        config=src.config,
        escalate_when=src.escalate_when or "on_failure",
        escalate_to=src.escalate_to or "parent",
        escalate_reason=getattr(src, "escalate_reason", ""),
    )
    db.add(clone)
    db.flush()
    scaffold_agent(db, clone, full_skills=True)

    src_enabled = get_enabled_skill_ids(src, db)
    if src_enabled:
        set_enabled_skills(db, clone, list(src_enabled))
    db.commit()
    db.refresh(clone)
    return {"ok": True, "cloned": {"id": clone.id, "name": clone.name, "from": src.id}}

async def _skill_enable_skills_on(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        target_id = int(args.get("target_agent_id"))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    tgt = db.get(models.Agent, target_id)
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Target agent not found"}

    skill_ids = args.get("skill_ids") or []
    if isinstance(skill_ids, str):
        skill_ids = [s.strip() for s in skill_ids.split(",") if s.strip()]
    valid = {s["id"] for s in get_skill_catalog()}
    clean = [s for s in skill_ids if s in valid]
    if not clean:
        return {"ok": False, "error": "No valid skill_ids provided"}

    existing = get_enabled_skill_ids(tgt, db)
    new_set = list(set(existing) | set(clean))
    set_enabled_skills(db, tgt, new_set)
    await emit_ops(user.id, kind="skill", status="done",
                   title=f"Enabled {len(clean)} skills on {tgt.name}", agent_id=agent.id, db=db)
    return {"ok": True, "target": tgt.id, "enabled_now": len(new_set), "added": len(clean)}

async def _skill_bulk_enable_skills(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    ids = args.get("agent_ids") or []
    if isinstance(ids, str):
        ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    preset = args.get("preset") or "full"
    extra = args.get("extra_skills") or []

    results = []
    for aid in ids:
        try:
            a = db.get(models.Agent, int(aid))
            if a and a.user_id == user.id:
                await _apply_preset_skills(db, a, preset)
                if extra:
                    cur = get_enabled_skill_ids(a, db)
                    add = [x for x in extra if x in {s["id"] for s in get_skill_catalog()}]
                    set_enabled_skills(db, a, list(set(cur) | set(add)))
                results.append({"id": a.id, "name": a.name, "ok": True})
        except Exception as e:
            results.append({"id": aid, "ok": False, "error": str(e)})
    db.commit()
    return {"ok": True, "updated": len([r for r in results if r.get("ok")]), "results": results}

async def _skill_configure_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Target not found"}

    for field in ("model", "personality", "idle_mode", "permission_level", "escalate_when"):
        if args.get(field) is not None:
            setattr(tgt, field, args[field])
    db.commit()
    return {"ok": True, "configured": tgt.id, "name": tgt.name}

async def _skill_promote_to_lead(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("agent_id")))
    except Exception:
        return {"ok": False, "error": "agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "Agent not found"}

    tgt.hierarchy_role = "lead"
    tgt.is_lead = True
    tgt.permission_level = "lead"

    report_ids = args.get("report_agent_ids") or []
    wired = 0
    for rid in report_ids:
        try:
            r = db.get(models.Agent, int(rid))
            if r and r.user_id == user.id:
                r.parent_id = tgt.id
                wired += 1
        except Exception:
            pass
    db.commit()
    return {"ok": True, "promoted": tgt.id, "reports_wired": wired}

async def _skill_pause_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    tgt.status = "paused"
    tgt.idle_mode = "allow_idle"
    db.commit()
    return {"ok": True, "paused": tgt.id}

async def _skill_resume_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    tgt.status = "active"
    tgt.idle_mode = "never_idle"
    db.commit()
    return {"ok": True, "resumed": tgt.id}

async def _skill_delete_agent(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        tgt = db.get(models.Agent, int(args.get("target_agent_id")))
    except Exception:
        return {"ok": False, "error": "target_agent_id required"}
    if not tgt or tgt.user_id != user.id:
        return {"ok": False, "error": "not found"}
    if is_orchestrator(tgt):
        return {"ok": False, "error": "Cannot delete the orchestrator"}
    db.delete(tgt)
    db.commit()
    return {"ok": True, "deleted": int(args.get("target_agent_id"))}

async def _skill_list_team(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    q = db.query(models.Agent).filter_by(user_id=user.id)
    if not is_orchestrator(agent):
        q = q.filter(models.Agent.parent_id == agent.id)
    role_filter = args.get("role_filter")
    if role_filter:
        q = q.filter_by(hierarchy_role=role_filter)
    rows = q.order_by(models.Agent.id).limit(200).all()
    out = []
    for a in rows:
        sk = list(get_enabled_skill_ids(a, db)) if args.get("include_skills") else None
        out.append({
            "id": a.id, "name": a.name, "role": a.hierarchy_role,
            "status": a.status, "idle": a.idle_mode, "skills": sk
        })
    return {"ok": True, "count": len(out), "team": out}


__all__ = [
    '_skill_spawn',
    '_skill_message',
    '_skill_assign_human',
    '_skill_save_memory',
    '_skill_save_training',
    '_skill_execute_goal',
    '_skill_create_task',
    '_skill_announce_plan',
    '_skill_notify_human',
    '_skill_status_update',
    '_skill_escalate_to_human',
    '_skill_set_agent_status',
    '_skill_create_reminder',
    '_skill_spawn_team',
    '_apply_preset_skills',
    '_skill_spawn_specialist',
    '_skill_clone_agent',
    '_skill_enable_skills_on',
    '_skill_bulk_enable_skills',
    '_skill_configure_agent',
    '_skill_promote_to_lead',
    '_skill_pause_agent',
    '_skill_resume_agent',
    '_skill_delete_agent',
    '_skill_list_team',
]
