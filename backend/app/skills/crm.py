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
    try:
        limit = min(100, int(args.get("limit") or 25))
    except Exception:
        limit = 25
    rows, _total = crm_service.list_customers(
        db, user, q=q or None, status=status, tag=tag, limit=limit,
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
        "annual_value",
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
    from .. import crm_service
    try:
        did = int(args.get("deal_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    deal = db.get(models.Deal, did)
    if not deal or deal.owner_user_id != user.id:
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
    from .. import crm_service
    try:
        did = int(args.get("deal_id") or args.get("id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    deal = db.get(models.Deal, did)
    if not deal or deal.owner_user_id != user.id:
        return {"ok": False, "error": "deal not found"}
    try:
        out = crm_service.delete_deal(db, user, deal)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "message": f"Deleted deal {out.get('title')}", **out}

async def _skill_log_customer_activity(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from .. import crm_service
    cust = crm_service.resolve_customer(
        db, user, args.get("customer_id"), (args.get("email") or "").strip() or None,
    )
    if not cust:
        return {"ok": False, "error": "customer not found or not owned"}
    kind = (args.get("kind") or "note").strip()
    title = (args.get("title") or kind.title()).strip()
    body = (args.get("body") or "").strip()
    a = crm_service.log_customer_activity(
        db, user, cust,
        kind=kind, title=title, body=body, agent_id=agent.id,
    )
    await emit_ops(user.id, kind="action", status="info", title=f"{cust.name}: {title}", detail=body[:180], agent_id=agent.id, db=db)
    return {"ok": True, "activity_id": a.id, "kind": kind}

async def _skill_create_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from fastapi import HTTPException
    from .. import crm_service
    # note: pipeline_id / stage_id optional — default sales board if omitted
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
        pipe_id = None
    title = (args.get("title") or f"Opportunity for {cust.name}")[:200]
    try:
        d = crm_service.create_deal_for_customer(
            db, user, cust,
            title=title,
            value=float(args.get("value") or 0),
            currency="USD",
            priority=args.get("priority") or "medium",
            expected_close=args.get("expected_close"),
            pipeline_id=pipe_id,
            stage_id=args.get("stage_id"),
            company_id=None,
            owner_human_id=None,
            owner_agent_id=agent.id,
            activity_title=f"Deal created by {agent.name}: {title}",
            activity_body=f"Value: {float(args.get('value') or 0)}",
            agent_id=agent.id,
            strict=False,
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "failed to create deal"
        if "stage" in detail.lower() or "no stages" in detail.lower():
            return {"ok": False, "error": "no stages in pipeline"}
        return {"ok": False, "error": detail}
    return {"ok": True, "deal": crm_service.deal_out(d, db)}

def _parse_dt_safe(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except Exception:
        return None

async def _skill_schedule_meeting(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    cust = None
    if cid:
        try:
            cust = db.get(models.Customer, int(cid))
        except Exception:
            cust = None
    if not cust and email:
        cust = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
    if not cust or cust.owner_user_id != user.id:
        return {"ok": False, "error": "customer not found or not owned"}
    title = (args.get("title") or f"Meeting with {cust.name}")[:200]
    start = _parse_dt_safe(args.get("start_at"))
    end = _parse_dt_safe(args.get("end_at"))
    d = models.DiaryEntry(
        owner_user_id=user.id,
        customer_id=cust.id,
        title=title,
        start_at=start,
        end_at=end,
        location=(args.get("location") or "").strip(),
        notes=(args.get("notes") or "").strip(),
        status="scheduled",
        owner_human_id=args.get("owner_human_id"),
        owner_agent_id=agent.id,
    )
    db.add(d)
    db.flush()
    db.add(models.CustomerActivity(
        customer_id=cust.id,
        owner_user_id=user.id,
        kind="meeting",
        title=f"Scheduled: {title}",
        body=f"{start.isoformat() if start else 'TBD'} @ {d.location or '—'}",
        agent_id=agent.id,
    ))
    cust.last_contacted_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    await emit_ops(user.id, kind="action", status="info", title=f"Diary: {title}", detail=cust.name, agent_id=agent.id, db=db)
    return {
        "ok": True,
        "diary_id": d.id,
        "title": d.title,
        "start_at": d.start_at,
        "status": d.status,
    }

async def _skill_list_diary(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    cid = args.get("customer_id")
    email = (args.get("email") or "").strip()
    status = args.get("status")
    upcoming = bool(args.get("upcoming"))
    q = db.query(models.DiaryEntry).filter_by(owner_user_id=user.id)
    if cid:
        try:
            q = q.filter_by(customer_id=int(cid))
        except Exception:
            pass
    elif email:
        c = db.query(models.Customer).filter_by(owner_user_id=user.id, email=email).first()
        if c:
            q = q.filter_by(customer_id=c.id)
    if status:
        q = q.filter_by(status=status)
    if upcoming:
        now = datetime.utcnow()
        q = q.filter(models.DiaryEntry.status == "scheduled", (models.DiaryEntry.start_at >= now) | (models.DiaryEntry.start_at.is_(None)))
    rows = q.order_by(models.DiaryEntry.start_at.asc().nullslast(), models.DiaryEntry.id.desc()).limit(50).all()
    out = []
    for d in rows:
        cust = db.get(models.Customer, d.customer_id)
        out.append({
            "id": d.id,
            "customer_id": d.customer_id,
            "customer_name": cust.name if cust else None,
            "title": d.title,
            "start_at": d.start_at,
            "end_at": d.end_at,
            "location": d.location,
            "status": d.status,
        })
    return {"ok": True, "count": len(out), "diary": out}

async def _skill_update_pipeline(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Update deal value/stage/status — full CRM write path."""
    status = (args.get("status") or "").strip().lower()
    if status in ("won", "win"):
        return await _skill_win_deal(db, agent, user, args)
    if status in ("lost", "lose"):
        return await _skill_lose_deal(db, agent, user, args)
    if args.get("stage_id") is not None or args.get("stage_name"):
        return await _skill_move_deal(db, agent, user, args)
    # Value / notes only
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    d = db.get(models.Deal, did)
    if not d or d.owner_user_id != user.id:
        return {"ok": False, "error": "deal not found"}
    if args.get("value") is not None:
        try:
            d.value = float(args["value"])
        except Exception:
            pass
    if args.get("notes") is not None:
        d.description = ((d.description or "") + f"\n{args.get('notes')}").strip()[-8000:]
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    from ..routers.business import _deal_out
    return {"ok": True, "message": f"Updated deal “{d.title}”", "deal": _deal_out(d, db)}

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
    from ..routers.business import _deal_out
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    d = db.get(models.Deal, did)
    if not d or d.owner_user_id != user.id:
        return {"ok": False, "error": "deal not found"}
    stage = None
    if args.get("stage_id") is not None:
        try:
            stage = db.get(models.PipelineStage, int(args["stage_id"]))
        except Exception:
            stage = None
    if not stage and args.get("stage_name"):
        name = str(args["stage_name"]).strip().lower()
        stages = (
            db.query(models.PipelineStage)
            .filter_by(pipeline_id=d.pipeline_id)
            .all()
        )
        stage = next((s for s in stages if (s.name or "").strip().lower() == name), None)
        if not stage:
            stage = next((s for s in stages if name in (s.name or "").lower()), None)
    if not stage or stage.pipeline_id != d.pipeline_id:
        return {"ok": False, "error": "stage not found on this deal's pipeline (stage_id or stage_name)"}
    prev = d.stage_id
    d.stage_id = stage.id
    # Stage type won/lost → close deal
    st = (stage.stage_type or "open").lower()
    if st == "won":
        d.status = "won"
        d.closed_at = datetime.utcnow()
    elif st == "lost":
        d.status = "lost"
        d.closed_at = datetime.utcnow()
    else:
        d.status = "open"
        d.closed_at = None
    if args.get("notes"):
        d.description = ((d.description or "") + f"\n[{agent.name}] {args.get('notes')}").strip()[-8000:]
    d.updated_at = datetime.utcnow()
    db.add(models.CustomerActivity(
        customer_id=d.customer_id,
        owner_user_id=user.id,
        kind="stage",
        title=f"Deal moved to {stage.name}",
        body=f"Deal #{d.id} stage {prev} → {stage.id} by {agent.name}",
        deal_id=d.id,
        agent_id=agent.id,
    ))
    db.commit()
    db.refresh(d)
    return {
        "ok": True,
        "message": f"Moved “{d.title}” to stage “{stage.name}”",
        "deal": _deal_out(d, db),
        "stage": {"id": stage.id, "name": stage.name, "stage_type": stage.stage_type},
    }

async def _skill_win_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _deal_out
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    d = db.get(models.Deal, did)
    if not d or d.owner_user_id != user.id:
        return {"ok": False, "error": "deal not found"}
    # Prefer won stage if present
    won = (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=d.pipeline_id, stage_type="won")
        .order_by(models.PipelineStage.position.desc())
        .first()
    )
    if won:
        d.stage_id = won.id
    if args.get("value") is not None:
        try:
            d.value = float(args["value"])
        except Exception:
            pass
    if args.get("notes"):
        d.description = ((d.description or "") + f"\n[Win] {args.get('notes')}").strip()[-8000:]
    d.status = "won"
    d.closed_at = datetime.utcnow()
    d.updated_at = datetime.utcnow()
    db.add(models.CustomerActivity(
        customer_id=d.customer_id,
        owner_user_id=user.id,
        kind="deal",
        title=f"Deal won: {d.title}",
        body=f"Won by {agent.name}. Value={d.value}",
        deal_id=d.id,
        agent_id=agent.id,
    ))
    db.commit()
    db.refresh(d)
    return {"ok": True, "message": f"Won deal “{d.title}”", "deal": _deal_out(d, db)}

async def _skill_lose_deal(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..routers.business import _deal_out
    try:
        did = int(args.get("deal_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "deal_id required"}
    d = db.get(models.Deal, did)
    if not d or d.owner_user_id != user.id:
        return {"ok": False, "error": "deal not found"}
    lost = (
        db.query(models.PipelineStage)
        .filter_by(pipeline_id=d.pipeline_id, stage_type="lost")
        .order_by(models.PipelineStage.position.desc())
        .first()
    )
    if lost:
        d.stage_id = lost.id
    reason = (args.get("lost_reason") or args.get("reason") or args.get("notes") or "").strip()
    if reason:
        d.lost_reason = reason[:500]
        d.description = ((d.description or "") + f"\n[Lost] {reason}").strip()[-8000:]
    d.status = "lost"
    d.closed_at = datetime.utcnow()
    d.updated_at = datetime.utcnow()
    db.add(models.CustomerActivity(
        customer_id=d.customer_id,
        owner_user_id=user.id,
        kind="deal",
        title=f"Deal lost: {d.title}",
        body=f"Lost by {agent.name}. Reason: {reason or '—'}",
        deal_id=d.id,
        agent_id=agent.id,
    ))
    db.commit()
    db.refresh(d)
    return {"ok": True, "message": f"Lost deal “{d.title}”", "deal": _deal_out(d, db)}

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
    from ..routers.business import _ensure_default_pipeline, _pipeline_out
    p = _ensure_default_pipeline(db, user)
    return {
        "ok": True,
        "message": f"Sales pipeline ready: {p.name}",
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
]
