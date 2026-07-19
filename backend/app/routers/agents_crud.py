"""List/create/get/patch/delete agent endpoints (+ pause/resume/duplicate/activity)."""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user, ensure_credits
from ..plans import plan_limits
from ..agent_serialize import agent_out, agents_out_list, task_dict
from ..agent_roles import (
    agent_sort_key,
    find_orchestrator,
    resolve_create_role,
    promote_orchestrator,
)
from .agents_common import (
    _get_owned,
    _apply_hierarchy,
    log_activity,
    AgentIn,
    AgentUpdate,
)

log = logging.getLogger("app.agents")

router = APIRouter()


@router.get("/")
def list_agents(
    company_id: int | None = None,
    project_id: int | None = None,
    lean: bool = True,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List agents. lean=true (default) skips per-agent activity/integrations for speed."""
    q = db.query(models.Agent).filter_by(user_id=user.id)
    if company_id is not None:
        q = q.filter_by(company_id=company_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    agents = q.all()
    agents.sort(key=agent_sort_key)
    return agents_out_list(db, agents, lean=lean)

@router.get("/{agent_id}")
def get_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    out = agent_out(a, db, activity_limit=40, include_team=True)
    out["recent_tasks"] = [
        task_dict(t, db)
        for t in db.query(models.Task).filter_by(agent_id=a.id).order_by(models.Task.id.desc()).limit(30).all()
    ]
    # Team tasks for lead view
    report_ids = [r["id"] for r in out.get("reports") or []]
    if report_ids:
        team_tasks = (
            db.query(models.Task)
            .filter(models.Task.agent_id.in_(report_ids))
            .order_by(models.Task.id.desc())
            .limit(40)
            .all()
        )
        out["team_tasks"] = [task_dict(t, db) for t in team_tasks]
    else:
        out["team_tasks"] = []
    conv = (
        db.query(models.Conversation)
        .filter_by(user_id=user.id, agent_id=a.id)
        .order_by(models.Conversation.id.desc())
        .first()
    )
    out["chat"] = None
    if conv:
        # Cap history so mobile chat pages open quickly (full thread still used server-side for reply context)
        msgs = (
            db.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.id.desc())
            .limit(40)
            .all()
        )
        msgs = list(reversed(msgs))
        out["chat"] = {
            "conversation_id": conv.id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": (m.content or "")[:8000],
                    "created_at": m.created_at,
                }
                for m in msgs
            ],
        }
    return out


@router.get("/{agent_id}/activity")
def agent_activity(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    logs = (
        db.query(models.ActivityLog)
        .filter_by(agent_id=a.id)
        .order_by(models.ActivityLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": l.id, "type": l.type, "message": l.message, "created_at": l.created_at}
        for l in logs
    ]


@router.post("/{agent_id}/duplicate")
async def duplicate_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents.")
    clone = models.Agent(
        user_id=user.id,
        name=f"{a.name} (copy)",
        template_type=a.template_type,
        personality=a.personality,
        model=a.model,
        idle_mode=a.idle_mode,
        status="paused",
        config=a.config,
        company_id=a.company_id,
        project_id=a.project_id,
        parent_id=a.parent_id,
        is_lead=False,
        hierarchy_role="member",
        permission_level=getattr(a, "permission_level", None) or "operator",
        escalate_when=getattr(a, "escalate_when", None) or "on_failure",
        escalate_reason=getattr(a, "escalate_reason", None) or "",
        escalate_to=getattr(a, "escalate_to", None) or "parent",
        escalate_human_id=getattr(a, "escalate_human_id", None),
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    await log_activity(clone.id, user.id, "info", f"Cloned from agent #{a.id}")
    return agent_out(clone, db)

@router.post("/")
async def create_agent(data: AgentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role != "admin" and (not user.subscription_active or user.plan in (None, "", "none")):
        raise HTTPException(402, "Choose a subscription plan to create agents")
    ensure_credits(db, user.id)
    count = db.query(models.Agent).filter_by(user_id=user.id).count()
    max_agents = int(plan_limits(user.plan).get("agents") or 0)
    if user.role != "admin" and count >= max_agents:
        raise HTTPException(400, f"Your plan allows up to {max_agents} agents. Upgrade on Billing.")

    role, is_lead, make_orch = resolve_create_role(
        hierarchy_role=data.hierarchy_role,
        template_type=data.template_type,
        is_lead=data.is_lead,
    )
    parent_id = data.parent_id
    if make_orch:
        parent_id = None
    if parent_id:
        _get_owned(parent_id, user, db)
    # Default non-orchestrator agents without parent → hang under main orchestrator
    if parent_id is None and not make_orch:
        orch = find_orchestrator(db, user.id)
        if orch:
            parent_id = orch.id

    company_id = data.company_id
    project_id = data.project_id
    if project_id:
        p = db.get(models.Project, project_id)
        if not p or (p.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid project")
        if company_id is None:
            company_id = p.company_id
        elif company_id != p.company_id:
            raise HTTPException(400, "project_id does not belong to company_id")
    if company_id:
        c = db.get(models.Company, company_id)
        if not c or (c.owner_user_id != user.id and user.role != "admin"):
            raise HTTPException(400, "Invalid company")

    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    from ..agent_scaffold import apply_create_defaults, repair_agent, map_model
    defaults = apply_create_defaults(data.model, data.template_type, role)
    cfg = dict(data.config or {})
    cfg.setdefault("autonomy", "full")
    a = models.Agent(
        user_id=user.id, name=data.name, template_type=data.template_type,
        personality=data.personality,
        model=map_model(data.model or defaults["model"]),
        idle_mode="never_idle",
        config=json.dumps(cfg),
        is_lead=is_lead,
        hierarchy_role=role,
        parent_id=parent_id,
        permission_level=normalize_permission(data.permission_level or defaults["permission_level"]),
        escalate_when=normalize_escalate_when(data.escalate_when or "on_failure"),
        escalate_reason=(data.escalate_reason or "").strip(),
        escalate_to=normalize_escalate_to(data.escalate_to or "parent"),
        escalate_human_id=data.escalate_human_id,
        status="active",
        company_id=company_id,
        project_id=project_id,
    )
    db.add(a)
    db.flush()
    if make_orch:
        promote_orchestrator(db, a)
    repair_agent(db, a, force_never_idle=True, expand_skills=True)
    db.commit()
    db.refresh(a)
    role_msg = " as Main Orchestrator" if make_orch else (" as Lead" if is_lead else (f" under #{parent_id}" if parent_id else ""))
    await log_activity(a.id, user.id, "info", f"Agent '{a.name}' created{role_msg} — full autonomy online")
    # Optional: auto-publish skill listing to AgentBay marketplace
    try:
        from ..agentbay_bridge import maybe_auto_publish
        await maybe_auto_publish(a, db)
        db.refresh(a)
    except Exception:
        pass
    return agent_out(a, db, include_team=True)

@router.patch("/{agent_id}")
def update_agent(agent_id: int, data: AgentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..permissions import normalize_permission, normalize_escalate_when, normalize_escalate_to
    a = _get_owned(agent_id, user, db)
    for field in ["name", "personality", "model", "idle_mode"]:
        v = getattr(data, field)
        if v is not None:
            setattr(a, field, v)
    if data.permission_level is not None:
        a.permission_level = normalize_permission(data.permission_level)
    if data.escalate_when is not None:
        a.escalate_when = normalize_escalate_when(data.escalate_when)
    if data.escalate_reason is not None:
        a.escalate_reason = (data.escalate_reason or "").strip()
    if data.escalate_to is not None:
        a.escalate_to = normalize_escalate_to(data.escalate_to)
    if data.escalate_human_id is not None:
        a.escalate_human_id = data.escalate_human_id or None
    if data.config is not None:
        a.config = json.dumps(data.config)
    if data.parent_id is not None or data.is_lead is not None or data.hierarchy_role is not None:
        _apply_hierarchy(
            a, db, user,
            parent_id=data.parent_id if data.parent_id is not None else None,
            clear_parent=data.parent_id == 0,
            is_lead=data.is_lead,
            hierarchy_role=data.hierarchy_role,
        )
    if data.company_id is not None or data.project_id is not None:
        company_id = data.company_id if data.company_id is not None else a.company_id
        project_id = data.project_id if data.project_id is not None else a.project_id
        # Allow clearing with 0
        if data.company_id == 0:
            company_id = None
        if data.project_id == 0:
            project_id = None
        if project_id:
            p = db.get(models.Project, project_id)
            if not p or (p.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid project")
            if company_id is None:
                company_id = p.company_id
            elif company_id != p.company_id:
                raise HTTPException(400, "project_id does not belong to company_id")
        if company_id:
            c = db.get(models.Company, company_id)
            if not c or (c.owner_user_id != user.id and user.role != "admin"):
                raise HTTPException(400, "Invalid company")
        if data.company_id is not None:
            a.company_id = None if data.company_id == 0 else company_id
        if data.project_id is not None:
            a.project_id = None if data.project_id == 0 else project_id
        if data.company_id is not None and data.project_id is None and a.project_id:
            # Keep project if still under company; else clear
            p = db.get(models.Project, a.project_id)
            if not p or p.company_id != a.company_id:
                a.project_id = None
    db.commit()
    return agent_out(a, db, include_team=True)

@router.post("/{agent_id}/pause")
async def pause(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "paused"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent paused")
    return agent_out(a, db)

@router.post("/{agent_id}/resume")
async def resume(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    a.status = "active"; db.commit()
    await log_activity(a.id, a.user_id, "info", "Agent resumed")
    return agent_out(a, db)

@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """
    Delete an agent and clear every FK that points at it.

    Uses SAVEPOINTs (begin_nested) for each optional step so a missing table
    never rolls back earlier cleanup — that was why delete used to fail.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    a = _get_owned(agent_id, user, db)
    aid = int(a.id)
    parent_id = a.parent_id
    uid = int(user.id)

    def _step(sql: str, params=None) -> bool:
        """Run one SQL step inside a savepoint. Returns False if skipped."""
        params = params or {"aid": aid}
        try:
            with db.begin_nested():
                db.execute(text(sql), params)
            return True
        except SQLAlchemyError as ex:
            # savepoint already rolled back; outer txn stays open
            msg = str(ex).lower()
            soft = any(
                s in msg
                for s in (
                    "no such table",
                    "undefinedtable",
                    "undefinedcolumn",
                    "no such column",
                    "unknown column",
                    "does not exist",  # Postgres: relation/column does not exist
                )
            )
            # Do NOT treat FK violations as soft — those must surface to last-resort path
            if not soft:
                log.warning("delete_agent step error: %s — %s", sql[:100], ex)
            return False
        except Exception as ex:
            log.warning("delete_agent unexpected: %s — %s", sql[:100], ex)
            return False

    # 1) Re-parent children so hierarchy stays valid
    if parent_id is not None:
        _step(
            "UPDATE agents SET parent_id = :pid WHERE parent_id = :aid",
            {"pid": parent_id, "aid": aid},
        )
    else:
        _step("UPDATE agents SET parent_id = NULL WHERE parent_id = :aid")

    # 2) Chat history for this agent
    try:
        with db.begin_nested():
            rows = db.execute(
                text("SELECT id FROM conversations WHERE agent_id = :aid"),
                {"aid": aid},
            ).fetchall()
            for (cid,) in rows:
                db.execute(
                    text("DELETE FROM messages WHERE conversation_id = :cid"),
                    {"cid": int(cid)},
                )
            db.execute(
                text("DELETE FROM conversations WHERE agent_id = :aid"),
                {"aid": aid},
            )
    except Exception:
        _step("UPDATE conversations SET agent_id = NULL WHERE agent_id = :aid")

    # 3) Wallet ledger then wallet
    try:
        with db.begin_nested():
            wids = db.execute(
                text("SELECT id FROM agent_wallets WHERE agent_id = :aid"),
                {"aid": aid},
            ).fetchall()
            for (wid,) in wids:
                db.execute(
                    text("DELETE FROM agent_wallet_txs WHERE wallet_id = :wid"),
                    {"wid": int(wid)},
                )
            db.execute(
                text("DELETE FROM agent_wallets WHERE agent_id = :aid"),
                {"aid": aid},
            )
    except Exception:
        pass

    # 4) Hard-delete agent-owned rows
    for sql in (
        "DELETE FROM activity_logs WHERE agent_id = :aid",
        "DELETE FROM agent_integrations WHERE agent_id = :aid",
        "DELETE FROM agent_knowledge_access WHERE agent_id = :aid",
        "DELETE FROM agent_memories WHERE agent_id = :aid",
        "DELETE FROM agent_skill_states WHERE agent_id = :aid",
        "DELETE FROM agent_programs WHERE agent_id = :aid",
        "DELETE FROM agent_messages WHERE from_agent_id = :aid",
        "DELETE FROM agent_messages WHERE to_agent_id = :aid",
    ):
        _step(sql)

    # 5) Null optional FKs (preserve CRM / meeting / task history)
    for sql in (
        "UPDATE tasks SET agent_id = NULL WHERE agent_id = :aid",
        "UPDATE tasks SET assignee_type = CASE WHEN human_id IS NOT NULL THEN 'human' ELSE 'unassigned' END "
        "WHERE agent_id IS NULL AND assignee_type = 'agent'",
        "UPDATE live_ops_events SET agent_id = NULL WHERE agent_id = :aid",
        "UPDATE escalation_logs SET from_agent_id = NULL WHERE from_agent_id = :aid",
        "UPDATE escalation_logs SET to_agent_id = NULL WHERE to_agent_id = :aid",
        "UPDATE human_messages SET sender_agent_id = NULL WHERE sender_agent_id = :aid",
        "UPDATE customers SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
        "UPDATE deals SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
        "UPDATE diary_entries SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
        "UPDATE customer_activities SET agent_id = NULL WHERE agent_id = :aid",
        "UPDATE meeting_rooms SET chair_agent_id = NULL WHERE chair_agent_id = :aid",
        "UPDATE meeting_participants SET agent_id = NULL WHERE agent_id = :aid",
        "UPDATE meeting_messages SET sender_agent_id = NULL WHERE sender_agent_id = :aid",
        "UPDATE git_repo_connections SET agent_id = NULL WHERE agent_id = :aid",
        "UPDATE conversations SET agent_id = NULL WHERE agent_id = :aid",
    ):
        _step(sql)

    # 6) Delete agent row (scoped to owner)
    try:
        with db.begin_nested():
            result = db.execute(
                text("DELETE FROM agents WHERE id = :aid AND user_id = :uid"),
                {"aid": aid, "uid": uid},
            )
            # SQLAlchemy 1.4/2.0: rowcount may be -1 on some drivers
            if getattr(result, "rowcount", None) == 0:
                raise HTTPException(404, "Agent not found")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        # Last resort: SQLite pragma off, or re-run nulls then delete
        try:
            dialect = ""
            try:
                dialect = (db.get_bind().dialect.name if hasattr(db, "get_bind") else db.bind.dialect.name) or ""
            except Exception:
                try:
                    dialect = db.bind.dialect.name
                except Exception:
                    dialect = ""
            if dialect == "sqlite":
                db.execute(text("PRAGMA foreign_keys=OFF"))
            for sql in (
                "UPDATE agents SET parent_id = NULL WHERE parent_id = :aid",
                "DELETE FROM activity_logs WHERE agent_id = :aid",
                "DELETE FROM agent_integrations WHERE agent_id = :aid",
                "DELETE FROM agent_knowledge_access WHERE agent_id = :aid",
                "DELETE FROM agent_memories WHERE agent_id = :aid",
                "DELETE FROM agent_skill_states WHERE agent_id = :aid",
                "DELETE FROM agent_programs WHERE agent_id = :aid",
                "DELETE FROM agent_messages WHERE from_agent_id = :aid OR to_agent_id = :aid",
                "UPDATE tasks SET agent_id = NULL WHERE agent_id = :aid",
                "UPDATE live_ops_events SET agent_id = NULL WHERE agent_id = :aid",
                "UPDATE escalation_logs SET from_agent_id = NULL WHERE from_agent_id = :aid",
                "UPDATE escalation_logs SET to_agent_id = NULL WHERE to_agent_id = :aid",
                "UPDATE human_messages SET sender_agent_id = NULL WHERE sender_agent_id = :aid",
                "UPDATE customers SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
                "UPDATE deals SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
                "UPDATE diary_entries SET owner_agent_id = NULL WHERE owner_agent_id = :aid",
                "UPDATE customer_activities SET agent_id = NULL WHERE agent_id = :aid",
                "UPDATE meeting_rooms SET chair_agent_id = NULL WHERE chair_agent_id = :aid",
                "UPDATE meeting_participants SET agent_id = NULL WHERE agent_id = :aid",
                "UPDATE meeting_messages SET sender_agent_id = NULL WHERE sender_agent_id = :aid",
                "UPDATE git_repo_connections SET agent_id = NULL WHERE agent_id = :aid",
            ):
                try:
                    db.execute(text(sql), {"aid": aid})
                except Exception:
                    pass
            db.execute(
                text("DELETE FROM agents WHERE id = :aid AND user_id = :uid"),
                {"aid": aid, "uid": uid},
            )
            if dialect == "sqlite":
                db.execute(text("PRAGMA foreign_keys=ON"))
            db.commit()
        except Exception as e2:
            db.rollback()
            log.exception("delete_agent failed for agent %s", aid)
            raise HTTPException(
                400,
                f"Could not delete agent — linked records still reference it. "
                f"({type(e2).__name__}: {e2})",
            ) from e2

    return {"ok": True, "deleted_id": aid}

