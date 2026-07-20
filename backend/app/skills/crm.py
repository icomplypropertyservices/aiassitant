"""CRM / deal / pipeline / diary skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops


async def _skill_list_customers(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    q = (args.get("q") or "").strip()
    status = args.get("status")
    tag = args.get("tag")
    lead_status = (args.get("lead_status") or "").strip() or None
    try:
        limit = min(100, int(args.get("limit") or 25))
    except Exception:
        limit = 25
    rows, _total = crm_service.list_customers(
        db, user, q=q or None, status=status, tag=tag, lead_status=lead_status, limit=limit,
    )
    return {
        "ok": True,
        "count": len(rows),
        "customers": [crm_service.customer_out(c, db, light=True) for c in rows],
    }

async def _skill_get_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        return {"ok": False, "error": "customer not found (provide customer_id or email)"}
    deals = db.query(models.Deal).filter_by(customer_id=cust.id).order_by(models.Deal.updated_at.desc()).limit(10).all()
    acts = db.query(models.CustomerActivity).filter_by(customer_id=cust.id).order_by(models.CustomerActivity.id.desc()).limit(15).all()
    diary = db.query(models.DiaryEntry).filter_by(customer_id=cust.id).order_by(models.DiaryEntry.start_at.asc().nullslast()).limit(10).all()
    return {
        "ok": True,
        "customer": crm_service.customer_out(cust, db),
        "deals": [{"id": d.id, "title": d.title, "value": d.value, "status": d.status, "stage_id": d.stage_id} for d in deals],
        "recent_activity": [{"id": a.id, "kind": a.kind, "title": a.title, "body": a.body, "created_at": a.created_at} for a in acts],
        "diary": [{"id": d.id, "title": d.title, "start_at": d.start_at, "status": d.status} for d in diary],
    }

async def _skill_create_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    name = (args.get("name") or args.get("customer_name") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    company_id = args.get("company_id")
    try:
        company_id = int(company_id) if company_id not in (None, "") else None
    except (TypeError, ValueError):
        company_id = None
    try:
        c = crm_service.create_customer(
            db, user,
            name=name,
            email=args.get("email") or "",
            phone=args.get("phone") or "",
            job_title=args.get("job_title") or "",
            account_name=args.get("account_name") or args.get("company") or "",
            website=args.get("website") or "",
            industry=args.get("industry") or "",
            address=args.get("address") or "",
            city=args.get("city") or "",
            country=args.get("country") or "",
            status=args.get("status") or "active",
            source=args.get("source") or "agent",
            tags=args.get("tags") or "",
            notes=args.get("notes") or "",
            annual_value=float(args.get("annual_value") or 0),
            company_id=company_id,
            owner_agent_id=agent.id,
            agent_id=agent.id,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Customer added: {c.name}",
        detail=c.account_name or c.email or "",
        agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "message": f"Created customer {c.name} (#{c.id})",
        "customer_id": c.id,
        "customer": crm_service.customer_out(c, db, light=True),
    }


async def _skill_update_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}
    fields = {}
    for f in (
        "name", "email", "phone", "status", "tags", "notes", "owner_human_id", "owner_agent_id",
        "job_title", "account_name", "website", "industry", "city", "country", "source",
        "annual_value", "lead_status", "lead_score",
    ):
        if args.get(f) is not None:
            fields[f] = args[f]
    if not fields:
        return {"ok": False, "error": "no fields to update"}
    try:
        cust = crm_service.update_customer_fields(db, user, cust, fields)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {
        "ok": True,
        "message": f"Updated {cust.name}",
        "customer": crm_service.customer_out(cust, db, light=True),
    }


async def _skill_delete_customer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}
    name = cust.name
    try:
        out = crm_service.delete_customer(db, user, cust)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Customer deleted: {name}",
        detail=f"by {agent.name}",
        agent_id=agent.id, db=db,
    )
    return {"ok": True, "message": f"Deleted customer {name}", **out}


async def _skill_update_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    try:
        did = int(args.get("deal_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        deal = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    fields = {}
    for f in ("title", "description", "priority", "currency", "status", "value", "expected_close"):
        if args.get(f) is not None:
            fields[f] = args[f]
    if not fields:
        return {"ok": False, "error": "no fields to update"}
    try:
        deal = crm_service.update_deal_fields(db, user, deal, fields)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {
        "ok": True,
        "message": f"Updated deal {deal.title}",
        "deal_id": deal.id,
        "title": deal.title,
        "value": deal.value,
        "status": deal.status,
    }


async def _skill_delete_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    try:
        did = int(args.get("deal_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        deal = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    try:
        out = crm_service.delete_deal(db, user, deal)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "message": f"Deleted deal {out.get('title')}", **out}

async def _skill_log_customer_activity(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Offline CRM note/activity write via crm_service (HANDLER_TABLE → no LLM)."""
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        # soft name match for agents that pass lead/name only
        name = (args.get("name") or args.get("lead") or args.get("customer_name") or "").strip()
        if name:
            cust = (
                db.query(models.Customer)
                .filter(
                    models.Customer.owner_user_id == user.id,
                    models.Customer.name.ilike(f"%{name}%"),
                )
                .order_by(models.Customer.id.desc())
                .first()
            )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}
    kind = (args.get("kind") or "note").strip() or "note"
    title = (args.get("title") or kind.title()).strip()
    body = (args.get("body") or args.get("notes") or args.get("note") or "").strip()
    deal_id = None
    if args.get("deal_id") is not None:
        try:
            deal = crm_service.get_owned_deal(db, user, int(args["deal_id"]))
            if deal.customer_id == cust.id:
                deal_id = deal.id
        except Exception:
            deal_id = None
    try:
        a = crm_service.log_customer_activity(
            db, user, cust,
            kind=kind, title=title, body=body,
            deal_id=deal_id, agent_id=agent.id,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    await emit_ops(
        user.id, kind="action", status="info",
        title=f"{cust.name}: {title}", detail=body[:180],
        agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "log_customer_activity",
        "activity_id": a.id,
        "customer_id": cust.id,
        "customer_name": cust.name,
        "kind": kind,
        "title": title,
        "deal_id": deal_id,
        "activity": crm_service.activity_out(a),
        "message": f"Logged {kind} on {cust.name}",
    }

async def _skill_create_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Create deal; optional stage_id or stage_name (e.g. Qualified after qualify_lead)."""
    from fastapi import HTTPException
    from .. import crm_service
    # note: pipeline_id / stage_id / stage_name optional — default sales board if omitted
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}
    pipe_id = args.get("pipeline_id")
    if pipe_id is not None:
        try:
            pipe = crm_service.get_owned_pipeline(db, user, int(pipe_id))
        except Exception:
            return {"ok": False, "error": "pipeline not found"}
        pipe_id = pipe.id
    else:
        pipe = crm_service.ensure_default_pipeline(db, user)
        pipe_id = pipe.id

    stage_id = args.get("stage_id")
    stage_name = (args.get("stage_name") or args.get("stage") or "").strip()
    # From qualify path: stage_name="Qualified" (or qualified=true)
    if not stage_id and not stage_name:
        qflag = args.get("qualified") or args.get("from_qualify")
        if qflag is True or (
            isinstance(qflag, str) and qflag.strip().lower() in ("1", "true", "yes", "on")
        ):
            stage_name = "Qualified"
    if stage_id is None and stage_name:
        # Resolve by name on target pipeline (exact then substring)
        stages = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=pipe_id)
            .order_by(models.PipelineStage.position, models.PipelineStage.id)
            .all()
        )
        sn = stage_name.lower()
        stage = next((s for s in stages if (s.name or "").strip().lower() == sn), None)
        if not stage:
            stage = next((s for s in stages if sn in (s.name or "").lower()), None)
        if stage:
            stage_id = stage.id

    title = (args.get("title") or f"Opportunity for {cust.name}")[:200]
    try:
        d = crm_service.create_deal_for_customer(
            db, user, cust,
            title=title,
            value=float(args.get("value") or 0),
            currency=(args.get("currency") or "USD"),
            priority=args.get("priority") or "medium",
            expected_close=args.get("expected_close"),
            pipeline_id=pipe_id,
            stage_id=stage_id,
            company_id=None,
            owner_human_id=None,
            owner_agent_id=agent.id,
            activity_title=f"Deal created by {agent.name}: {title}",
            activity_body=f"Value: {float(args.get('value') or 0)}"
                          + (f" · stage={stage_name}" if stage_name else ""),
            agent_id=agent.id,
            strict=False,
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "failed to create deal"
        if "stage" in detail.lower() or "no stages" in detail.lower():
            return {"ok": False, "error": "no stages in pipeline"}
        return {"ok": False, "error": detail}
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "create_deal",
        "deal_id": d.id,
        "stage_id": d.stage_id,
        "deal": crm_service.deal_out(d, db),
        "message": f"Created deal “{d.title}” (#{d.id})",
    }

def _parse_dt_safe(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except Exception:
        return None

async def _skill_schedule_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Schedule diary meeting via crm_service.schedule_meeting (ownership-checked)."""
    from fastapi import HTTPException
    from .. import crm_service

    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        name = (args.get("name") or args.get("lead") or args.get("customer_name") or "").strip()
        if name:
            cust = (
                db.query(models.Customer)
                .filter(
                    models.Customer.owner_user_id == user.id,
                    models.Customer.name.ilike(f"%{name}%"),
                )
                .order_by(models.Customer.id.desc())
                .first()
            )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}

    deal_id = args.get("deal_id")
    try:
        deal_id = int(deal_id) if deal_id not in (None, "") else None
    except (TypeError, ValueError):
        deal_id = None

    try:
        d = crm_service.schedule_meeting(
            db, user, cust,
            title=(args.get("title") or f"Meeting with {cust.name}")[:200],
            start_at=args.get("start_at"),
            end_at=args.get("end_at"),
            location=(args.get("location") or "").strip(),
            notes=(args.get("notes") or "").strip(),
            deal_id=deal_id,
            owner_human_id=args.get("owner_human_id"),
            owner_agent_id=agent.id,
            agent_id=agent.id,
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "schedule failed"
        return {"ok": False, "error": detail}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Diary: {d.title}", detail=cust.name,
        agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "schedule_meeting",
        "diary_id": d.id,
        "customer_id": cust.id,
        "title": d.title,
        "start_at": d.start_at,
        "status": d.status,
        "diary": crm_service.diary_out(d, db),
        "message": f"Scheduled “{d.title}” with {cust.name}",
    }


