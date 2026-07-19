"""
Comms Practice — train Call / SMS / Email agents with product pitches and humans.

Modes:
  - practice (default): AI drafts scripts + logs as training; no premium delivery
  - live: real Twilio SMS/call or SMTP/Resend email (premium credits)

Product-to-sell context is injected so agents practice sales scripts.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, channels, config
from ..auth_utils import get_current_user, ensure_credits
from ..database import get_db
from ..user_keys import credentials_for_user
from ..usage_billing import bill_llm_turn, charge_event, meter_snapshot
from ..live_ops import emit_ops
from ..human_service import ensure_my_human
from ..ownership import require_owned

router = APIRouter(prefix="/comms", tags=["comms"])

Channel = Literal["call", "sms", "email"]
Mode = Literal["practice", "live"]


class ProductIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: str = ""
    benefits: str = ""
    audience: str = ""
    offer: str = ""
    objection: str = ""


class PracticeRunIn(BaseModel):
    channel: Channel
    mode: Mode = "practice"
    agent_id: int | None = None
    human_id: int | None = None
    # Destination overrides (else human phone/email)
    to: str | None = None
    product: ProductIn | None = None
    # Optional extra instruction for the agent
    goal: str = ""
    # Live call/SMS/email extras
    live_confirm: bool = False


def _channel_status(creds: dict) -> dict:
    twilio_sid = (creds.get("twilio_sid") or config.TWILIO_ACCOUNT_SID or "").strip()
    twilio_token = (creds.get("twilio_token") or config.TWILIO_AUTH_TOKEN or "").strip()
    twilio_from = (creds.get("twilio_from") or config.TWILIO_FROM_NUMBER or "").strip()
    smtp_ok = channels.smtp_or_resend_configured(creds)
    return {
        "twilio": {
            "ready": bool(twilio_sid and twilio_token and twilio_from),
            "from_number": twilio_from[-4:].rjust(len(twilio_from), "*") if twilio_from else "",
            "hint": None if (twilio_sid and twilio_token and twilio_from) else (
                "Set Twilio SID, token, and From number in Settings → API keys or platform env."
            ),
        },
        "email": {
            "ready": bool(smtp_ok),
            "from": (config.SMTP_FROM or config.RESEND_FROM or "")[:80],
            "hint": None if smtp_ok else (
                "Set RESEND_API_KEY + RESEND_FROM, or SMTP_HOST/USER/PASSWORD."
            ),
        },
        "practice_always": True,
        "note": "Practice mode never charges premium; live mode bills SMS/call/email credits.",
    }


def _pick_agent(db: Session, user: models.User, agent_id: int | None) -> models.Agent:
    if agent_id:
        a = require_owned(
            db, models.Agent, agent_id, user,
            user_field='user_id', not_found="Agent not found",
        )
        return a
    # Prefer sales/outreach/support core members
    prefer = ("sales", "outreach", "support", "lead", "orchestrator")
    agents = db.query(models.Agent).filter_by(user_id=user.id, status="active").all()
    for p in prefer:
        for a in agents:
            blob = f"{a.template_type or ''} {a.name or ''} {a.hierarchy_role or ''}".lower()
            if p in blob:
                return a
    if agents:
        return agents[0]
    raise HTTPException(400, "No agents yet — set up Core Team or spawn a sales agent first")


def _pick_human(db: Session, user: models.User, human_id: int | None) -> models.Human:
    if human_id:
        h = require_owned(
            db, models.Human, human_id, user,
            user_field='owner_user_id', not_found="Human not found",
        )
        return h
    return ensure_my_human(db, user)


def _product_brief(p: ProductIn | None) -> str:
    if not p:
        return "Product: (general practice — invent a professional pitch)."
    parts = [f"Product name: {p.name}"]
    if p.price:
        parts.append(f"Price: {p.price}")
    if p.benefits:
        parts.append(f"Benefits: {p.benefits}")
    if p.audience:
        parts.append(f"Audience: {p.audience}")
    if p.offer:
        parts.append(f"Offer / CTA: {p.offer}")
    if p.objection:
        parts.append(f"Common objection to handle: {p.objection}")
    return "\n".join(parts)


async def _draft_script(
    db: Session,
    user: models.User,
    agent: models.Agent,
    channel: str,
    product: ProductIn | None,
    human: models.Human,
    goal: str,
) -> dict[str, Any]:
    from ..llm import complete
    from ..agent_prompts import build_agent_system_prompt
    from ..user_keys import credentials_for_user
    from ..agent_scaffold import map_model

    system = build_agent_system_prompt(db, agent)
    channel_label = {"call": "phone call script", "sms": "SMS text", "email": "sales email"}[channel]
    human_line = f"Practice partner: {human.name}"
    if human.phone:
        human_line += f" · phone {human.phone}"
    if human.email:
        human_line += f" · email {human.email}"

    user_prompt = (
        f"You are training for a live {channel_label} with a human practice partner.\n"
        f"{human_line}\n\n"
        f"{_product_brief(product)}\n\n"
        f"Extra goal: {goal or 'Sell the product helpfully; book a next step.'}\n\n"
        "Output JSON only with keys:\n"
        '  "subject" (email only, else empty string),\n'
        '  "script" (full call script or SMS/email body),\n'
        '  "short_version" (under 160 chars for SMS preview),\n'
        '  "talking_points" (array of 3-5 bullets),\n'
        '  "objection_reply" (one short reply),\n'
        '  "cta" (clear next step).\n'
        "Be human, warm, and concise. No markdown fences."
    )
    model = map_model(agent.model or "quality")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    creds = credentials_for_user(db, user.id)
    raw = ""
    try:
        raw = await complete(messages, model=model, mode="general", credentials=creds)
        raw = (raw or "").strip()
    except Exception as e:
        raw = ""
        err = str(e)
    else:
        err = None

    usage = None
    if raw:
        try:
            usage = bill_llm_turn(db, user, model, messages, raw)
        except Exception:
            usage = None

    parsed: dict[str, Any] = {}
    if raw:
        try:
            text = raw
            if "```" in text:
                import re
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
                if m:
                    text = m.group(1)
            parsed = json.loads(text)
        except Exception:
            parsed = {
                "subject": f"About {product.name}" if product else "Quick note",
                "script": raw[:4000],
                "short_version": raw[:160],
                "talking_points": [],
                "objection_reply": "",
                "cta": "Shall we book a 15-minute call?",
            }

    return {
        "ok": True if raw else False,
        "channel": channel,
        "subject": (parsed.get("subject") or "")[:200],
        "script": (parsed.get("script") or raw or "")[:8000],
        "short_version": (parsed.get("short_version") or (parsed.get("script") or "")[:160])[:320],
        "talking_points": parsed.get("talking_points") or [],
        "objection_reply": parsed.get("objection_reply") or "",
        "cta": parsed.get("cta") or "",
        "usage": usage,
        "error": err,
        "model": model,
    }


def _log_practice(
    db: Session,
    user: models.User,
    agent: models.Agent,
    human: models.Human,
    channel: str,
    mode: str,
    product: ProductIn | None,
    draft: dict,
    delivery: dict | None,
) -> models.AgentMemory:
    title = f"Comms practice · {channel} · {mode}"
    if product:
        title += f" · {product.name}"
    body = {
        "channel": channel,
        "mode": mode,
        "human_id": human.id,
        "human_name": human.name,
        "product": product.model_dump() if product else None,
        "draft": {
            "subject": draft.get("subject"),
            "script": draft.get("script"),
            "short_version": draft.get("short_version"),
            "talking_points": draft.get("talking_points"),
            "cta": draft.get("cta"),
        },
        "delivery": delivery,
        "at": datetime.utcnow().isoformat() + "Z",
    }
    mem = models.AgentMemory(
        agent_id=agent.id,
        user_id=user.id,
        kind="training",
        title=title[:200],
        content=json.dumps(body, default=str)[:8000],
        tags=f"comms-practice,{channel},{mode}",
    )
    db.add(mem)
    # Also activity log
    db.add(models.ActivityLog(
        agent_id=agent.id,
        type=channel if channel in ("email", "sms", "call") else "action",
        message=f"{title}: {(draft.get('short_version') or draft.get('script') or '')[:180]}",
    ))
    db.commit()
    db.refresh(mem)
    return mem


@router.get("/status")
def comms_status(db: Session = Depends(get_db), user=Depends(get_current_user)):
    creds = credentials_for_user(db, user.id)
    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id)
        .order_by(models.Agent.id.asc())
        .limit(80)
        .all()
    )
    humans = (
        db.query(models.Human)
        .filter_by(owner_user_id=user.id)
        .order_by(models.Human.id.asc())
        .limit(40)
        .all()
    )
    my = next((h for h in humans if getattr(h, "is_my_human", False)), humans[0] if humans else None)
    return {
        "channels": _channel_status(creds),
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "template_type": a.template_type,
                "hierarchy_role": a.hierarchy_role,
                "status": a.status,
            }
            for a in agents
        ],
        "humans": [
            {
                "id": h.id,
                "name": h.name,
                "email": h.email,
                "phone": h.phone,
                "is_my_human": bool(getattr(h, "is_my_human", False)),
                "status": h.status,
            }
            for h in humans
        ],
        "default_human_id": my.id if my else None,
        "scenarios": [
            {
                "id": "sell_product",
                "label": "Sell a product",
                "blurb": "Pitch benefits, handle one objection, ask for a next step.",
            },
            {
                "id": "follow_up",
                "label": "Follow-up",
                "blurb": "Warm follow-up after a demo or quote.",
            },
            {
                "id": "support",
                "label": "Support call/SMS",
                "blurb": "Resolve a simple issue and confirm satisfaction.",
            },
            {
                "id": "appointment",
                "label": "Book appointment",
                "blurb": "Propose two times and confirm booking.",
            },
        ],
        "meter": meter_snapshot(db, user),
    }


@router.get("/history")
def comms_history(
    limit: int = 30,
    channel: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = (
        db.query(models.AgentMemory)
        .filter(
            models.AgentMemory.user_id == user.id,
            models.AgentMemory.tags.ilike("%comms-practice%"),
        )
        .order_by(models.AgentMemory.id.desc())
    )
    rows = q.limit(min(80, max(1, limit))).all()
    out = []
    for r in rows:
        try:
            payload = json.loads(r.content or "{}")
        except Exception:
            payload = {"raw": (r.content or "")[:500]}
        ch = payload.get("channel") or ""
        if channel and ch != channel:
            continue
        out.append({
            "id": r.id,
            "agent_id": r.agent_id,
            "title": r.title,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            "channel": ch,
            "mode": payload.get("mode"),
            "product": (payload.get("product") or {}).get("name") if isinstance(payload.get("product"), dict) else None,
            "preview": (payload.get("draft") or {}).get("short_version")
            or ((payload.get("draft") or {}).get("script") or "")[:160],
            "delivery_ok": (payload.get("delivery") or {}).get("ok"),
        })
    return {"items": out, "count": len(out)}


@router.post("/practice/run")
async def practice_run(
    data: PracticeRunIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Draft a call/SMS/email for product practice with a human.
    mode=practice → train only (no Twilio/email send).
    mode=live → real delivery (premium credits) after confirm.
    """
    ensure_credits(db, user.id)
    agent = _pick_agent(db, user, data.agent_id)
    human = _pick_human(db, user, data.human_id)

    draft = await _draft_script(
        db, user, agent, data.channel, data.product, human, data.goal or "",
    )
    if not draft.get("script") and not draft.get("ok"):
        raise HTTPException(502, draft.get("error") or "Could not generate practice script")

    delivery: dict[str, Any] | None = None
    if data.mode == "live":
        if not data.live_confirm:
            raise HTTPException(400, "live_confirm=true required for live send/call")
        creds = credentials_for_user(db, user.id)
        if data.channel == "email":
            to = (data.to or human.email or "").strip()
            if not to:
                raise HTTPException(400, "Human has no email — set email on Team or pass to=")
            ensure_credits(db, user.id, min_credits=0.02)
            charge_event(db, user, "premium-comm", text=draft.get("script") or "", cost_override=0.02)
            sent, detail = await channels.send_email(
                to,
                draft.get("subject") or f"From {agent.name}",
                draft.get("script") or "",
                credentials=creds,
            )
            delivery = {"ok": sent, "channel": "email", "to": to, "detail": detail, "billed": 0.02}
        elif data.channel == "sms":
            to = (data.to or human.phone or "").strip()
            if not to:
                raise HTTPException(400, "Human has no phone — set phone on Team or pass to=")
            body = (draft.get("short_version") or draft.get("script") or "")[:480]
            ensure_credits(db, user.id, min_credits=0.015)
            charge_event(db, user, "premium-comm", text=body, cost_override=0.015)
            sent, detail = await channels.send_sms(to, body, credentials=creds)
            delivery = {"ok": sent, "channel": "sms", "to": to, "detail": detail, "billed": 0.015, "body": body}
        else:  # call
            to = (data.to or human.phone or "").strip()
            if not to:
                raise HTTPException(400, "Human has no phone — set phone on Team or pass to=")
            script = (draft.get("script") or "")[:1500]
            ensure_credits(db, user.id, min_credits=0.08)
            charge_event(db, user, "voice-call", text=script, cost_override=0.08)
            sent, detail = await channels.make_call(to, script, credentials=creds)
            delivery = {"ok": sent, "channel": "call", "to": to, "detail": detail, "billed": 0.08}

        await emit_ops(
            user.id,
            kind="action",
            status="done" if (delivery or {}).get("ok") else "failed",
            title=f"Live {data.channel} practice",
            detail=(delivery or {}).get("detail") or "",
            agent_id=agent.id,
            db=db,
        )

    mem = _log_practice(
        db, user, agent, human, data.channel, data.mode, data.product, draft, delivery,
    )

    return {
        "ok": True,
        "mode": data.mode,
        "channel": data.channel,
        "agent": {"id": agent.id, "name": agent.name},
        "human": {
            "id": human.id,
            "name": human.name,
            "email": human.email,
            "phone": human.phone,
        },
        "product": data.product.model_dump() if data.product else None,
        "draft": {
            "subject": draft.get("subject"),
            "script": draft.get("script"),
            "short_version": draft.get("short_version"),
            "talking_points": draft.get("talking_points"),
            "objection_reply": draft.get("objection_reply"),
            "cta": draft.get("cta"),
        },
        "delivery": delivery,
        "memory_id": mem.id,
        "usage": draft.get("usage"),
        "hint": (
            "Practice mode saved to agent training memory. Switch to Live to send for real "
            "(uses credits + Twilio/email)."
            if data.mode == "practice"
            else None
        ),
        "meter": meter_snapshot(db, user),
    }
