"""Build agent training / knowledge / app access context for LLM prompts."""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from . import models
from .integrations_service import integrations_context_for_agent


def _policy(program: models.AgentProgram | None) -> dict:
    if not program:
        return {}
    try:
        return json.loads(program.policy_json or "{}")
    except Exception:
        return {}


def files_for_agent(
    db: Session, agent: models.Agent, *, max_files: int = 12, max_chars: int = 14000,
) -> list[models.KnowledgeFile]:
    program = db.query(models.AgentProgram).filter_by(agent_id=agent.id).first()
    pol = _policy(program)
    allow_all = bool(pol.get("allow_all_files"))

    q = db.query(models.KnowledgeFile).filter_by(user_id=agent.user_id, status="ready")

    if allow_all:
        return q.order_by(models.KnowledgeFile.updated_at.desc()).limit(max_files).all()

    access = db.query(models.AgentKnowledgeAccess).filter_by(agent_id=agent.id).all()
    if not access:
        return []

    file_ids: set[int] = set()
    folder_ids: set[int] = set()
    for a in access:
        if a.permission == "none":
            continue
        if a.resource_type == "all":
            return q.order_by(models.KnowledgeFile.updated_at.desc()).limit(max_files).all()
        if a.resource_type == "file" and a.resource_id:
            file_ids.add(int(a.resource_id))
        if a.resource_type == "folder" and a.resource_id:
            folder_ids.add(int(a.resource_id))

    rows = []
    if file_ids:
        rows.extend(
            db.query(models.KnowledgeFile)
            .filter(
                models.KnowledgeFile.user_id == agent.user_id,
                models.KnowledgeFile.id.in_(list(file_ids)),
                models.KnowledgeFile.status == "ready",
            )
            .all()
        )
    if folder_ids:
        rows.extend(
            db.query(models.KnowledgeFile)
            .filter(
                models.KnowledgeFile.user_id == agent.user_id,
                models.KnowledgeFile.folder_id.in_(list(folder_ids)),
                models.KnowledgeFile.status == "ready",
            )
            .all()
        )
    seen = set()
    out = []
    for f in rows:
        if f.id in seen:
            continue
        seen.add(f.id)
        out.append(f)
        if len(out) >= max_files:
            break
    return out


def knowledge_context_for_agent(db: Session, agent_id: int, *, max_chars: int | None = None) -> str:
    agent = db.get(models.Agent, agent_id)
    if not agent:
        return "Training library: agent not found."

    program = db.query(models.AgentProgram).filter_by(agent_id=agent_id).first()
    pol = _policy(program)
    cap = int(max_chars or pol.get("max_file_chars") or 14000)

    parts = []
    if program and (program.instructions or "").strip():
        parts.append("## Agent program / standing instructions\n" + program.instructions.strip())

    files = files_for_agent(db, agent, max_chars=cap)
    if not files:
        parts.append(
            "Training library: no files allocated. "
            "Owner can assign files in Training → Agent access."
        )
    else:
        chunks = []
        used = 0
        for f in files:
            body = (f.content_text or "").strip()
            if not body:
                body = f"(No extracted text; file={f.name}, storage={f.storage})"
            header = f"### {f.name} [id={f.id}, storage={f.storage}]"
            if f.tags:
                header += f" tags={f.tags}"
            piece = header + "\n" + body
            if used + len(piece) > cap:
                remain = max(0, cap - used - len(header) - 20)
                if remain > 200:
                    chunks.append(header + "\n" + body[:remain] + "\n…[truncated]")
                break
            chunks.append(piece)
            used += len(piece)
        parts.append(
            "## Training materials you are authorized to use\n"
            "Use these as ground truth for policies, product info, and SOPs.\n\n"
            + "\n\n---\n\n".join(chunks)
        )

    if pol.get("allow_all_apps"):
        conns = (
            db.query(models.IntegrationConnection)
            .filter_by(user_id=agent.user_id, status="connected")
            .all()
        )
        if conns:
            lines = [
                f"- {c.display_name or c.app_id} [{c.app_id}] (policy: all apps allowed)"
                for c in conns
            ]
            parts.append("## Connected apps (all allowed by program policy)\n" + "\n".join(lines))
        else:
            parts.append(integrations_context_for_agent(db, agent_id))
    else:
        parts.append(integrations_context_for_agent(db, agent_id))

    return "\n\n".join(parts)


def agent_program_out(program: models.AgentProgram | None) -> dict | None:
    if not program:
        return None
    return {
        "agent_id": program.agent_id,
        "instructions": program.instructions or "",
        "policy": _policy(program),
        "updated_at": program.updated_at,
    }
