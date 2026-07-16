"""Training library: folders, files, cloud storage, agent access programming."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from .. import storage_backends as store
from ..training_context import (
    knowledge_context_for_agent,
    agent_program_out,
    files_for_agent,
)
from ..integrations_service import connection_out

router = APIRouter(prefix="/training", tags=["training"])
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class FolderIn(BaseModel):
    name: str
    description: str = ""
    parent_id: int | None = None


class NoteIn(BaseModel):
    name: str
    content: str
    description: str = ""
    tags: str = ""
    folder_id: int | None = None
    status: str = "ready"


class FileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: str | None = None
    folder_id: int | None = None
    content: str | None = None
    status: str | None = None


class AccessItem(BaseModel):
    resource_type: str
    resource_id: int | None = None
    permission: str = "read"


class AgentAccessIn(BaseModel):
    items: list[AccessItem] = Field(default_factory=list)
    replace: bool = True


class ProgramIn(BaseModel):
    instructions: str = ""
    allow_all_files: bool = False
    allow_all_apps: bool = False
    max_file_chars: int = 14000
    file_ids: list[int] | None = None
    folder_ids: list[int] | None = None
    connection_ids: list[int] | None = None


class ImportCloudIn(BaseModel):
    storage: str
    path: str
    connection_id: int | None = None
    folder_id: int | None = None
    name: str | None = None
    tags: str = ""


class FileAgentsIn(BaseModel):
    agent_ids: list[int] = Field(default_factory=list)


def _file_out(f: models.KnowledgeFile, db: Session | None = None) -> dict:
    agents = []
    if db is not None:
        q = db.query(models.AgentKnowledgeAccess).filter(
            (
                (models.AgentKnowledgeAccess.resource_type == "file")
                & (models.AgentKnowledgeAccess.resource_id == f.id)
            )
            | (
                (models.AgentKnowledgeAccess.resource_type == "all")
            )
        )
        if f.folder_id:
            q = db.query(models.AgentKnowledgeAccess).filter(
                (
                    (models.AgentKnowledgeAccess.resource_type == "file")
                    & (models.AgentKnowledgeAccess.resource_id == f.id)
                )
                | (
                    (models.AgentKnowledgeAccess.resource_type == "folder")
                    & (models.AgentKnowledgeAccess.resource_id == f.folder_id)
                )
                | (models.AgentKnowledgeAccess.resource_type == "all")
            )
        seen = set()
        for r in q.all():
            if r.agent_id in seen:
                continue
            a = db.get(models.Agent, r.agent_id)
            if not a or a.user_id != f.user_id:
                continue
            seen.add(r.agent_id)
            agents.append({"id": a.id, "name": a.name, "permission": r.permission})

    preview = (f.content_text or "")[:400]
    return {
        "id": f.id,
        "name": f.name,
        "description": f.description or "",
        "tags": f.tags or "",
        "kind": f.kind,
        "storage": f.storage,
        "storage_path": f.storage_path or "",
        "connection_id": f.connection_id,
        "folder_id": f.folder_id,
        "mime_type": f.mime_type,
        "size_bytes": f.size_bytes or 0,
        "status": f.status,
        "has_content": bool((f.content_text or "").strip()),
        "content_preview": preview,
        "content_chars": len(f.content_text or ""),
        "agents": agents,
        "created_at": f.created_at,
        "updated_at": f.updated_at,
    }


def _folder_out(folder: models.KnowledgeFolder, db: Session) -> dict:
    n = db.query(models.KnowledgeFile).filter_by(folder_id=folder.id).count()
    return {
        "id": folder.id,
        "name": folder.name,
        "description": folder.description or "",
        "parent_id": folder.parent_id,
        "file_count": n,
        "created_at": folder.created_at,
    }


def _owned_file(file_id: int, user, db) -> models.KnowledgeFile:
    f = db.get(models.KnowledgeFile, file_id)
    if not f or f.user_id != user.id:
        raise HTTPException(404, "File not found")
    return f


def _storage_connection(db: Session, user, storage: str, connection_id: int | None):
    storage = (storage or "local").lower()
    if storage in ("local", "", "note"):
        return None
    app_map = {
        "dropbox": "dropbox",
        "gcs": "google_cloud_storage",
        "google_cloud": "google_cloud_storage",
        "google_cloud_storage": "google_cloud_storage",
    }
    app_id = app_map.get(storage, storage)
    q = db.query(models.IntegrationConnection).filter_by(user_id=user.id, status="connected")
    if connection_id:
        c = db.get(models.IntegrationConnection, connection_id)
        if not c or c.user_id != user.id:
            raise HTTPException(400, "Invalid storage connection")
        return c
    c = q.filter_by(app_id=app_id).order_by(models.IntegrationConnection.id.desc()).first()
    if not c and storage in ("gcs", "google_cloud", "google_cloud_storage"):
        c = (
            q.filter(models.IntegrationConnection.app_id.in_(["google_cloud_storage", "google", "gcs"]))
            .first()
        )
    if not c:
        raise HTTPException(
            400,
            f"No connected {storage} storage. Connect it under Settings → Connected apps first.",
        )
    return c


@router.get("/overview")
def overview(db: Session = Depends(get_db), user=Depends(get_current_user)):
    files = db.query(models.KnowledgeFile).filter_by(user_id=user.id).count()
    folders = db.query(models.KnowledgeFolder).filter_by(user_id=user.id).count()
    ready = db.query(models.KnowledgeFile).filter_by(user_id=user.id, status="ready").count()
    by_storage: dict[str, int] = {}
    for f in db.query(models.KnowledgeFile).filter_by(user_id=user.id).all():
        by_storage[f.storage] = by_storage.get(f.storage, 0) + 1
    stor_apps = ("dropbox", "google_cloud_storage", "google")
    conns = (
        db.query(models.IntegrationConnection)
        .filter(
            models.IntegrationConnection.user_id == user.id,
            models.IntegrationConnection.app_id.in_(stor_apps),
        )
        .all()
    )
    return {
        "files": files,
        "folders": folders,
        "ready": ready,
        "by_storage": by_storage,
        "storage_connections": [connection_out(c, db) for c in conns],
        "backends": [
            {"id": "local", "name": "Local (server)", "always": True},
            {"id": "gcs", "name": "Google Cloud Storage", "app_id": "google_cloud_storage"},
            {"id": "dropbox", "name": "Dropbox", "app_id": "dropbox"},
        ],
    }


@router.get("/folders")
def list_folders(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.KnowledgeFolder)
        .filter_by(user_id=user.id)
        .order_by(models.KnowledgeFolder.name)
        .all()
    )
    return [_folder_out(f, db) for f in rows]


@router.post("/folders")
def create_folder(data: FolderIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "Folder name required")
    if data.parent_id:
        p = db.get(models.KnowledgeFolder, data.parent_id)
        if not p or p.user_id != user.id:
            raise HTTPException(400, "Invalid parent folder")
    folder = models.KnowledgeFolder(
        user_id=user.id,
        name=name,
        description=(data.description or "").strip(),
        parent_id=data.parent_id,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _folder_out(folder, db)


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    folder = db.get(models.KnowledgeFolder, folder_id)
    if not folder or folder.user_id != user.id:
        raise HTTPException(404, "Folder not found")
    for f in db.query(models.KnowledgeFile).filter_by(folder_id=folder_id).all():
        f.folder_id = None
    db.query(models.AgentKnowledgeAccess).filter_by(
        resource_type="folder", resource_id=folder_id,
    ).delete()
    db.delete(folder)
    db.commit()
    return {"ok": True}


@router.get("/files")
def list_files(
    folder_id: int | None = None,
    q: str | None = None,
    storage: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(models.KnowledgeFile).filter_by(user_id=user.id)
    if folder_id is not None:
        if folder_id == 0:
            query = query.filter(models.KnowledgeFile.folder_id.is_(None))
        else:
            query = query.filter_by(folder_id=folder_id)
    if storage:
        query = query.filter_by(storage=storage)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.KnowledgeFile.name.ilike(like))
            | (models.KnowledgeFile.tags.ilike(like))
            | (models.KnowledgeFile.description.ilike(like))
        )
    rows = query.order_by(models.KnowledgeFile.updated_at.desc()).limit(200).all()
    return {"files": [_file_out(f, db) for f in rows], "count": len(rows)}


@router.get("/files/{file_id}")
def get_file(file_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    f = _owned_file(file_id, user, db)
    out = _file_out(f, db)
    out["content"] = f.content_text or ""
    return out


@router.post("/notes")
def create_note(data: NoteIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = (data.name or "").strip()
    content = data.content or ""
    if not name:
        raise HTTPException(400, "Name required")
    if not content.strip():
        raise HTTPException(400, "Content required")
    if data.folder_id:
        folder = db.get(models.KnowledgeFolder, data.folder_id)
        if not folder or folder.user_id != user.id:
            raise HTTPException(400, "Invalid folder")
    f = models.KnowledgeFile(
        user_id=user.id,
        folder_id=data.folder_id,
        name=name,
        description=(data.description or "").strip(),
        tags=(data.tags or "").strip(),
        kind="note",
        storage="local",
        storage_path="",
        mime_type="text/markdown",
        size_bytes=len(content.encode("utf-8")),
        content_text=content,
        status=data.status or "ready",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return _file_out(f, db)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder_id: int | None = Form(None),
    storage: str = Form("local"),
    connection_id: int | None = Form(None),
    tags: str = Form(""),
    description: str = Form(""),
    remote_folder: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    storage = (storage or "local").lower()
    conn = _storage_connection(db, user, storage, connection_id) if storage != "local" else None

    if folder_id:
        folder = db.get(models.KnowledgeFolder, int(folder_id))
        if not folder or folder.user_id != user.id:
            raise HTTPException(400, "Invalid folder")

    try:
        meta = await store.save_bytes(
            user_id=user.id,
            filename=file.filename or "upload.bin",
            data=data,
            storage=storage,
            connection=conn,
            remote_folder=remote_folder,
            mime=file.content_type,
        )
    except Exception as e:
        raise HTTPException(400, f"Upload failed: {e}") from e

    f = models.KnowledgeFile(
        user_id=user.id,
        folder_id=int(folder_id) if folder_id else None,
        name=file.filename or meta.get("storage_path") or "upload",
        description=(description or "").strip(),
        tags=(tags or "").strip(),
        kind="upload",
        storage=meta.get("storage") or storage,
        storage_path=meta.get("storage_path") or "",
        connection_id=meta.get("connection_id") or (conn.id if conn else None),
        mime_type=meta.get("mime_type") or file.content_type or "application/octet-stream",
        size_bytes=meta.get("size_bytes") or len(data),
        content_text=meta.get("content_text") or "",
        status="ready",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return _file_out(f, db)


@router.post("/import-cloud")
async def import_cloud(data: ImportCloudIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    storage = (data.storage or "").lower()
    if storage not in ("dropbox", "gcs", "google_cloud", "google_cloud_storage"):
        raise HTTPException(400, "storage must be dropbox or gcs")
    conn = _storage_connection(db, user, storage, data.connection_id)
    try:
        raw = await store.read_bytes(storage=storage, storage_path=data.path, connection=conn)
    except Exception as e:
        raise HTTPException(400, f"Import failed: {e}") from e
    name = data.name or data.path.rstrip("/").split("/")[-1] or "imported"
    text = store.extract_text(name, raw)
    f = models.KnowledgeFile(
        user_id=user.id,
        folder_id=data.folder_id,
        name=name,
        tags=(data.tags or "").strip(),
        kind="cloud",
        storage="dropbox" if storage == "dropbox" else "gcs",
        storage_path=data.path,
        connection_id=conn.id if conn else None,
        mime_type="application/octet-stream",
        size_bytes=len(raw),
        content_text=text[:500_000],
        status="ready",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return _file_out(f, db)


@router.get("/cloud/list")
async def cloud_list(
    storage: str,
    path: str = "",
    connection_id: int | None = None,
    bucket: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    storage = storage.lower()
    conn = _storage_connection(db, user, storage, connection_id)
    secrets = store.connection_secrets(conn)
    meta = store.connection_meta(conn)
    try:
        if storage == "dropbox":
            token = secrets.get("access_token") or secrets.get("token")
            items = await store.dropbox_list(token, path or "")
            return {"items": items, "storage": "dropbox"}
        if storage in ("gcs", "google_cloud", "google_cloud_storage"):
            b = bucket or secrets.get("bucket") or meta.get("bucket")
            if not b:
                raise HTTPException(400, "GCS bucket required on connection or query")
            sa = store.parse_service_account(
                secrets.get("service_account_json") or secrets.get("service_account")
            )
            if not sa and secrets.get("private_key") and secrets.get("client_email"):
                sa = {
                    "client_email": secrets["client_email"],
                    "private_key": secrets["private_key"].replace("\\n", "\n"),
                }
            items = await store.gcs_list(
                access_token=secrets.get("access_token"),
                bucket=b,
                prefix=path or "",
                service_account_json=sa,
            )
            return {"items": items, "storage": "gcs", "bucket": b}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    raise HTTPException(400, "Unsupported storage")


@router.patch("/files/{file_id}")
def update_file(file_id: int, data: FileUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    f = _owned_file(file_id, user, db)
    if data.name is not None:
        f.name = data.name.strip() or f.name
    if data.description is not None:
        f.description = data.description
    if data.tags is not None:
        f.tags = data.tags
    if data.folder_id is not None:
        if data.folder_id == 0:
            f.folder_id = None
        else:
            folder = db.get(models.KnowledgeFolder, data.folder_id)
            if not folder or folder.user_id != user.id:
                raise HTTPException(400, "Invalid folder")
            f.folder_id = data.folder_id
    if data.content is not None:
        f.content_text = data.content
        f.size_bytes = len(data.content.encode("utf-8"))
    if data.status is not None:
        if data.status not in ("draft", "ready", "archived"):
            raise HTTPException(400, "Invalid status")
        f.status = data.status
    f.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(f)
    return _file_out(f, db)


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    f = _owned_file(file_id, user, db)
    conn = db.get(models.IntegrationConnection, f.connection_id) if f.connection_id else None
    try:
        if f.storage_path and f.kind != "note":
            await store.delete_bytes(storage=f.storage, storage_path=f.storage_path, connection=conn)
    except Exception:
        pass
    db.query(models.AgentKnowledgeAccess).filter_by(resource_type="file", resource_id=f.id).delete()
    db.delete(f)
    db.commit()
    return {"ok": True}


def _agent_access_payload(agent_id: int, db: Session, user) -> dict:
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    access = db.query(models.AgentKnowledgeAccess).filter_by(agent_id=agent_id).all()
    items = []
    for row in access:
        item = {
            "id": row.id,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "permission": row.permission,
        }
        if row.resource_type == "file" and row.resource_id:
            f = db.get(models.KnowledgeFile, row.resource_id)
            item["name"] = f.name if f else f"file#{row.resource_id}"
        elif row.resource_type == "folder" and row.resource_id:
            folder = db.get(models.KnowledgeFolder, row.resource_id)
            item["name"] = folder.name if folder else f"folder#{row.resource_id}"
        else:
            item["name"] = "All training files"
        items.append(item)

    program = db.query(models.AgentProgram).filter_by(agent_id=agent_id).first()
    app_links = db.query(models.AgentIntegration).filter_by(agent_id=agent_id).all()
    apps = []
    for link in app_links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c:
            apps.append({
                "connection_id": c.id,
                "app_id": c.app_id,
                "display_name": c.display_name or c.app_id,
                "status": c.status,
                "permission": link.permission,
            })
    files = files_for_agent(db, a)
    return {
        "agent_id": agent_id,
        "agent_name": a.name,
        "access": items,
        "program": agent_program_out(program),
        "apps": apps,
        "resolved_files": [_file_out(f) for f in files],
        "context_preview": knowledge_context_for_agent(db, agent_id)[:2500],
    }


@router.get("/agents/{agent_id}/access")
def get_agent_access(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _agent_access_payload(agent_id, db, user)


@router.put("/agents/{agent_id}/access")
def set_agent_access(
    agent_id: int,
    data: AgentAccessIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    if data.replace:
        db.query(models.AgentKnowledgeAccess).filter_by(agent_id=agent_id).delete()
    for item in data.items or []:
        rt = (item.resource_type or "file").lower()
        if rt not in ("file", "folder", "all"):
            raise HTTPException(400, "resource_type must be file, folder, or all")
        if rt != "all":
            if not item.resource_id:
                raise HTTPException(400, f"resource_id required for {rt}")
            if rt == "file":
                f = db.get(models.KnowledgeFile, item.resource_id)
                if not f or f.user_id != user.id:
                    raise HTTPException(400, f"Invalid file {item.resource_id}")
            if rt == "folder":
                folder = db.get(models.KnowledgeFolder, item.resource_id)
                if not folder or folder.user_id != user.id:
                    raise HTTPException(400, f"Invalid folder {item.resource_id}")
        db.add(models.AgentKnowledgeAccess(
            agent_id=agent_id,
            resource_type=rt,
            resource_id=None if rt == "all" else item.resource_id,
            permission=item.permission or "read",
        ))
    db.commit()
    return _agent_access_payload(agent_id, db, user)


@router.put("/agents/{agent_id}/program")
def set_agent_program(
    agent_id: int,
    data: ProgramIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")

    program = db.query(models.AgentProgram).filter_by(agent_id=agent_id).first()
    if not program:
        program = models.AgentProgram(agent_id=agent_id)
        db.add(program)
    program.instructions = data.instructions or ""
    program.policy_json = json.dumps({
        "allow_all_files": bool(data.allow_all_files),
        "allow_all_apps": bool(data.allow_all_apps),
        "max_file_chars": int(data.max_file_chars or 14000),
    })
    program.updated_at = datetime.utcnow()

    if data.file_ids is not None or data.folder_ids is not None or data.allow_all_files:
        db.query(models.AgentKnowledgeAccess).filter_by(agent_id=agent_id).delete()
        if data.allow_all_files:
            db.add(models.AgentKnowledgeAccess(
                agent_id=agent_id, resource_type="all", resource_id=None, permission="read",
            ))
        else:
            for fid in data.file_ids or []:
                f = db.get(models.KnowledgeFile, int(fid))
                if f and f.user_id == user.id:
                    db.add(models.AgentKnowledgeAccess(
                        agent_id=agent_id, resource_type="file", resource_id=f.id, permission="read",
                    ))
            for folder_id in data.folder_ids or []:
                folder = db.get(models.KnowledgeFolder, int(folder_id))
                if folder and folder.user_id == user.id:
                    db.add(models.AgentKnowledgeAccess(
                        agent_id=agent_id, resource_type="folder", resource_id=folder.id, permission="read",
                    ))

    if data.connection_ids is not None or data.allow_all_apps:
        db.query(models.AgentIntegration).filter_by(agent_id=agent_id).delete()
        if data.allow_all_apps:
            for c in db.query(models.IntegrationConnection).filter_by(user_id=user.id, status="connected").all():
                db.add(models.AgentIntegration(connection_id=c.id, agent_id=agent_id, permission="full"))
        else:
            for cid in data.connection_ids or []:
                c = db.get(models.IntegrationConnection, int(cid))
                if c and c.user_id == user.id:
                    db.add(models.AgentIntegration(connection_id=c.id, agent_id=agent_id, permission="full"))

    db.commit()
    return _agent_access_payload(agent_id, db, user)


@router.get("/agents/{agent_id}/context")
def agent_context_preview(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    return {"agent_id": agent_id, "context": knowledge_context_for_agent(db, agent_id)}


@router.put("/files/{file_id}/agents")
def set_file_agents(
    file_id: int,
    data: FileAgentsIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    f = _owned_file(file_id, user, db)
    db.query(models.AgentKnowledgeAccess).filter_by(
        resource_type="file", resource_id=f.id,
    ).delete()
    linked = 0
    for aid in data.agent_ids or []:
        a = db.get(models.Agent, int(aid))
        if not a or a.user_id != user.id:
            continue
        db.add(models.AgentKnowledgeAccess(
            agent_id=a.id,
            resource_type="file",
            resource_id=f.id,
            permission="read",
        ))
        linked += 1
    db.commit()
    return {"file_id": f.id, "allocated": linked, "file": _file_out(f, db)}
