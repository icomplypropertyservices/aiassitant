import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config
from ..auth_utils import get_current_user

router = APIRouter(prefix="/media", tags=["media"])


def _ensure_upload_dir() -> Path:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return config.UPLOAD_DIR


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    content_type = (file.content_type or "").lower()
    if content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            400,
            f"Unsupported type {content_type}. Allowed: {list(config.ALLOWED_IMAGE_TYPES)}",
        )
    data = await file.read()
    max_bytes = config.UPLOAD_MAX_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(400, f"File too large (max {config.UPLOAD_MAX_MB}MB)")
    if len(data) < 32:
        raise HTTPException(400, "File empty or too small")

    ext = config.ALLOWED_IMAGE_TYPES[content_type]
    user_dir = _ensure_upload_dir() / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{ext}"
    path = user_dir / name
    path.write_bytes(data)

    rel = f"/api/media/files/{user.id}/{name}"
    absolute = f"{config.PUBLIC_API_URL}{rel}"
    return {
        "url": absolute,
        "path": rel,
        "filename": name,
        "content_type": content_type,
        "size": len(data),
    }


@router.get("/files/{user_id}/{filename}")
def get_file(user_id: int, filename: str):
    # prevent path traversal
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = config.UPLOAD_DIR / str(user_id) / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path)