async def _skill_list_diary(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """List diary entries via crm_service.list_diary (owner-scoped)."""
    from .. import crm_service

    upcoming = args.get("upcoming")
    if isinstance(upcoming, str):
        upcoming = upcoming.strip().lower() in ("1", "true", "yes", "on")
    try:
        limit = min(100, max(1, int(args.get("limit") or 50)))
    except (TypeError, ValueError):
        limit = 50

    rows = crm_service.list_diary(
        db, user,
        customer_id=args.get("customer_id"),
        email=(args.get("email") or "").strip() or None,
        status=(args.get("status") or "").strip() or None,
        upcoming=bool(upcoming),
        limit=limit,
    )
    out = [crm_service.diary_out(d, db) for d in rows]
    return {
        "ok": True,
        "mode": "crm_read",
        "skill": "list_diary",
        "count": len(out),
        "diary": out,
        "message": f"Found {len(out)} diary entr{'y' if len(out) == 1 else 'ies'}",
    }

async def _skill_update_pipeline(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Update deal value/stage/status — routes to move/win/lose or update_deal_fields."""
    from fastapi import HTTPException
    from .. import crm_service
    status = (args.get("status") or "").strip().lower()
    if status in ("won", "win"):
        return await _skill_win_deal(db, agent, user, args)
    if status in ("lost", "lose"):
        return await _skill_lose_deal(db, agent, user, args)
    if args.get("stage_id") is not None or args.get("stage_name"):
        return await _skill_move_deal(db, agent, user, args)
    # Value / notes only via service ownership
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        d = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    fields: dict = {}
    if args.get("value") is not None:
        fields["value"] = args["value"]
    if args.get("notes") is not None:
        fields["description"] = ((d.description or "") + f"\n{args.get('notes')}").strip()[-8000:]
    if not fields:
        return {"ok": False, "error": "no fields to update (value, notes, stage_id/stage_name, or status)"}
    try:
        d = crm_service.update_deal_fields(db, user, d, fields)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {
        "ok": True,
        "message": f"Updated deal “{d.title}”",
        "deal": crm_service.deal_out(d, db),
    }

async def _skill_list_pipelines(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _pipeline_out, _ensure_default_pipeline
    _ensure_default_pipeline(db, user)
    try:
        limit = min(40, int(args.get("limit") or 20))
    except Exception:
        limit = 20
    rows = (
        db.query(models.Pipeline)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Pipeline.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "count": len(rows),
        "pipelines": [_pipeline_out(p, db, with_deals=False) for p in rows],
    }

async def _skill_get_pipeline(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _pipeline_out, _ensure_default_pipeline
    pid = args.get("pipeline_id")
    if pid is None:
        p = _ensure_default_pipeline(db, user)
    else:
        try:
            p = db.get(models.Pipeline, int(pid))
        except Exception:
            p = None
        if not p or p.owner_user_id != user.id:
            return {"ok": False, "error": "pipeline not found"}
    with_deals = args.get("with_deals")
    if with_deals is None:
        with_deals = True
    if isinstance(with_deals, str):
        with_deals = with_deals.lower() not in ("0", "false", "no")
    return {"ok": True, "pipeline": _pipeline_out(p, db, with_deals=bool(with_deals))}

async def _skill_list_pipeline_stages(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _stage_out, _ensure_default_pipeline
    pid = args.get("pipeline_id")
    if pid is None:
        p = _ensure_default_pipeline(db, user)
        pid = p.id
    else:
        try:
            pid = int(pid)
        except Exception:
            return {"ok": False, "error": "pipeline_id invalid"}
        p = db.get(models.Pipeline, pid)
        if not p or p.owner_user_id != user.id:
            return {"ok": False, "error": "pipeline not found"}
    stages = (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=pid)
        .order_by(models.PipelineStage.position, models.PipelineStage.id)
        .all()
    )
    return {"ok": True, "pipeline_id": pid, "stages": [_stage_out(s) for s in stages]}

async def _skill_move_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Move deal stage via crm_service.move_deal / move_deal_stage (ownership-checked)."""
    from fastapi import HTTPException
    from .. import crm_service
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        d = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    # Ensure pipeline still has stages (repairs empty boards)
    try:
        pipe = crm_service.get_owned_pipeline(db, user, d.pipeline_id)
        crm_service.ensure_pipeline_stages(db, pipe, commit=True)
    except Exception:
        pass
    try:
        d, stage = crm_service.move_deal_stage(
            db, user, d,
            stage_id=args.get("stage_id"),
            stage_name=args.get("stage_name"),
            notes=args.get("notes"),
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "move failed"
        if "stage" in detail.lower():
            return {"ok": False, "error": "stage not found on this deal's pipeline (stage_id or stage_name)"}
        return {"ok": False, "error": detail}
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "move_deal",
        "message": f"Moved “{d.title}” to stage “{stage.name}”",
        "deal_id": d.id,
        "stage_id": stage.id,
        "stage_name": stage.name,
        "status": d.status,
        "deal": crm_service.deal_out(d, db),
        "stage": {"id": stage.id, "name": stage.name, "stage_type": stage.stage_type},
    }

async def _skill_win_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Close deal as won via crm_service.win_deal (ownership-checked)."""
    from fastapi import HTTPException
    from .. import crm_service
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        d = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    try:
        pipe = crm_service.get_owned_pipeline(db, user, d.pipeline_id)
        crm_service.ensure_pipeline_stages(db, pipe, commit=True)
    except Exception:
        pass
    try:
        value = None
        if args.get("value") is not None:
            value = float(args["value"])
        d = crm_service.win_deal(
            db, user, d,
            value=value,
            notes=(args.get("notes") or "").strip() or None,
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "win failed"
        return {"ok": False, "error": detail}
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)[:200]}
    out = crm_service.deal_out(d, db)
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "win_deal",
        "message": f"Won deal “{d.title}” (value={d.value})",
        "deal_id": d.id,
        "status": d.status,
        "value": d.value,
        "closed_at": d.closed_at,
        "stage_id": d.stage_id,
        "stage_name": out.get("stage_name"),
        "deal": out,
    }

async def _skill_lose_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Close deal as lost via crm_service.lose_deal (ownership-checked)."""
    from fastapi import HTTPException
    from .. import crm_service
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    try:
        d = crm_service.get_owned_deal(db, user, did)
    except HTTPException:
        return {"ok": False, "error": "deal not found"}
    try:
        pipe = crm_service.get_owned_pipeline(db, user, d.pipeline_id)
        crm_service.ensure_pipeline_stages(db, pipe, commit=True)
    except Exception:
        pass
    reason = (args.get("lost_reason") or args.get("reason") or args.get("notes") or "").strip()
    try:
        d = crm_service.lose_deal(
            db, user, d,
            lost_reason=reason or None,
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "lose failed"
        return {"ok": False, "error": detail}
    out = crm_service.deal_out(d, db)
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "lose_deal",
        "message": f"Lost deal “{d.title}”" + (f" — {reason}" if reason else ""),
        "deal_id": d.id,
        "status": d.status,
        "lost_reason": d.lost_reason or reason or "",
        "closed_at": d.closed_at,
        "stage_id": d.stage_id,
        "stage_name": out.get("stage_name"),
        "deal": out,
    }

async def _skill_pipeline_summary(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _ensure_default_pipeline, _pipeline_out
    pid = args.get("pipeline_id")
    if pid is None:
        p = _ensure_default_pipeline(db, user)
    else:
        try:
            p = db.get(models.Pipeline, int(pid))
        except Exception:
            p = None
        if not p or p.owner_user_id != user.id:
            return {"ok": False, "error": "pipeline not found"}
    board = _pipeline_out(p, db, with_deals=True)
    stages = board.get("board") or []
    open_deals = [d for d in (board.get("deals") or []) if d.get("status") == "open"]
    won = [d for d in (board.get("deals") or []) if d.get("status") == "won"]
    lost = [d for d in (board.get("deals") or []) if d.get("status") == "lost"]
    return {
        "ok": True,
        "pipeline_id": p.id,
        "pipeline_name": p.name,
        "open_count": len(open_deals),
        "open_value": sum(float(d.get("value") or 0) for d in open_deals),
        "won_count": len(won),
        "won_value": sum(float(d.get("value") or 0) for d in won),
        "lost_count": len(lost),
        "stages": [
            {
                "id": s["id"],
                "name": s["name"],
                "count": s.get("count", 0),
                "value": s.get("value", 0),
                "stage_type": s.get("stage_type"),
            }
            for s in stages
        ],
        "message": f"Pipeline “{p.name}”: {len(open_deals)} open · {len(won)} won · {len(lost)} lost",
    }

async def _skill_ensure_sales_pipeline(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Bootstrap default Sales pipeline + stages (includes Qualified). Offline CRM write."""
    from .. import crm_service
    from ..routers.business import _pipeline_out

    result = crm_service.ensure_sales_pipeline(db, user)
    p = result["pipeline"]
    stages = result["stages"]
    stage_brief = [
        {"id": s.id, "name": s.name, "stage_type": s.stage_type, "position": s.position}
        for s in stages
    ]
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "ensure_sales_pipeline",
        "message": f"Sales pipeline ready: {p.name} ({len(stages)} stages)"
                   + ("" if result["has_qualified_stage"] else " — WARNING: no Qualified stage"),
        "pipeline_id": p.id,
        "pipeline_name": p.name,
        "stages": stage_brief,
        "stage_names": result["stage_names"],
        "has_qualified_stage": result["has_qualified_stage"],
        "has_won_stage": result["has_won_stage"],
        "has_lost_stage": result["has_lost_stage"],
        "pipeline": _pipeline_out(p, db, with_deals=False),
    }

async def _skill_list_deals(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    try:
        limit = min(50, int(args.get("limit") or 25))
    except Exception:
        limit = 25
    status = (args.get("status") or "").strip() or None
    q = (args.get("q") or "").strip().lower()
    query = db.query(models.Deal).filter_by(owner_user_id=user.id)
    if status:
        query = query.filter(models.Deal.status == status)
    if args.get("pipeline_id") is not None:
        try:
            query = query.filter(models.Deal.pipeline_id == int(args["pipeline_id"]))
        except Exception:
            pass
    if args.get("stage_id") is not None:
        try:
            query = query.filter(models.Deal.stage_id == int(args["stage_id"]))
        except Exception:
            pass
    rows = query.order_by(models.Deal.updated_at.desc()).limit(80).all()
    out = []
    for d in rows:
        if q and q not in f"{d.title or ''} {d.description or ''}".lower():
            continue
        out.append({
            "id": d.id,
            "title": d.title,
            "value": d.value,
            "status": d.status,
            "customer_id": d.customer_id,
            "pipeline_id": d.pipeline_id,
            "stage_id": d.stage_id,
            "priority": d.priority,
        })
        if len(out) >= limit:
            break
    return {"ok": True, "count": len(out), "deals": out}


# ── Lead qualification (sales AI) ─────────────────────────────────────────

def _score_lead_from_signals(args: dict, cust: models.Customer | None = None) -> tuple[float, list[str]]:
    """Delegate to crm_service.score_lead_signals (shared offline scorer)."""
    from .. import crm_service
    return crm_service.score_lead_signals(args, cust)


def _status_from_score(score: float, explicit: str | None = None) -> str:
    from .. import crm_service
    return crm_service.status_from_lead_score(score, explicit)


def _resolve_or_create_lead(
    db: Session,
    agent: models.Agent,
    user: models.User,
    args: dict,
):
    """Resolve customer by id/email/name; optionally create from lead name."""
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if cust:
        return cust, False
    lead_name = (
        args.get("lead") or args.get("name") or args.get("customer_name") or args.get("q") or ""
    ).strip()
    if lead_name:
        # Prefer exact/ilike name match over creating duplicates
        like = f"%{lead_name}%"
        cust = (
            db.query(models.Customer)
            .filter(
                models.Customer.owner_user_id == user.id,
                models.Customer.name.ilike(like),
            )
            .order_by(models.Customer.id.desc())
            .first()
        )
        if cust:
            return cust, False
        # Create new lead record so sales agents can always qualify inbound names
        create = bool(args.get("create_if_missing"))
        if create or args.get("create_if_missing") is None:
            # default: create when only a free-text lead name is provided
            cust = crm_service.create_customer(
                db, user,
                name=lead_name[:200],
                email=(args.get("email") or "").strip(),
                phone=(args.get("phone") or "").strip(),
                account_name=(args.get("company") or args.get("account_name") or "").strip(),
                status="active",
                source=(args.get("source") or "agent").strip() or "agent",
                notes=(args.get("notes") or "").strip(),
                tags="lead",
                owner_agent_id=agent.id,
                agent_id=agent.id,
            )
            cust.lead_status = "new"
            cust.lead_score = 0.0
            db.commit()
            db.refresh(cust)
            return cust, True
    return None, False


async def _skill_list_leads(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """List CRM leads (customers with lead_status or all filtered by status/score)."""
    from .. import crm_service
    q = (args.get("q") or args.get("query") or "").strip() or None
    lead_status = (args.get("lead_status") or args.get("status") or "").strip().lower() or None
    # When no explicit status, show anyone in the lead funnel (or all if all=true)
    show_all = args.get("all")
    if isinstance(show_all, str):
        show_all = show_all.strip().lower() in ("1", "true", "yes", "on")
    try:
        limit = min(100, max(1, int(args.get("limit") or 25)))
    except (TypeError, ValueError):
        limit = 25
    min_score = args.get("min_score") or args.get("min_lead_score")
    try:
        min_score = float(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        min_score = None

    has_lead = not show_all and not lead_status
    rows, total = crm_service.list_leads(
        db, user,
        q=q,
        lead_status=lead_status,
        has_lead_status=has_lead,
        min_score=min_score,
        limit=limit,
    )
    # If funnel is empty and all not requested, fall back to recent customers tagged/source as leads
    if not rows and has_lead:
        rows2, _ = crm_service.list_customers(db, user, q=q, tag="lead", limit=limit)
        if rows2:
            rows, total = rows2, len(rows2)
        else:
            rows3, total3 = crm_service.list_customers(db, user, q=q, limit=limit)
            rows, total = rows3, total3

    leads = [crm_service.customer_out(c, db, light=True) for c in rows]
    return {
        "ok": True,
        "mode": "crm_read",
        "skill": "list_leads",
        "count": len(leads),
        "total": total,
        "leads": leads,
        "message": f"Found {len(leads)} lead(s)"
                   + (f" with lead_status={lead_status}" if lead_status else ""),
    }


async def _skill_set_lead_status(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Set lead_status (and optional lead_score) on a CRM customer via crm_service."""
    from fastapi import HTTPException
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        # name fallback
        name = (args.get("lead") or args.get("name") or "").strip()
        if name:
            cust = (
                db.query(models.Customer)
                .filter(
                    models.Customer.owner_user_id == user.id,
                    models.Customer.name.ilike(f"%{name}%"),
                )
                .order_by(models.Customer.id.desc())
                .first()
            )
    if not cust:
        return {"ok": False, "error": "customer not found (provide customer_id, email, or lead name)"}

    status = (args.get("lead_status") or args.get("status") or "").strip().lower()
    if not status:
        return {"ok": False, "error": "lead_status required (new|contacted|nurturing|qualified|disqualified|converted)"}

    score_val = None
    if args.get("score") is not None or args.get("lead_score") is not None:
        score_val = args.get("score") if args.get("score") is not None else args.get("lead_score")
    notes = (args.get("notes") or args.get("reason") or "").strip() or None
    reason = (args.get("reason") or args.get("disqualified_reason") or "").strip() or None

    try:
        cust = crm_service.set_lead_status(
            db, user, cust,
            lead_status=status,
            lead_score=score_val,
            notes=notes,
            disqualified_reason=reason if status == "disqualified" else None,
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "failed to set lead status"
        return {"ok": False, "error": detail}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Lead {cust.name}: {status}",
        detail=f"score={cust.lead_score}",
        agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "set_lead_status",
        "message": f"Set lead status of {cust.name} to {status}",
        "customer_id": cust.id,
        "lead_status": cust.lead_status,
        "lead_score": float(cust.lead_score or 0),
        "qualified_at": cust.qualified_at,
        "customer": crm_service.customer_out(cust, db, light=True),
    }


def _letter_grade(score: float) -> str:
    from .. import crm_service
    return crm_service.letter_grade(score)


def _maybe_move_deal_to_qualified(
    db: Session,
    user: models.User,
    agent: models.Agent,
    cust: models.Customer,
    args: dict,
) -> dict | None:
    """Optionally move an open deal into a Qualified-like pipeline stage via move_deal_stage."""
    from .. import crm_service

    move = args.get("move_deal")
    if move is False or (isinstance(move, str) and str(move).strip().lower() in ("0", "false", "no")):
        return None

    deal = None
    if args.get("deal_id") is not None:
        try:
            deal = crm_service.get_owned_deal(db, user, int(args["deal_id"]))
        except Exception:
            deal = None
        if deal and deal.customer_id != cust.id:
            deal = None
    elif move is True or (
        isinstance(move, str) and str(move).strip().lower() in ("1", "true", "yes", "on")
    ):
        deal = (
            db.query(models.Deal)
            .filter_by(owner_user_id=user.id, customer_id=cust.id, status="open")
            .order_by(models.Deal.updated_at.desc())
            .first()
        )
    if not deal:
        return None

    prev = deal.stage_id
    stage_name = (args.get("stage_name") or "qualified").strip()
    try:
        deal, stage = crm_service.move_deal_stage(
            db, user, deal,
            stage_name=stage_name,
            agent_id=agent.id,
            agent_name=agent.name or "",
            activity_title=f"Deal moved to {stage_name}",
            activity_body=f"Deal #{deal.id} stage {prev} → qualified (qualify_lead by {agent.name})",
            commit=False,
        )
    except Exception:
        # Fallback: substring match "qualif" if exact name missing
        stages = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=deal.pipeline_id)
            .order_by(models.PipelineStage.position, models.PipelineStage.id)
            .all()
        )
        stage = next((s for s in stages if "qualif" in (s.name or "").lower()), None)
        if not stage:
            open_stages = [s for s in stages if (s.stage_type or "open").lower() == "open"]
            stage = open_stages[min(1, len(open_stages) - 1)] if len(open_stages) >= 2 else (
                open_stages[0] if open_stages else None
            )
        if not stage:
            return None
        try:
            deal, stage = crm_service.move_deal_stage(
                db, user, deal,
                stage=stage,
                agent_id=agent.id,
                agent_name=agent.name or "",
                commit=False,
            )
        except Exception:
            return None

    return {
        "deal_id": deal.id,
        "stage_id": stage.id,
        "stage_name": stage.name,
        "previous_stage_id": prev,
    }


async def _skill_score_lead(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Numeric + letter score for a lead (offline). Optionally persist lead_score."""
    from .. import crm_service

    # Map context → notes for shared scorer
    merged = dict(args)
    if merged.get("context") and not merged.get("notes"):
        merged["notes"] = merged.get("context")

    cust, created = _resolve_or_create_lead(db, agent, user, {**merged, "create_if_missing": False})
    if not cust:
        # score-only without CRM row: synthetic from args
        score, reasons = crm_service.score_lead_signals(merged, None)
        grade = crm_service.letter_grade(score)
        return {
            "ok": True,
            "skill": "score_lead",
            "mode": "score_only",
            "lead_score": score,
            "grade": grade,
            "suggested_status": crm_service.status_from_lead_score(score),
            "score_reasons": reasons,
            "message": f"Lead score {score:.0f}/100 ({grade}) — no CRM customer resolved",
        }

    score, reasons = crm_service.score_lead_signals(merged, cust)
    grade = crm_service.letter_grade(score)
    suggested = crm_service.status_from_lead_score(score)

    persist = args.get("persist")
    do_persist = persist is True or (
        isinstance(persist, str) and persist.strip().lower() in ("1", "true", "yes", "on")
    )
    if do_persist:
        fields: dict = {"lead_score": score}
        if args.get("set_status") or args.get("lead_status"):
            fields["lead_status"] = str(
                args.get("set_status") or args.get("lead_status") or suggested
            ).strip().lower()
        try:
            cust = crm_service.update_customer_fields(db, user, cust, fields)
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    return {
        "ok": True,
        "skill": "score_lead",
        "mode": "crm_write" if do_persist else "score_only",
        "customer_id": cust.id,
        "customer_name": cust.name,
        "lead_score": score,
        "grade": grade,
        "suggested_status": suggested,
        "score_reasons": reasons,
        "created": created,
        "message": f"Lead score for {cust.name}: {score:.0f}/100 ({grade}) → suggest {suggested}",
        "customer": crm_service.customer_out(cust, db, light=True),
    }


async def _skill_qualify_lead(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Score and qualify a lead against ICP / budget signals; write lead_* fields on Customer.

    Offline CRM write path — no LLM. Uses crm_service.qualify_lead; optionally moves
    an open deal to a Qualified stage.
    """
    from .. import crm_service

    cust, created = _resolve_or_create_lead(db, agent, user, args)
    if not cust:
        return {
            "ok": False,
            "error": "customer not found — provide customer_id, email, or lead name",
        }

    force_q = args.get("force_qualified") or args.get("qualified")
    force = force_q is True or (
        isinstance(force_q, str) and str(force_q).strip().lower() in ("1", "true", "yes", "on")
    )

    try:
        result = crm_service.qualify_lead(
            db, user, cust,
            args=args,
            force_qualified=force,
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

    cust = result["customer"]
    new_status = result["lead_status"]
    score = float(result["lead_score"] or 0)

    deal_moved = None
    if new_status == "qualified":
        try:
            deal_moved = _maybe_move_deal_to_qualified(db, user, agent, cust, args)
            if deal_moved:
                db.commit()
        except Exception:
            deal_moved = None

    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Qualified lead: {cust.name} ({score:.0f})",
        detail=new_status,
        agent_id=agent.id, db=db,
    )

    grade = result["grade"]
    return {
        "ok": True,
        "skill": "qualify_lead",
        "mode": "crm_write",
        "message": (
            f"{'Created and ' if created else ''}Qualified {cust.name}: "
            f"score {score:.0f}/100 ({grade}) → {new_status}"
        ),
        "customer_id": cust.id,
        "customer_name": cust.name,
        "created": created,
        "lead_score": score,
        "lead_status": new_status,
        "qualified_at": result.get("qualified_at") or getattr(cust, "qualified_at", None),
        "grade": grade,
        "score_reasons": result.get("score_reasons") or [],
        "activity_id": result.get("activity_id"),
        "deal_moved": deal_moved,
        "recommendation": result.get("recommendation"),
        "customer": crm_service.customer_out(cust, db, light=True),
    }


async def _skill_list_qualified_leads(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """List customers with lead_status=qualified — always forces qualified (not free-form list_leads)."""
    from .. import crm_service

    q = (args.get("q") or args.get("query") or "").strip() or None
    try:
        limit = min(100, max(1, int(args.get("limit") or 25)))
    except (TypeError, ValueError):
        limit = 25
    min_score = args.get("min_score") or args.get("min_lead_score")
    try:
        min_score = float(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        min_score = None

    # Always qualified — ignore conflicting lead_status/status from args
    rows, total = crm_service.list_leads(
        db, user,
        q=q,
        lead_status="qualified",
        has_lead_status=False,
        min_score=min_score,
        limit=limit,
    )
    leads = [crm_service.customer_out(c, db, light=True) for c in rows]
    return {
        "ok": True,
        "mode": "crm_read",
        "skill": "list_qualified_leads",
        "count": len(leads),
        "total": total,
        "lead_status": "qualified",
        "leads": leads,
        "customers": leads,  # alias for callers that expect customers key
        "message": f"Found {len(leads)} qualified lead(s)",
    }


async def _skill_disqualify_lead(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Mark lead disqualified via crm_service.disqualify_lead (stores reason)."""
    from fastapi import HTTPException
    from .. import crm_service

    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        name = (args.get("lead") or args.get("name") or "").strip()
        if name:
            cust = (
                db.query(models.Customer)
                .filter(
                    models.Customer.owner_user_id == user.id,
                    models.Customer.name.ilike(f"%{name}%"),
                )
                .order_by(models.Customer.id.desc())
                .first()
            )
    if not cust:
        return {"ok": False, "error": "customer not found (provide customer_id, email, or lead name)"}

    reason = (args.get("reason") or args.get("disqualified_reason") or args.get("notes") or "").strip()
    score_val = None
    if args.get("score") is not None or args.get("lead_score") is not None:
        score_val = args.get("score") if args.get("score") is not None else args.get("lead_score")

    try:
        cust = crm_service.disqualify_lead(
            db, user, cust,
            reason=reason or None,
            notes=(args.get("notes") or reason or None),
            lead_score=score_val,
            agent_id=agent.id,
            agent_name=agent.name or "",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "disqualify failed"
        return {"ok": False, "error": detail}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

    await emit_ops(
        user.id, kind="action", status="info",
        title=f"Lead disqualified: {cust.name}",
        detail=reason[:180] if reason else "",
        agent_id=agent.id, db=db,
    )
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "disqualify_lead",
        "message": f"Disqualified lead {cust.name}",
        "customer_id": cust.id,
        "lead_status": cust.lead_status,
        "lead_score": float(cust.lead_score or 0),
        "disqualified_reason": getattr(cust, "disqualified_reason", None) or reason or "",
        "customer": crm_service.customer_out(cust, db, light=True),
    }


# ── Products catalogue (+ special offers) ──────────────────────────────────

def _product_brief(p: models.Product, *, full: bool = False) -> dict:
    from .. import crm_service
    return crm_service.product_out(p, full=full)


def _default_company_id(db: Session, user: models.User, company_id=None) -> int | None:
    from .. import crm_service
    return crm_service.default_company_id(db, user, company_id)


async def _skill_list_products(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """List catalogue products owned by the workspace (crm_service ownership)."""
    from .. import crm_service
    try:
        limit = min(100, max(1, int(args.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    q = (args.get("q") or args.get("query") or "").strip() or None
    status = (args.get("status") or "").strip() or None
    tag = (args.get("tag") or "").strip() or None
    kind = (args.get("kind") or "").strip() or None
    offer_only = args.get("has_offer") or args.get("special_offers")
    if isinstance(offer_only, str):
        offer_only = offer_only.strip().lower() in ("1", "true", "yes", "on")
    company_id = args.get("company_id")
    try:
        company_id = int(company_id) if company_id not in (None, "") else None
    except (TypeError, ValueError):
        company_id = None

    rows = crm_service.list_products(
        db, user,
        q=q, status=status, tag=tag, kind=kind,
        offer_only=bool(offer_only), company_id=company_id, limit=limit,
    )
    return {
        "ok": True,
        "mode": "crm_read",
        "skill": "list_products",
        "count": len(rows),
        "products": [crm_service.product_out(p) for p in rows],
        "message": f"Found {len(rows)} product(s)",
    }


def _product_full_flag(args: dict) -> bool:
    """True when caller wants full product body (read_product / detail=true)."""
    for key in ("full", "detail", "read_full"):
        v = args.get(key)
        if v is True:
            return True
        if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on", "full"):
            return True
    return False


async def _skill_get_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    full = _product_full_flag(args)
    try:
        pid = int(args.get("product_id") or args.get("id"))
    except (TypeError, ValueError):
        # fallback name search (owner-scoped via list_products)
        name = (args.get("name") or args.get("q") or "").strip()
        if not name:
            return {"ok": False, "error": "product_id or name required"}
        rows = crm_service.list_products(db, user, q=name, limit=5)
        p = next(
            (r for r in rows if (r.name or "").strip().lower() == name.lower()),
            rows[0] if rows else None,
        )
        if not p:
            return {"ok": False, "error": f"product not found matching “{name}”"}
        return {
            "ok": True,
            "mode": "crm_read",
            "skill": "get_product",
            "product": crm_service.product_out(p, full=full),
            "message": f"Product #{p.id}: {p.name}",
        }
    try:
        p = crm_service.get_owned_product(db, user, pid)
    except HTTPException:
        return {"ok": False, "error": "product not found"}
    return {
        "ok": True,
        "mode": "crm_read",
        "skill": "get_product",
        "product": crm_service.product_out(p, full=full),
        "message": f"Product #{p.id}: {p.name}",
    }


async def _skill_read_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Full product read (alias of get_product with full body)."""
    return await _skill_get_product(db, agent, user, {**args, "full": True})


async def _skill_search_products(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Search catalogue — same as list_products with q from query/search."""
    q = args.get("q") or args.get("query") or args.get("search") or args.get("name") or ""
    return await _skill_list_products(db, agent, user, {**args, "q": q})


async def _skill_create_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Create product via crm_service (owner-scoped; requires workspace company)."""
    from fastapi import HTTPException
    from .. import crm_service
    name = (args.get("name") or args.get("title") or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    try:
        price = float(args.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    try:
        p = crm_service.create_product(
            db, user,
            name=name,
            company_id=args.get("company_id"),
            sku=str(args.get("sku") or ""),
            description=str(args.get("description") or ""),
            kind=str(args.get("kind") or "product"),
            price=price,
            currency=str(args.get("currency") or "USD"),
            status=str(args.get("status") or "active"),
            tags=args.get("tags") or "",
            benefits=str(args.get("benefits") or ""),
            audience=str(args.get("audience") or ""),
            offer=str(args.get("offer") or args.get("special_offer") or ""),
            image_url=str(args.get("image_url") or ""),
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "create product failed"
        return {"ok": False, "error": detail}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Product added: {p.name}",
        detail=(p.offer or p.description or "")[:180],
        agent_id=agent.id, db=db,
    )
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id, type="product",
            message=f"Created product #{p.id} {p.name}"
            + (f" · offer: {p.offer[:80]}" if p.offer else ""),
        ))
        db.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "create_product",
        "message": f"Created product “{p.name}” (#{p.id})"
                   + (f" with special offer: {p.offer}" if p.offer else ""),
        "product_id": p.id,
        "product": crm_service.product_out(p),
    }


async def _skill_update_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    try:
        pid = int(args.get("product_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "product_id required"}
    try:
        p = crm_service.get_owned_product(db, user, pid)
    except HTTPException:
        return {"ok": False, "error": "product not found"}
    fields: dict = {}
    str_fields = (
        "name", "sku", "description", "kind", "currency", "status",
        "benefits", "audience", "offer", "image_url",
    )
    for f in str_fields:
        val = args.get(f)
        if f == "offer" and val is None:
            val = args.get("special_offer")
        if val is not None:
            fields[f] = val
    if args.get("price") is not None:
        fields["price"] = args.get("price")
    if args.get("tags") is not None:
        fields["tags"] = args.get("tags")
    if args.get("company_id") is not None:
        fields["company_id"] = args.get("company_id")
    if not fields:
        return {"ok": False, "error": "no fields to update"}
    try:
        p = crm_service.update_product_fields(db, user, p, fields)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    changed = list(fields.keys())
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Product updated: {p.name}",
        detail=", ".join(changed),
        agent_id=agent.id, db=db,
    )
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id, type="product",
            message=f"Updated product #{p.id} ({', '.join(changed)})",
        ))
        db.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "update_product",
        "message": f"Updated product “{p.name}” ({', '.join(changed)})",
        "changed": changed,
        "product": crm_service.product_out(p),
    }


async def _skill_delete_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    try:
        pid = int(args.get("product_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "product_id required"}
    try:
        p = crm_service.get_owned_product(db, user, pid)
    except HTTPException:
        return {"ok": False, "error": "product not found"}
    name = p.name
    db.delete(p)
    db.commit()
    await emit_ops(
        user.id, kind="system", status="info",
        title=f"Product deleted: {name}",
        detail=f"by {agent.name}",
        agent_id=agent.id, db=db,
    )
    try:
        db.add(models.ActivityLog(
            agent_id=agent.id, type="product",
            message=f"Deleted product #{pid}: {name}",
        ))
        db.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "mode": "crm_write",
        "skill": "delete_product",
        "message": f"Deleted product “{name}”",
        "product_id": pid,
    }


async def _skill_set_product_offer(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Set or clear a special offer on a product (promo / CTA text)."""
    offer = args.get("offer") if "offer" in args else args.get("special_offer")
    if offer is None:
        return {"ok": False, "error": "offer / special_offer text required (empty string clears offer)"}
    args = {**args, "offer": str(offer).strip(), "product_id": args.get("product_id") or args.get("id")}
    out = await _skill_update_product(db, agent, user, args)
    if out.get("ok"):
        p = out.get("product") or {}
        if p.get("offer"):
            out["message"] = f"Special offer set on “{p.get('name')}”: {p.get('offer')}"
        else:
            out["message"] = f"Special offer cleared on “{p.get('name')}”"
    return out


async def _skill_write_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Upsert product: update if product_id or matching name exists, else create."""
    pid = args.get("product_id") or args.get("id")
    if pid not in (None, ""):
        try:
            int(pid)
            out = await _skill_update_product(db, agent, user, args)
            if out.get("ok"):
                out["message"] = f"Wrote (updated) product — {out.get('message')}"
                out["action"] = "update"
            return out
        except (TypeError, ValueError):
            pass

    name = (args.get("name") or args.get("title") or "").strip()
    if name:
        existing = (
            db.query(models.Product)
            .filter(
                models.Product.owner_user_id == user.id,
                models.Product.name.ilike(name),
            )
            .order_by(models.Product.id.desc())
            .first()
        )
        if existing:
            merged = {**args, "product_id": existing.id}
            out = await _skill_update_product(db, agent, user, merged)
            if out.get("ok"):
                out["message"] = f"Wrote (updated existing) product — {out.get('message')}"
                out["action"] = "update"
            return out

    out = await _skill_create_product(db, agent, user, args)
    if out.get("ok"):
        out["message"] = f"Wrote (created) product — {out.get('message')}"
        out["action"] = "create"
    return out


async def _skill_archive_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Soft-archive a product (status=archived) instead of hard delete."""
    try:
        pid = int(args.get("product_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "product_id required"}
    return await _skill_update_product(
        db, agent, user, {"product_id": pid, "status": "archived"}
    )


async def _skill_duplicate_product(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Clone a product (optionally with a new name / offer) — ownership via crm_service."""
    from fastapi import HTTPException
    from .. import crm_service
    try:
        pid = int(args.get("product_id") or args.get("id") or args.get("source_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "product_id required"}
    try:
        src = crm_service.get_owned_product(db, user, pid)
    except HTTPException:
        return {"ok": False, "error": "product not found"}
    new_name = (args.get("name") or args.get("new_name") or f"{src.name} (copy)").strip()[:200]
    create_args = {
        "name": new_name,
        "sku": str(args.get("sku") or "").strip() or "",
        "description": src.description or "",
        "kind": src.kind or "product",
        "price": args.get("price") if args.get("price") is not None else src.price,
        "currency": src.currency or "USD",
        "status": str(args.get("status") or "draft").strip() or "draft",
        "tags": src.tags or "",
        "benefits": src.benefits or "",
        "audience": src.audience or "",
        "offer": args.get("offer") if args.get("offer") is not None else (src.offer or ""),
        "image_url": src.image_url or "",
        "company_id": src.company_id,
    }
    out = await _skill_create_product(db, agent, user, create_args)
    if out.get("ok"):
        out["source_product_id"] = pid
        out["message"] = f"Duplicated product #{pid} → #{out.get('product_id')}: {new_name}"
    return out


__all__ = [
    '_skill_list_customers',
    '_skill_get_customer',
    '_skill_create_customer',
    '_skill_update_customer',
    '_skill_delete_customer',
    '_skill_log_customer_activity',
    '_skill_create_deal',
    '_skill_update_deal',
    '_skill_delete_deal',
    '_parse_dt_safe',
    '_skill_schedule_meeting',
    '_skill_list_diary',
    '_skill_update_pipeline',
    '_skill_list_pipelines',
    '_skill_get_pipeline',
    '_skill_list_pipeline_stages',
    '_skill_move_deal',
    '_skill_win_deal',
    '_skill_lose_deal',
    '_skill_pipeline_summary',
    '_skill_ensure_sales_pipeline',
    '_skill_list_deals',
    '_skill_list_leads',
    '_skill_list_qualified_leads',
    '_skill_set_lead_status',
    '_skill_disqualify_lead',
    '_skill_score_lead',
    '_skill_qualify_lead',
    '_skill_list_products',
    '_skill_get_product',
    '_skill_read_product',
    '_skill_search_products',
    '_skill_create_product',
    '_skill_update_product',
    '_skill_write_product',
    '_skill_delete_product',
    '_skill_set_product_offer',
    '_skill_archive_product',
    '_skill_duplicate_product',
]
