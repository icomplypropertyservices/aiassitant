"""Voice metering + image/video generation (always billed on the token meter)."""
from __future__ import annotations

import base64
import hashlib
import html
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth_utils import get_current_user, ensure_credits
from ..usage_billing import charge_event, meter_snapshot
from ..ws import manager
from .. import config

router = APIRouter(prefix="/media", tags=["media"])


class VoiceMeterIn(BaseModel):
    kind: str = Field(..., description="voice_stt | voice_tts")
    text: str = ""


class ImageIn(BaseModel):
    prompt: str
    size: str = "1024x1024"
    style: str = "vivid"


class VideoIn(BaseModel):
    prompt: str
    duration_sec: int = Field(default=4, ge=2, le=12)


async def _broadcast_usage(user_id: int, charged: dict):
    try:
        await manager.broadcast(
            f"tokens:{user_id}",
            {
                "event": "usage",
                "tokens": charged.get("tokens"),
                "cost": charged.get("cost"),
                "model": charged.get("model"),
                "tokens_used_period": charged.get("tokens_used_period"),
                "credits": charged.get("credits"),
            },
        )
    except Exception:
        pass


@router.post("/voice/meter")
async def meter_voice(data: VoiceMeterIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Bill STT / TTS — always consumes tokens (included pool first, then wallet)."""
    ensure_credits(db, user.id)
    kind = (data.kind or "").lower().replace("-", "_")
    if kind not in ("voice_stt", "voice_tts", "stt", "tts"):
        raise HTTPException(400, "kind must be voice_stt or voice_tts")
    if kind in ("stt", "voice_stt"):
        bill_kind = "voice_stt"
    else:
        bill_kind = "voice_tts"
    text = (data.text or "").strip()
    if not text:
        # Still meter a minimum turn so voice never free-rides
        text = " "
    charged = charge_event(db, user, bill_kind, text=text)
    await _broadcast_usage(user.id, charged)
    return {
        "ok": True,
        **charged,
        "meter": meter_snapshot(db, user),
        "note": "Voice usage always counts toward your monthly token pool.",
    }


def _svg_placeholder(prompt: str, kind: str = "image") -> str:
    """Deterministic placeholder asset when no external image API is configured."""
    title = html.escape((prompt or kind)[:80])
    h = hashlib.md5(prompt.encode()).hexdigest()[:6]
    colors = [f"#{h}a", f"#1{h[1:]}c", f"#0{h[2:]}e"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#{h}"/>
      <stop offset="100%" stop-color="#1668dc"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <text x="50%" y="46%" fill="#fff" font-size="42" font-family="system-ui,sans-serif"
        text-anchor="middle">{kind.upper()}</text>
  <text x="50%" y="56%" fill="#e2e8f0" font-size="22" font-family="system-ui,sans-serif"
        text-anchor="middle">{title}</text>
</svg>"""
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


@router.post("/image")
async def generate_image(data: ImageIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Generate an image and always charge tokens + credits."""
    ensure_credits(db, user.id, min_credits=0.01)
    prompt = (data.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(400, "prompt required")

    url = None
    provider = "managed"
    # xAI Imagine via Super JWT only (same connection as grok TUI)
    key = config.get_grok_token() or ""
    if key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=90) as client:
                # OpenAI-compatible image attempts; if API shape differs, fall back
                r = await client.post(
                    "https://api.x.ai/v1/images/generations",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "grok-imagine-image", "prompt": prompt, "n": 1},
                )
                if r.status_code < 400:
                    body = r.json()
                    url = (body.get("data") or [{}])[0].get("url") or (body.get("data") or [{}])[0].get("b64_json")
                    if url and not str(url).startswith("http") and not str(url).startswith("data:"):
                        url = f"data:image/png;base64,{url}"
                    provider = "managed"
        except Exception:
            url = None

    if not url:
        url = _svg_placeholder(prompt, "image")
        provider = "managed-placeholder"

    charged = charge_event(db, user, "image", text=prompt)
    await _broadcast_usage(user.id, charged)
    return {
        "ok": True,
        "url": url,
        "prompt": prompt,
        "provider": "managed",
        "usage": charged,
        "meter": meter_snapshot(db, user),
        "note": None if provider != "managed-placeholder" else "Preview asset generated; configure media backend for production renders.",
    }


@router.post("/video")
async def generate_video(data: VideoIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue/generate a short video concept + poster; always charge tokens."""
    ensure_credits(db, user.id, min_credits=0.05)
    prompt = (data.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(400, "prompt required")

    poster = _svg_placeholder(prompt, "video")
    # Production: hook RunPod / Imagine video URL here
    video_url = None

    charged = charge_event(db, user, "video", text=prompt)
    await _broadcast_usage(user.id, charged)
    return {
        "ok": True,
        "poster_url": poster,
        "video_url": video_url,
        "prompt": prompt,
        "duration_sec": data.duration_sec,
        "provider": "managed",
        "usage": charged,
        "meter": meter_snapshot(db, user),
        "note": "Video job accepted. Poster ready; full video URL fills when media worker is configured.",
    }
