"""Agent chat, messages, memory, and websocket endpoints."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from .. import models
from ..auth_utils import get_current_user, ensure_credits, accept_and_authenticate_ws
from ..ws import manager
from ..llm import stream_completion, complete, provider_hint
from ..usage_billing import bill_llm_turn
from ..user_keys import credentials_for_user
from ..agent_prompts import chat_voice_extra, build_agent_system_prompt
from .agents_common import (
    _get_owned,
    log_activity,
    mode_for_template,
    AgentChatIn,
    AgentMsgIn,
    MemoryIn,
)

log = logging.getLogger("app.agents")

router = APIRouter()


@router.post("/{agent_id}/message-agent")
async def message_agent(agent_id: int, data: AgentMsgIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    return await execute_skill(db, a, user, "message_agent", data.model_dump())


@router.get("/{agent_id}/messages")
def list_agent_messages(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMessage)
        .filter(
            models.AgentMessage.user_id == user.id,
            ((models.AgentMessage.from_agent_id == a.id) | (models.AgentMessage.to_agent_id == a.id)),
        )
        .order_by(models.AgentMessage.id.desc())
        .limit(80)
        .all()
    )
    out = []
    for m in rows:
        fa = db.get(models.Agent, m.from_agent_id)
        ta = db.get(models.Agent, m.to_agent_id)
        out.append({
            "id": m.id,
            "from_agent_id": m.from_agent_id,
            "from_name": fa.name if fa else "?",
            "to_agent_id": m.to_agent_id,
            "to_name": ta.name if ta else "?",
            "thread_key": m.thread_key,
            "content": m.content,
            "status": getattr(m, "status", "sent"),
            "created_at": getattr(m, "created_at", None),
        })
    return {"messages": out}


@router.get("/{agent_id}/memory")
def list_memory(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    rows = (
        db.query(models.AgentMemory)
        .filter_by(agent_id=a.id)
        .order_by(models.AgentMemory.id.desc())
        .limit(100)
        .all()
    )
    return {
        "memories": [
            {
                "id": m.id,
                "kind": m.kind,
                "title": m.title,
                "content": m.content,
                "tags": m.tags,
                "knowledge_file_id": m.knowledge_file_id,
                "created_at": m.created_at,
            }
            for m in rows
        ]
    }


@router.post("/{agent_id}/memory")
async def save_memory(agent_id: int, data: MemoryIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    if data.save_to_training:
        return await execute_skill(
            db, a, user, "save_training",
            {"title": data.title, "content": data.content, "tags": data.tags},
        )
    return await execute_skill(
        db, a, user, "save_memory",
        {"title": data.title, "content": data.content, "kind": data.kind, "tags": data.tags},
    )


@router.delete("/{agent_id}/memory/{memory_id}")
def delete_memory(agent_id: int, memory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = _get_owned(agent_id, user, db)
    m = db.get(models.AgentMemory, memory_id)
    if not m or m.agent_id != a.id:
        raise HTTPException(404, "Memory not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: int, data: AgentChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Direct agent chat — optimised for mobile REST (fast non-stream Grok)."""
    from ..agent_scaffold import map_model, resolve_runtime
    from ..llm import complete as llm_complete
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    rt = resolve_runtime(a)
    mode = mode_for_template(a.template_type)
    model = rt.model or "fast"
    # Prefer snappy Fast tier for chat unless user explicitly picked quality/reasoning
    mlow = str(model).lower()
    if mode == "coding" and mlow in ("fast", "small", "medium", "vps-fast"):
        model = "quality"
    elif mlow in ("", "default", "auto"):
        model = "fast"

    text = (data.message or "").strip()
    if not text:
        raise HTTPException(400, "Message is required")

    conv = None
    if data.conversation_id:
        conv = db.get(models.Conversation, data.conversation_id)
        if not conv or conv.user_id != user.id or conv.agent_id != a.id:
            conv = None
    if not conv:
        conv = (
            db.query(models.Conversation)
            .filter_by(user_id=user.id, agent_id=a.id)
            .order_by(models.Conversation.id.desc())
            .first()
        )
    if not conv:
        conv = models.Conversation(
            user_id=user.id, agent_id=a.id,
            title=f"Chat · {a.name}", mode=mode,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    db.add(models.Message(conversation_id=conv.id, role="user", content=text))
    db.commit()

    # Tight context — fewer messages + shorter caps = faster chat
    history = (
        db.query(models.Message)
        .filter_by(conversation_id=conv.id)
        .order_by(models.Message.id.desc())
        .limit(6)
        .all()
    )
    history = list(reversed(history))
    from ..agent_skills import run_skills_from_text, extract_skill_calls, strip_skill_blocks
    from ..live_ops import emit_ops

    # Ensure core skills are persisted before chat so actions actually run
    try:
        from ..agent_scaffold import ensure_agent_skills
        ensure_agent_skills(db, a)
    except Exception:
        pass

    # Compact prompt for chat (full skills catalogue reserved for tasks/autonomy)
    system = build_agent_system_prompt(db, a, include_config=True, extra="")
    if len(system) > 5000:
        system = system[:5000] + "\n[context truncated for speed]"
    system = (
        system
        + "\n"
        + chat_voice_extra()
        + "\nReply like a helpful human teammate: natural, concise, no code dumps. "
        "When the human asks you to DO something (tasks, meetings, CRM, messages, plans), "
        "emit the correct ```skill blocks with valid JSON args, then give a clear short "
        "confirmation of what you started/finished. Do not only describe skills — run them. "
        "If you need input, end with a ```questions block of short questions."
    )
    llm_messages: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        role = m.role if m.role in ("user", "assistant") else "user"
        content = (m.content or "")[:800]
        if content.strip():
            llm_messages.append({"role": role, "content": content})

    # Best-effort ops event — never block chat on broadcast failure
    try:
        await emit_ops(
            user.id, kind="action", status="running",
            title=f"{a.name} thinking", detail=(text or "")[:200],
            agent_id=a.id, db=db,
        )
    except Exception:
        pass

    creds = credentials_for_user(db, user.id)
    # Short user messages → fewer tokens out (faster + cheaper)
    max_out = 384 if len(text) < 80 else 768 if len(text) < 400 else 1200
    reply = ""
    try:
        reply = await llm_complete(
            llm_messages, model, mode, credentials=creds, max_tokens=max_out,
        )
    except Exception as e:
        log.exception("agent chat failed agent_id=%s", a.id)
        reply = f"Chat backend error: {e}"
    reply = (reply or "").strip()
    if not reply:
        reply = (
            "No reply was generated. Please try again in a moment. "
            "If this keeps happening, check Settings → API / Grok is configured."
        )

    # Only run skill side-effects when the model actually emitted skill blocks
    skill_results: list = []
    clean_reply = reply
    if extract_skill_calls(reply):
        try:
            import asyncio as _asyncio
            # Allow real work (create_task / execute_goal / meetings) — 8s was killing runs
            clean_reply, skill_results = await _asyncio.wait_for(
                run_skills_from_text(db, a, user, reply),
                timeout=45.0,
            )
        except Exception as e:
            log.warning("skill post-process skipped/failed: %s", e)
            try:
                clean_reply = strip_skill_blocks(reply)
            except Exception:
                clean_reply = reply
            skill_results = [{"skill": "?", "ok": False, "error": str(e)[:200]}]
    if skill_results:
        parts = []
        for r in skill_results[:10]:
            sid = r.get("skill") or "?"
            if r.get("ok"):
                parts.append(f"✓ {sid}: {r.get('message') or 'ok'}")
            else:
                parts.append(f"✗ {sid}: {r.get('error') or r.get('message') or 'failed'}")
        summary = "; ".join(parts)
        if summary:
            clean_reply = (clean_reply + f"\n\n— Actions: {summary}").strip()

    # Auto chain: one human goal prompt → parent task + hierarchy-delegated steps + queue.
    # Pass skill_results so a successful execute_goal skill is not double-started.
    chain_info = None
    try:
        from ..task_chain import maybe_auto_chain_from_chat
        chain_info = await maybe_auto_chain_from_chat(
            db, user, a, text, skill_results=skill_results,
        )
        if chain_info and chain_info.get("ok") and chain_info.get("from_skill"):
            n = chain_info.get("steps") or len(chain_info.get("children") or [])
            pid = chain_info.get("parent_task_id")
            if pid:
                clean_reply = (
                    (clean_reply or reply).strip()
                    + f"\n\n— Goal chain started via execute_goal: task #{pid}"
                    + (f" with {n} delegated steps." if n else ".")
                ).strip()
        elif chain_info and chain_info.get("ok") and not chain_info.get("deduped"):
            n = chain_info.get("steps") or len(chain_info.get("children") or [])
            clean_reply = (
                (clean_reply or reply).strip()
                + f"\n\n— Auto-chain started: goal task #{chain_info.get('parent_task_id')} "
                f"with {n} delegated steps (hierarchy). Autonomy will run/monitor them."
            ).strip()
        elif chain_info and chain_info.get("deduped"):
            clean_reply = (
                (clean_reply or reply).strip()
                + f"\n\n— Goal chain already running (#{chain_info.get('parent_task_id')})."
            ).strip()
    except Exception as chain_err:
        log.warning("auto-chain from chat skipped: %s", chain_err)

    final_text = (clean_reply or reply).strip()
    db.add(models.Message(conversation_id=conv.id, role="assistant", content=final_text))
    db.commit()

    charged = bill_llm_turn(db, user, model, llm_messages, final_text)
    try:
        await manager.broadcast(f"tokens:{user.id}", {
            "event": "usage",
            "tokens": charged["tokens"],
            "cost": charged["cost"],
            "model": charged.get("model") or model,
            "tokens_used_period": charged.get("tokens_used_period"),
            "credits": charged.get("credits"),
        })
    except Exception:
        pass
    try:
        await log_activity(a.id, user.id, "action", f"Replied to a direct chat message")
        await emit_ops(
            user.id, kind="action", status="done",
            title=f"{a.name} replied",
            detail=final_text[:240],
            agent_id=a.id, db=db,
        )
    except Exception:
        pass
    out = {
        "reply": final_text,
        "tokens": charged["tokens"],
        "cost": charged["cost"],
        "tokens_used_period": charged.get("tokens_used_period"),
        "credits": charged.get("credits"),
        "bill_source": charged.get("bill_source"),
        "conversation_id": conv.id,
        "skills": skill_results,
        "provider_hint": provider_hint(model, creds),
        "ok": True,
    }
    if chain_info:
        out["goal_chain"] = chain_info
    return out


@router.websocket("/{agent_id}/ws/chat")
async def agent_live_chat(ws: WebSocket, agent_id: int, token: str = Query("")):
    """Streaming live chat with a single agent.

    Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}.
    """
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    if not user:
        db.close()
        return
    a = db.get(models.Agent, agent_id)
    if not a or (a.user_id != user.id and user.role != "admin"):
        db.close()
        try:
            await ws.close(code=4404)
        except Exception:
            pass
        return
    agent_id = a.id
    user_id = user.id
    agent_name = a.name
    personality = a.personality
    template_type = a.template_type
    model = a.model
    config_raw = a.config or "{}"
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("type") == "auth":
                # Extra auth frames after handshake are ignored
                continue
            if data.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue
            text = (data.get("message") or "").strip()
            if not text:
                continue

            bal = db.query(models.Balance).filter_by(user_id=user_id).first()
            user_obj = db.get(models.User, user_id)
            # light credit gate
            try:
                from ..auth_utils import ensure_credits
                ensure_credits(db, user_id)
            except HTTPException as he:
                await ws.send_text(json.dumps({"type": "error", "content": he.detail}))
                continue

            mode = mode_for_template(template_type)
            use_model = model
            if mode == "coding" and use_model in ("vps-fast", "vps-quality"):
                use_model = "vps-qwen-coder"

            conv = (
                db.query(models.Conversation)
                .filter_by(user_id=user_id, agent_id=agent_id)
                .order_by(models.Conversation.id.desc())
                .first()
            )
            if not conv:
                conv = models.Conversation(
                    user_id=user_id, agent_id=agent_id,
                    title=f"Chat · {agent_name}", mode=mode,
                )
                db.add(conv)
                db.commit()
                db.refresh(conv)
            await ws.send_text(json.dumps({
                "type": "conversation", "conversation_id": conv.id,
            }))

            db.add(models.Message(conversation_id=conv.id, role="user", content=text))
            db.commit()

            history = (
                db.query(models.Message)
                .filter_by(conversation_id=conv.id)
                .order_by(models.Message.id)
                .all()
            )
            a_live = db.get(models.Agent, agent_id)
            try:
                if a_live:
                    from ..agent_scaffold import ensure_agent_skills
                    ensure_agent_skills(db, a_live)
            except Exception:
                pass
            system = (
                build_agent_system_prompt(db, a_live)
                if a_live
                else f"You are {agent_name}. Personality: {personality}."
            )
            system = (
                f"{system}\n{chat_voice_extra()}\n"
                "Reply like a helpful human teammate: natural, concise, no code dumps. "
                "When asked to DO work, emit ```skill JSON blocks then confirm in plain language. "
                "If you need input, end with a ```questions block of short questions."
            )
            llm_messages = [{"role": "system", "content": system}]
            for m in history[-10:]:
                role = m.role if m.role in ("user", "assistant") else "user"
                content = (m.content or "")[:4000]
                if content.strip():
                    llm_messages.append({"role": role, "content": content})

            await ws.send_text(json.dumps({"type": "start"}))
            creds = credentials_for_user(db, user_id)
            reply = ""
            try:
                async for chunk in stream_completion(llm_messages, use_model, mode, credentials=creds):
                    reply += chunk
                    await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))
            except Exception as e:
                err = f"Chat backend error: {e}"
                reply = err
                await ws.send_text(json.dumps({"type": "chunk", "content": err}))
            reply = (reply or "").strip() or "No reply generated — please try again."

            # Skill side-effects (same as REST chat) — may include execute_goal
            skill_results: list = []
            try:
                from ..agent_skills import run_skills_from_text, extract_skill_calls, strip_skill_blocks
                a_skills = db.get(models.Agent, agent_id)
                u_skills = db.get(models.User, user_id)
                if a_skills and u_skills and extract_skill_calls(reply):
                    import asyncio as _asyncio
                    clean_live, skill_results = await _asyncio.wait_for(
                        run_skills_from_text(db, a_skills, u_skills, reply),
                        timeout=45.0,
                    )
                    reply = (clean_live or reply).strip()
                    if skill_results:
                        parts = []
                        for r in skill_results[:10]:
                            sid = r.get("skill") or "?"
                            if r.get("ok"):
                                parts.append(f"✓ {sid}: {r.get('message') or 'ok'}")
                            else:
                                parts.append(f"✗ {sid}: {r.get('error') or 'failed'}")
                        if parts:
                            reply = (reply + f"\n\n— Actions: {'; '.join(parts)}").strip()
            except Exception as skill_err:
                log.warning("live chat skill post-process skipped: %s", skill_err)
                try:
                    from ..agent_skills import strip_skill_blocks
                    reply = strip_skill_blocks(reply)
                except Exception:
                    pass
                skill_results = []

            # Auto chain: goal-like human prompts → parent + hierarchy steps (same as REST).
            # skill_results skips a second parent when execute_goal already ran.
            chain_info = None
            try:
                a_chain = db.get(models.Agent, agent_id)
                u_chain = db.get(models.User, user_id)
                if a_chain and u_chain:
                    from ..task_chain import maybe_auto_chain_from_chat
                    chain_info = await maybe_auto_chain_from_chat(
                        db, u_chain, a_chain, text, skill_results=skill_results,
                    )
                    if chain_info and chain_info.get("ok") and chain_info.get("from_skill"):
                        n = chain_info.get("steps") or len(chain_info.get("children") or [])
                        pid = chain_info.get("parent_task_id")
                        if pid:
                            reply = (
                                reply.strip()
                                + f"\n\n— Goal chain started via execute_goal: task #{pid}"
                                + (f" with {n} delegated steps." if n else ".")
                            ).strip()
                    elif chain_info and chain_info.get("ok") and not chain_info.get("deduped"):
                        n = chain_info.get("steps") or len(chain_info.get("children") or [])
                        reply = (
                            reply.strip()
                            + f"\n\n— Auto-chain started: goal task #{chain_info.get('parent_task_id')} "
                            f"with {n} delegated steps (hierarchy). Autonomy will run/monitor them."
                        ).strip()
                    elif chain_info and chain_info.get("deduped"):
                        reply = (
                            reply.strip()
                            + f"\n\n— Goal chain already running (#{chain_info.get('parent_task_id')})."
                        ).strip()
            except Exception as chain_err:
                log.warning("auto-chain from live chat skipped: %s", chain_err)

            db.add(models.Message(conversation_id=conv.id, role="assistant", content=reply))
            db.commit()

            charged = bill_llm_turn(db, user_obj, use_model, llm_messages, reply)
            done_payload = {
                "type": "done",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "conversation_id": conv.id,
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            }
            if chain_info:
                done_payload["goal_chain"] = chain_info
            if skill_results:
                done_payload["skills"] = skill_results
            await ws.send_text(json.dumps(done_payload))
            await manager.broadcast(f"tokens:{user_id}", {
                "event": "usage",
                "tokens": charged["tokens"],
                "cost": charged["cost"],
                "model": charged.get("model") or use_model,
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            })
            await log_activity(agent_id, user_id, "action", "Live chat reply sent")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)[:200]}))
        except Exception:
            pass
    finally:
        db.close()


@router.websocket("/ws")
async def agents_ws(ws: WebSocket, token: str = Query("")):
    """Agent activity feed WS. Auth: ?token= (legacy/mobile) or first-message {"type":"auth","token":...}."""
    db = SessionLocal()
    user = await accept_and_authenticate_ws(ws, token, db)
    db.close()
    if not user:
        return
    channel = f"agents:{user.id}"
    manager.register(channel, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, ws)
