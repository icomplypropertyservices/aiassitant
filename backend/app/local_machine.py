"""Local / remote machine registration and snapshots for orchestrator + CLI."""
from __future__ import annotations

import json
import os
import platform
import secrets
import socket
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models


def _public_id() -> str:
    return f"mch_{secrets.token_hex(8)}"


def collect_local_snapshot() -> dict[str, Any]:
    """Snapshot of the machine running this process (API host or CLI)."""
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    disk = {}
    try:
        import shutil
        usage = shutil.disk_usage(cwd)
        disk = {
            "total_gb": round(usage.total / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "used_gb": round((usage.total - usage.free) / (1024**3), 2),
        }
    except Exception:
        pass

    env_flags = {
        "vercel": bool(os.getenv("VERCEL")),
        "has_git": bool(os.environ.get("PATH") and "git" in os.environ.get("PATH", "").lower() or True),
        "python": platform.python_version(),
    }

    # Discover common project roots under home (shallow)
    project_hints = []
    for rel in (
        "ai-business-assistant",
        "icomply-products-seo",
        "riddle-wallet",
        "Desktop",
    ):
        p = os.path.join(home, rel) if not rel.startswith("C:") else rel
        # Windows user path
        candidates = [
            os.path.join(home, rel),
            os.path.join("C:\\Users\\E-Store", rel),
        ]
        for c in candidates:
            if os.path.isdir(c):
                project_hints.append(c)
                break

    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "arch": platform.machine(),
        "processor": platform.processor(),
        "cwd": cwd,
        "home": home,
        "disk": disk,
        "env": env_flags,
        "project_hints": project_hints[:20],
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }


def machine_out(m: models.MachineNode) -> dict:
    snap = {}
    try:
        snap = json.loads(m.snapshot_json or "{}")
    except Exception:
        snap = {}
    return {
        "id": m.id,
        "public_id": m.public_id,
        "name": m.name,
        "kind": m.kind,
        "hostname": m.hostname or "",
        "os_name": m.os_name or "",
        "arch": m.arch or "",
        "status": m.status,
        "agent_version": m.agent_version or "",
        "labels": m.labels or "",
        "snapshot": snap,
        "last_seen_at": m.last_seen_at.isoformat() + "Z" if m.last_seen_at else None,
        "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
    }


def register_or_heartbeat(
    db: Session,
    user: models.User,
    *,
    name: str | None = None,
    kind: str = "local",
    public_id: str | None = None,
    snapshot: dict | None = None,
    labels: str = "",
    agent_version: str = "cli-1.0",
) -> models.MachineNode:
    snap = snapshot or collect_local_snapshot()
    hostname = snap.get("hostname") or socket.gethostname()
    row = None
    if public_id:
        row = db.query(models.MachineNode).filter_by(user_id=user.id, public_id=public_id).first()
    if not row:
        row = (
            db.query(models.MachineNode)
            .filter_by(user_id=user.id, hostname=hostname, kind=kind)
            .first()
        )
    now = datetime.utcnow()
    if row:
        row.snapshot_json = json.dumps(snap)
        row.hostname = hostname
        row.os_name = str(snap.get("os") or row.os_name or "")[:200]
        row.arch = str(snap.get("arch") or row.arch or "")[:64]
        row.status = "online"
        row.last_seen_at = now
        row.agent_version = agent_version or row.agent_version
        if labels:
            row.labels = labels
        if name:
            row.name = name
        row.updated_at = now
    else:
        row = models.MachineNode(
            user_id=user.id,
            public_id=public_id or _public_id(),
            name=name or f"{hostname} ({kind})",
            kind=kind or "local",
            hostname=hostname,
            os_name=str(snap.get("os") or "")[:200],
            arch=str(snap.get("arch") or "")[:64],
            status="online",
            agent_version=agent_version,
            snapshot_json=json.dumps(snap),
            labels=labels or "",
            last_seen_at=now,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_machines(db: Session, user_id: int) -> list[models.MachineNode]:
    return (
        db.query(models.MachineNode)
        .filter_by(user_id=user_id)
        .order_by(models.MachineNode.id.desc())
        .all()
    )
