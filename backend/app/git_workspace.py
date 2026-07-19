"""Git repository connections for agents (GitHub API + local paths)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from . import models
from .crypto import encrypt_secret, decrypt_secret, mask_secret


def repo_out(r: models.GitRepoConnection) -> dict:
    return {
        "id": r.id,
        "provider": r.provider,
        "name": r.name,
        "full_name": r.full_name or r.name,
        "clone_url": r.clone_url or "",
        "html_url": r.html_url or "",
        "default_branch": r.default_branch or "main",
        "local_path": r.local_path or "",
        "machine_id": r.machine_id,
        "company_id": r.company_id,
        "agent_id": r.agent_id,
        "status": r.status,
        "token_hint": r.token_hint or "",
        "has_token": bool(r.encrypted_token),
        "last_sync_at": r.last_sync_at.isoformat() + "Z" if r.last_sync_at else None,
        "last_error": r.last_error or "",
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }


def connect_github_repo(
    db: Session,
    user: models.User,
    *,
    full_name: str,
    token: str,
    company_id: int | None = None,
    agent_id: int | None = None,
    local_path: str = "",
    machine_id: int | None = None,
) -> models.GitRepoConnection:
    full_name = (full_name or "").strip().strip("/")
    token = (token or "").strip()
    if "/" not in full_name:
        raise ValueError("full_name must be owner/repo")
    if not token:
        raise ValueError("GitHub token required")

    # Validate token + repo
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=20) as client:
        r = client.get(f"https://api.github.com/repos/{full_name}", headers=headers)
    if r.status_code == 404:
        raise ValueError(f"Repo not found or no access: {full_name}")
    if r.status_code in (401, 403):
        raise ValueError(f"GitHub auth failed (HTTP {r.status_code})")
    if r.status_code != 200:
        raise ValueError(f"GitHub HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()

    existing = (
        db.query(models.GitRepoConnection)
        .filter_by(user_id=user.id, provider="github", full_name=full_name)
        .first()
    )
    hint = token[-4:] if len(token) >= 4 else "****"
    enc = encrypt_secret(token)
    if existing:
        row = existing
        row.encrypted_token = enc
        row.token_hint = hint
        row.clone_url = data.get("clone_url") or row.clone_url
        row.html_url = data.get("html_url") or row.html_url
        row.default_branch = data.get("default_branch") or row.default_branch or "main"
        row.name = data.get("name") or row.name
        row.status = "connected"
        row.last_error = ""
        row.last_sync_at = datetime.utcnow()
        if company_id is not None:
            row.company_id = company_id
        if agent_id is not None:
            row.agent_id = agent_id
        if local_path:
            row.local_path = local_path
        if machine_id is not None:
            row.machine_id = machine_id
    else:
        row = models.GitRepoConnection(
            user_id=user.id,
            company_id=company_id,
            agent_id=agent_id,
            provider="github",
            name=data.get("name") or full_name.split("/")[-1],
            full_name=full_name,
            clone_url=data.get("clone_url") or f"https://github.com/{full_name}.git",
            html_url=data.get("html_url") or f"https://github.com/{full_name}",
            default_branch=data.get("default_branch") or "main",
            local_path=local_path or "",
            machine_id=machine_id,
            encrypted_token=enc,
            token_hint=hint,
            scopes="",
            status="connected",
            last_sync_at=datetime.utcnow(),
            meta_json=json.dumps({"private": bool(data.get("private"))}),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def connect_local_repo(
    db: Session,
    user: models.User,
    *,
    name: str,
    local_path: str,
    machine_id: int | None = None,
    company_id: int | None = None,
    agent_id: int | None = None,
    default_branch: str = "main",
) -> models.GitRepoConnection:
    name = (name or "").strip() or "local-repo"
    local_path = (local_path or "").strip()
    if not local_path:
        raise ValueError("local_path required")
    row = models.GitRepoConnection(
        user_id=user.id,
        company_id=company_id,
        agent_id=agent_id,
        provider="local",
        name=name,
        full_name=name,
        clone_url="",
        html_url="",
        default_branch=default_branch or "main",
        local_path=local_path,
        machine_id=machine_id,
        status="connected",
        last_sync_at=datetime.utcnow(),
        meta_json=json.dumps({"source": "local"}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_repos(db: Session, user_id: int) -> list[models.GitRepoConnection]:
    return (
        db.query(models.GitRepoConnection)
        .filter_by(user_id=user_id)
        .order_by(models.GitRepoConnection.id.desc())
        .all()
    )


def github_list_user_repos(token: str, limit: int = 30) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=25) as client:
        r = client.get(
            "https://api.github.com/user/repos",
            headers=headers,
            params={"per_page": min(limit, 100), "sort": "updated"},
        )
    if r.status_code != 200:
        raise ValueError(f"GitHub list repos HTTP {r.status_code}")
    out = []
    for item in r.json():
        out.append(
            {
                "full_name": item.get("full_name"),
                "name": item.get("name"),
                "private": item.get("private"),
                "html_url": item.get("html_url"),
                "default_branch": item.get("default_branch"),
                "clone_url": item.get("clone_url"),
            }
        )
    return out


def get_repo_token(row: models.GitRepoConnection) -> str:
    if not row.encrypted_token:
        return ""
    try:
        return decrypt_secret(row.encrypted_token)
    except Exception:
        return ""
