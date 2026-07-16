"""Local + Google Cloud Storage + Dropbox backends for training files."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from .integrations_service import secrets_from_row, meta_from_row

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
LOCAL_UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", str(_BACKEND_ROOT / "uploads")))
if os.getenv("VERCEL"):
    LOCAL_UPLOAD_ROOT = Path("/tmp/ai_assistant_uploads")

# Canonical storage ids
STORAGE_LOCAL = "local"
STORAGE_DROPBOX = "dropbox"
STORAGE_GCS = "gcs"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".xml", ".html", ".htm",
    ".yml", ".yaml", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".sql", ".log",
    ".ini", ".cfg", ".env.example", ".rst",
}


def normalize_storage(storage: str | None) -> str:
    s = (storage or "local").lower().strip()
    if s in ("gcs", "google_cloud", "google_cloud_storage"):
        return STORAGE_GCS
    if s == "dropbox":
        return STORAGE_DROPBOX
    if s in ("local", "", "note"):
        return STORAGE_LOCAL
    return s


def ensure_local_dir(user_id: int) -> Path:
    d = LOCAL_UPLOAD_ROOT / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(name: str) -> str:
    base = os.path.basename(name or "file")
    base = re.sub(r"[^\w.\- ()+]", "_", base).strip("._") or "file"
    return base[:180]


def extract_text(filename: str, data: bytes, mime: str | None = None) -> str:
    ext = Path(filename).suffix.lower()
    mime = (mime or mimetypes.guess_type(filename)[0] or "").lower()
    if ext in TEXT_EXTENSIONS or mime.startswith("text/") or mime in (
        "application/json", "application/xml", "application/javascript",
    ):
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return data.decode(enc)
            except Exception:
                continue
    return f"[Binary file: {filename}, {len(data)} bytes, type={mime or 'unknown'}]"


def connection_secrets(row) -> dict:
    """Alias — canonical implementation lives in integrations_service."""
    return secrets_from_row(row)


def connection_meta(row) -> dict:
    return meta_from_row(row)


def local_save(user_id: int, filename: str, data: bytes) -> dict:
    folder = ensure_local_dir(user_id)
    name = safe_filename(filename)
    unique = f"{uuid.uuid4().hex[:10]}_{name}"
    path = folder / unique
    path.write_bytes(data)
    return {
        "storage": "local",
        "storage_path": f"{user_id}/{unique}",
        "size_bytes": len(data),
        "absolute": str(path),
    }


def local_read(storage_path: str) -> bytes:
    path = LOCAL_UPLOAD_ROOT / storage_path
    if not path.is_file():
        raise FileNotFoundError(storage_path)
    return path.read_bytes()


def local_delete(storage_path: str) -> None:
    path = LOCAL_UPLOAD_ROOT / storage_path
    if path.is_file():
        path.unlink()


async def dropbox_upload(access_token: str, remote_path: str, data: bytes) -> dict:
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://content.dropboxapi.com/2/files/upload",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": json.dumps({
                    "path": remote_path,
                    "mode": "add",
                    "autorename": True,
                    "mute": True,
                }),
            },
            content=data,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Dropbox upload failed: {r.status_code} {r.text[:300]}")
        body = r.json()
        return {
            "storage": "dropbox",
            "storage_path": body.get("path_display") or remote_path,
            "size_bytes": body.get("size") or len(data),
            "remote_id": body.get("id"),
        }


async def dropbox_download(access_token: str, remote_path: str) -> bytes:
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Dropbox-API-Arg": json.dumps({"path": remote_path}),
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Dropbox download failed: {r.status_code} {r.text[:300]}")
        return r.content


async def dropbox_list(access_token: str, path: str = "") -> list[dict]:
    p = path if path.startswith("/") or path == "" else f"/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.dropboxapi.com/2/files/list_folder",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"path": p, "limit": 100},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Dropbox list failed: {r.status_code} {r.text[:300]}")
        entries = r.json().get("entries") or []
        return [
            {
                "name": e.get("name"),
                "path": e.get("path_display"),
                "tag": e.get(".tag"),
                "size": e.get("size"),
            }
            for e in entries
        ]


async def dropbox_delete(access_token: str, remote_path: str) -> None:
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            "https://api.dropboxapi.com/2/files/delete_v2",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"path": remote_path},
        )


def parse_service_account(raw: str | dict | None) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        if not text.startswith("{"):
            text = base64.b64decode(text).decode("utf-8")
        return json.loads(text)
    except Exception:
        return None


async def _gcs_sa_access_token(sa: dict) -> str:
    import time
    import jwt as pyjwt

    now = int(time.time())
    client_email = sa.get("client_email")
    private_key = sa.get("private_key")
    if not client_email or not private_key:
        raise RuntimeError("Service account JSON missing client_email/private_key")
    claim = {
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    assertion = pyjwt.encode(claim, private_key, algorithm="RS256")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GCS SA token failed: {r.status_code} {r.text[:300]}")
        return r.json()["access_token"]


def _parse_gs(path: str) -> tuple[str, str]:
    p = (path or "").strip()
    if p.startswith("gs://"):
        rest = p[5:]
        bucket, _, obj = rest.partition("/")
        return bucket, obj
    raise ValueError(f"Invalid GCS path: {path}")


async def gcs_upload(
    *,
    access_token: str | None,
    bucket: str,
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    service_account_json: dict | None = None,
) -> dict:
    bucket = bucket.strip()
    object_name = object_name.lstrip("/")
    if not bucket:
        raise RuntimeError("GCS bucket required")
    token = access_token
    if not token and service_account_json:
        token = await _gcs_sa_access_token(service_account_json)
    if not token:
        raise RuntimeError("GCS access token or service account JSON required")
    url = (
        f"https://storage.googleapis.com/upload/storage/v1/b/{quote(bucket, safe='')}/o"
        f"?uploadType=media&name={quote(object_name, safe='')}"
    )
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            content=data,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GCS upload failed: {r.status_code} {r.text[:400]}")
        body = r.json()
        return {
            "storage": "gcs",
            "storage_path": f"gs://{bucket}/{body.get('name') or object_name}",
            "size_bytes": int(body.get("size") or len(data)),
            "bucket": bucket,
            "object": body.get("name") or object_name,
        }


async def gcs_download(
    *,
    access_token: str | None,
    storage_path: str,
    service_account_json: dict | None = None,
) -> bytes:
    bucket, obj = _parse_gs(storage_path)
    token = access_token
    if not token and service_account_json:
        token = await _gcs_sa_access_token(service_account_json)
    if not token:
        raise RuntimeError("GCS access token required")
    url = (
        f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/"
        f"{quote(obj, safe='')}?alt=media"
    )
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise RuntimeError(f"GCS download failed: {r.status_code} {r.text[:300]}")
        return r.content


async def gcs_list(
    *,
    access_token: str | None,
    bucket: str,
    prefix: str = "",
    service_account_json: dict | None = None,
) -> list[dict]:
    token = access_token
    if not token and service_account_json:
        token = await _gcs_sa_access_token(service_account_json)
    if not token:
        raise RuntimeError("GCS access token required")
    url = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o"
    params = {"maxResults": 100}
    if prefix:
        params["prefix"] = prefix
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"GCS list failed: {r.status_code} {r.text[:300]}")
        items = r.json().get("items") or []
        return [
            {
                "name": i.get("name"),
                "path": f"gs://{bucket}/{i.get('name')}",
                "size": int(i.get("size") or 0),
                "tag": "file",
            }
            for i in items
        ]


def _sa_from_secrets(secrets: dict) -> dict | None:
    sa = parse_service_account(
        secrets.get("service_account_json")
        or secrets.get("private_key_json")
        or secrets.get("service_account")
    )
    if not sa and secrets.get("private_key") and secrets.get("client_email"):
        sa = {
            "client_email": secrets["client_email"],
            "private_key": secrets["private_key"].replace("\\n", "\n"),
        }
    return sa


async def save_bytes(
    *,
    user_id: int,
    filename: str,
    data: bytes,
    storage: str = "local",
    connection=None,
    remote_folder: str = "",
    mime: str | None = None,
) -> dict:
    storage = normalize_storage(storage)
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    text = extract_text(filename, data, mime)
    if len(text) > 500_000:
        text = text[:500_000] + "\n…[truncated for storage]"

    if storage == STORAGE_LOCAL:
        meta = local_save(user_id, filename, data)
        meta["content_text"] = text
        meta["mime_type"] = mime
        return meta

    secrets = connection_secrets(connection) if connection else {}
    meta_conn = connection_meta(connection) if connection else {}

    if storage == STORAGE_DROPBOX:
        token = secrets.get("access_token") or secrets.get("token") or ""
        if not token:
            raise RuntimeError("Dropbox connection missing access token")
        prefix = (remote_folder or meta_conn.get("root_path") or "/AI-Training").rstrip("/")
        remote = f"{prefix}/{safe_filename(filename)}"
        meta = await dropbox_upload(token, remote, data)
        meta["content_text"] = text
        meta["mime_type"] = mime
        meta["connection_id"] = connection.id if connection else None
        return meta

    if storage == STORAGE_GCS:
        bucket = secrets.get("bucket") or meta_conn.get("bucket") or os.getenv("GCS_BUCKET", "")
        sa = _sa_from_secrets(secrets)
        token = secrets.get("access_token") or None
        prefix = (remote_folder or meta_conn.get("prefix") or "ai-training").strip("/")
        object_name = f"{prefix}/{user_id}/{uuid.uuid4().hex[:8]}_{safe_filename(filename)}"
        meta = await gcs_upload(
            access_token=token,
            bucket=bucket,
            object_name=object_name,
            data=data,
            content_type=mime,
            service_account_json=sa,
        )
        meta["content_text"] = text
        meta["mime_type"] = mime
        meta["connection_id"] = connection.id if connection else None
        return meta

    meta = local_save(user_id, filename, data)
    meta["content_text"] = text
    meta["mime_type"] = mime
    return meta


async def read_bytes(*, storage: str, storage_path: str, connection=None) -> bytes:
    storage = normalize_storage(storage)
    if storage == STORAGE_LOCAL:
        return local_read(storage_path)
    secrets = connection_secrets(connection) if connection else {}
    if storage == STORAGE_DROPBOX:
        token = secrets.get("access_token") or secrets.get("token") or ""
        return await dropbox_download(token, storage_path)
    if storage == STORAGE_GCS:
        return await gcs_download(
            access_token=secrets.get("access_token"),
            storage_path=storage_path,
            service_account_json=_sa_from_secrets(secrets),
        )
    return local_read(storage_path)


async def delete_bytes(*, storage: str, storage_path: str, connection=None) -> None:
    storage = normalize_storage(storage)
    if storage == STORAGE_LOCAL:
        local_delete(storage_path)
        return
    secrets = connection_secrets(connection) if connection else {}
    if storage == STORAGE_DROPBOX:
        token = secrets.get("access_token") or secrets.get("token") or ""
        if token and storage_path:
            try:
                await dropbox_delete(token, storage_path)
            except Exception:
                pass
        return
    if storage == STORAGE_GCS and storage_path.startswith("gs://"):
        try:
            bucket, obj = _parse_gs(storage_path)
            sa = _sa_from_secrets(secrets)
            token = secrets.get("access_token")
            if not token and sa:
                token = await _gcs_sa_access_token(sa)
            if token:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.delete(
                        f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/{quote(obj, safe='')}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
        except Exception:
            pass
