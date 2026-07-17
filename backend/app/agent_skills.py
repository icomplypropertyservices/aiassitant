"""
Agent skills: spawn agents, talk to agents, use connected apps, assign humans,
save memory, promote data into training, announce plans.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .agent_roles import is_orchestrator, normalize_role
from .integrations_service import secrets_from_row, meta_from_row, integrations_context_for_agent
from .live_ops import emit_ops

# ── Catalog ──────────────────────────────────────────────────────────────

SKILL_CATALOG: list[dict] = [
    {
        "id": "spawn_agent",
        "name": "Spawn agent",
        "description": "Create a new team agent under you (or as orchestrator under any lead).",
        "args": ["name", "template_type", "personality", "hierarchy_role", "parent_id"],
        "roles": ["orchestrator", "lead"],
    },
    {
        "id": "message_agent",
        "name": "Message agent",
        "description": "Send a message to another agent and optionally get their reply.",
        "args": ["to_agent_id", "message", "expect_reply"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "use_app",
        "name": "Use connected app",
        "description": "Call a connected integration (Slack, Gmail, Shopify, socials, etc.).",
        "args": ["app_id", "action", "payload"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "assign_human",
        "name": "Assign work to human",
        "description": "Allocate a task to a human teammate.",
        "args": ["human_id", "title", "description", "priority"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "save_memory",
        "name": "Save agent data",
        "description": "Persist a note/fact/deliverable in this agent's data vault.",
        "args": ["title", "content", "kind", "tags"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "save_training",
        "name": "Save to training",
        "description": "Promote text into the training library and attach to this agent.",
        "args": ["title", "content", "tags", "folder_id"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
    {
        "id": "create_task",
        "name": "Create task",
        "description": "Create a task for an agent or human.",
        "args": ["title", "description", "agent_id", "human_id", "priority"],
        "roles": ["orchestrator", "lead", "member"],
    },
    {
        "id": "announce_plan",
        "name": "Announce plan",
        "description": "Publish a multi-step plan to the live ops banner.",
        "args": ["title", "steps"],
        "roles": ["orchestrator", "lead", "member", "specialist"],
    },
]

DEFAULT_ENABLED = [s["id"] for s in SKILL_CATALOG]

_SKILL_BLOCK = re.compile(
    r"```skill\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def list_skills_for_agent(agent: models.Agent, db: Session) -> list[dict]:
    role = normalize_role(agent)
    enabled = enabled_skill_ids(agent, db)
    out = []
    for s in SKILL_CATALOG:
        allowed_roles = s.get("roles") or []
        role_ok = role in allowed_roles or is_orchestrator(agent)
        out.append({
            **s,
            "enabled": s["id"] in enabled and role_ok,
            "role_allowed": role_ok,
        })
    return out


def enabled_skill_ids(agent: models.Agent, db: Session) -> set[str]:
    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    if not row or not (row.enabled_json or "").strip():
        return set(DEFAULT_ENABLED)
    try:
        data = json.loads(row.enabled_json)
        if isinstance(data, list) and data:
            return set(str(x) for x in data)
    except Exception:
        pass
    return set(DEFAULT_ENABLED)


def set_enabled_skills(db: Session, agent: models.Agent, skill_ids: list[str]) -> list[str]:
    valid = {s["id"] for s in SKILL_CATALOG}
    clean = [s for s in skill_ids if s in valid]
    row = db.query(models.AgentSkillState).filter_by(agent_id=agent.id).first()
    if not row:
        row = models.AgentSkillState(agent_id=agent.id)
        db.add(row)
    row.enabled_json = json.dumps(clean)
    row.updated_at = datetime.utcnow()
    db.commit()
    return clean


def skills_prompt_block(agent: models.Agent, db: Session) -> str:
    skills = [s for s in list_skills_for_agent(agent, db) if s.get("enabled")]
    if not skills:
        return ""
    lines = [
        "You have SKILLS. When you need to act (not just answer), emit one or more blocks:",
        '```skill',
        '{"skill":"<id>","args":{...}}',
        "```",
        "Available skills:",
    ]
    for s in skills:
        lines.append(f"- {s['id']}: {s['description']} args={s['args']}")
    lines.append(
        "Also available apps context:\n"
        + (integrations_context_for_agent(db, agent.id) or "(no apps linked)")
    )
    humans = db.query(models.Human).filter_by(owner_user_id=agent.user_id, status="active").limit(20).all()
    if humans:
        lines.append(
            "Humans you may assign: "
            + ", ".join(f"{h.name}(id={h.id}, {h.role_title or 'teammate'})" for h in humans)
        )
    peers = (
        db.query(models.Agent)
        .filter(models.Agent.user_id == agent.user_id, models.Agent.id != agent.id)
        .limit(30)
        .all()
    )
    if peers:
        lines.append(
            "Other agents: "
            + ", ".join(f"{p.name}(id={p.id},{p.hierarchy_role})" for p in peers)
        )
    return "\n".join(lines)


def extract_skill_calls(text: str) -> list[dict]:
    calls = []
    for m in _SKILL_BLOCK.finditer(text or ""):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj.get("skill"):
                calls.append(obj)
        except Exception:
            continue
    # Also accept single-line JSON skill directives
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{") and '"skill"' in line:
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("skill") and obj not in calls:
                    calls.append(obj)
            except Exception:
                pass
    return calls


def strip_skill_blocks(text: str) -> str:
    cleaned = _SKILL_BLOCK.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


async def execute_skill(
    db: Session,
    agent: models.Agent,
    user: models.User,
    skill_id: str,
    args: dict | None = None,
) -> dict[str, Any]:
    args = args or {}
    enabled = enabled_skill_ids(agent, db)
    if skill_id not in enabled and not is_orchestrator(agent):
        return {"ok": False, "error": f"Skill '{skill_id}' is disabled for this agent"}

    meta = next((s for s in SKILL_CATALOG if s["id"] == skill_id), None)
    if not meta:
        return {"ok": False, "error": f"Unknown skill '{skill_id}'"}

    role = normalize_role(agent)
    if role not in (meta.get("roles") or []) and not is_orchestrator(agent):
        return {"ok": False, "error": f"Role '{role}' cannot use skill '{skill_id}'"}

    await emit_ops(
        user.id,
        kind="skill",
        status="running",
        title=f"{agent.name} → {meta['name']}",
        detail=json.dumps(args)[:400],
        agent_id=agent.id,
        payload={"skill": skill_id, "args": args},
        db=db,
    )

    try:
        if skill_id == "spawn_agent":
            result = await _skill_spawn(db, agent, user, args)
        elif skill_id == "message_agent":
            result = await _skill_message(db, agent, user, args)
        elif skill_id == "use_app":
            result = await _skill_use_app(db, agent, user, args)
        elif skill_id == "assign_human":
            result = await _skill_assign_human(db, agent, user, args)
        elif skill_id == "save_memory":
            result = await _skill_save_memory(db, agent, user, args)
        elif skill_id == "save_training":
            result = await _skill_save_training(db, agent, user, args)
        elif skill_id == "create_task":
            result = await _skill_create_task(db, agent, user, args)
        elif skill_id == "announce_plan":
            result = await _skill_announce_plan(db, agent, user, args)
        else:
            result = {"ok": False, "error": "not implemented"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    await emit_ops(
        user.id,
        kind="skill",
        status="done" if result.get("ok") else "failed",
        title=f"{agent.name} → {meta['name']}",
        detail=result.get("message") or result.get("error") or "",
        agent_id=agent.id,
        payload={"skill": skill_id, "result": result},
        db=db,
    )
    return result


async def run_skills_from_text(
    db: Session,
    agent: models.Agent,
    user: models.User,
    text: str,
) -> tuple[str, list[dict]]:
    """Parse skill blocks, execute them, return cleaned reply + results."""
    calls = extract_skill_calls(text)
    results = []
    for call in calls:
        sid = str(call.get("skill") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {
            k: v for k, v in call.items() if k != "skill"
        }
        r = await execute_skill(db, agent, user, sid, args)
        results.append({"skill": sid, **r})
    return strip_skill_blocks(text), results


# ── Individual skills ────────────────────────────────────────────────────

async def _skill_spawn(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    name = (args.get("name") or "New agent").strip()[:120]
    template = (args.get("template_type") or "custom").strip()[:80]
    personality = (args.get("personality") or "Professional, helpful, concise.").strip()
    hrole = (args.get("hierarchy_role") or "member").strip()
    if hrole not in ("lead", "member", "specialist"):
        hrole = "member"
    parent_id = args.get("parent_id")
    if parent_id is None:
        parent_id = agent.id if not is_orchestrator(agent) else None
    else:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            parent_id = agent.id

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
        model=agent.model or "vps-fast",
        status="active",
        idle_mode="allow_idle",
        config="{}",
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return {
        "ok": True,
        "message": f"Spawned agent {child.name} (id={child.id})",
        "agent": {"id": child.id, "name": child.name, "hierarchy_role": child.hierarchy_role},
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
    msg = models.AgentMessage(
        user_id=user.id,
        from_agent_id=agent.id,
        to_agent_id=target.id,
        thread_key=thread_key,
        content=content,
        status="open",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    reply_text = None
    if args.get("expect_reply", True):
        # Lightweight auto-reply from target using their personality (no nested skill loop)
        from .llm import complete
        from .user_keys import credentials_for_user
        from .agent_prompts import build_agent_system_prompt

        system = build_agent_system_prompt(db, target)
        prompt = (
            f"{system}\n\nYou received an internal message from teammate agent "
            f"{agent.name} (id={agent.id}):\n\n{content}\n\n"
            "Reply helpfully in 1-3 short paragraphs. Do not emit skill blocks."
        )
        creds = credentials_for_user(db, user.id)
        try:
            reply_text = await complete(
                [{"role": "user", "content": prompt}],
                target.model or "vps-fast",
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
                    status="acknowledged",
                )
                db.add(reply)
                db.commit()
        except Exception as e:
            reply_text = f"(auto-reply failed: {e})"

    return {
        "ok": True,
        "message": f"Messaged {target.name}",
        "thread_key": thread_key,
        "message_id": msg.id,
        "reply": reply_text,
    }


async def _skill_use_app(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .integration_actions import run_app_action

    app_id = (args.get("app_id") or "").strip().lower()
    action = (args.get("action") or "status").strip().lower()
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    if not app_id:
        return {"ok": False, "error": "app_id required"}

    # Must be allocated to this agent
    links = db.query(models.AgentIntegration).filter_by(agent_id=agent.id).all()
    conn = None
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c and c.app_id == app_id and c.user_id == user.id:
            conn = c
            break
    if not conn:
        # Fall back to any connected app of that type for orchestrators
        if is_orchestrator(agent):
            conn = (
                db.query(models.IntegrationConnection)
                .filter_by(user_id=user.id, app_id=app_id, status="connected")
                .order_by(models.IntegrationConnection.id.desc())
                .first()
            )
    if not conn:
        return {"ok": False, "error": f"No connected '{app_id}' app allocated to this agent"}

    result = await run_app_action(conn, action, payload)
    return result


async def _skill_assign_human(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        human_id = int(args.get("human_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "human_id required"}
    human = db.get(models.Human, human_id)
    if not human or human.owner_user_id != user.id:
        return {"ok": False, "error": "Human not found"}
    title = (args.get("title") or args.get("description") or "Work item")[:120]
    description = (args.get("description") or title).strip()
    priority = args.get("priority") or "medium"
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
        labels="human,allocated",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
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
        "message": f"Assigned to {human.name}",
        "task_id": t.id,
        "human": {"id": human.id, "name": human.name},
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


async def _skill_create_task(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or args.get("description") or "Task")[:120]
    description = (args.get("description") or title).strip()
    agent_id = args.get("agent_id") or agent.id
    human_id = args.get("human_id")
    try:
        agent_id = int(agent_id) if agent_id is not None else agent.id
    except (TypeError, ValueError):
        agent_id = agent.id
    try:
        human_id = int(human_id) if human_id is not None else None
    except (TypeError, ValueError):
        human_id = None

    target = db.get(models.Agent, agent_id)
    if not target or target.user_id != user.id:
        return {"ok": False, "error": "agent not found"}

    t = models.Task(
        user_id=user.id,
        agent_id=target.id,
        human_id=human_id,
        assignee_type="human" if human_id else "agent",
        company_id=target.company_id,
        project_id=target.project_id,
        title=title,
        description=description,
        status="todo",
        priority=args.get("priority") or "medium",
        labels="skill-created",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"ok": True, "message": "Task created", "task_id": t.id}


async def _skill_announce_plan(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    title = (args.get("title") or "Plan")[:200]
    steps = args.get("steps") or []
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("\n") if s.strip()]
    if not isinstance(steps, list):
        steps = []
    plan_id = f"plan-{uuid.uuid4().hex[:10]}"
    await emit_ops(
        user.id,
        kind="plan",
        status="running",
        title=title,
        detail=f"{len(steps)} steps",
        agent_id=agent.id,
        plan_id=plan_id,
        payload={"steps": steps},
        db=db,
    )
    for i, step in enumerate(steps[:20], 1):
        text = step if isinstance(step, str) else json.dumps(step)
        await emit_ops(
            user.id,
            kind="step",
            status="queued",
            title=f"Step {i}",
            detail=text[:500],
            agent_id=agent.id,
            plan_id=plan_id,
            db=db,
        )
    return {"ok": True, "message": f"Plan announced ({len(steps)} steps)", "plan_id": plan_id}
