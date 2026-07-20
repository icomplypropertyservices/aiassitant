"""Voice metering + image/video generation (always billed on the token meter).

Uses xAI Grok Imagine when credentials are available:
  POST https://api.x.ai/v1/images/generations
  POST https://api.x.ai/v1/images/edits
  POST https://api.x.ai/v1/videos/generations  (+ poll GET /v1/videos/{request_id})

Skill handlers and HTTP routes share the same helpers so status/errors stay honest.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth_utils import get_current_user, ensure_credits
from ..usage_billing import charge_event, meter_snapshot
from ..ws import manager
from .. import config

log = logging.getLogger("aba.media")

router = APIRouter(prefix="/media", tags=["media"])

XAI_IMAGES_URL = "https://api.x.ai/v1/images/generations"
XAI_IMAGES_EDIT_URL = "https://api.x.ai/v1/images/edits"
XAI_VIDEOS_URL = "https://api.x.ai/v1/videos/generations"
XAI_VIDEO_STATUS_URL = "https://api.x.ai/v1/videos/{request_id}"

# Default Imagine models (override via env if xAI renames)
XAI_IMAGE_MODEL = getattr(config, "XAI_IMAGE_MODEL", None) or "grok-imagine-image"
XAI_IMAGE_MODEL_QUALITY = getattr(config, "XAI_IMAGE_MODEL_QUALITY", None) or "grok-imagine-image-quality"
XAI_VIDEO_MODEL = getattr(config, "XAI_VIDEO_MODEL", None) or "grok-imagine-video"

# Skill path: poll a short window so chat doesn't hang; return request_id if still pending
VIDEO_POLL_INTERVAL_SEC = 4.0
VIDEO_POLL_TIMEOUT_SEC = 75.0


class VoiceMeterIn(BaseModel):
    kind: str = Field(..., description="voice_stt | voice_tts")
    text: str = ""


class ImageIn(BaseModel):
    prompt: str
    size: str = "1024x1024"
    style: str = "vivid"


class ImageEditIn(BaseModel):
    prompt: str
    image_url: str = Field(..., description="Public URL or data:image/... URI of source image")
    style: str = ""


class VideoIn(BaseModel):
    prompt: str
    duration_sec: int = Field(default=6, ge=1, le=15)
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    image_url: str | None = None


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


def _svg_placeholder(prompt: str, kind: str = "image") -> str:
    """Deterministic placeholder asset when no external image API is configured."""
    title = html.escape((prompt or kind)[:80])
    h = hashlib.md5((prompt or kind).encode()).hexdigest()[:6]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#{h}"/>
      <stop offset="100%" stop-color="#1668dc"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <text x="50%" y="46%" fill="#fff" font-size="42" font-family="system-ui,sans-serif"
        text-anchor="middle">{html.escape(kind.upper())}</text>
  <text x="50%" y="56%" fill="#e2e8f0" font-size="22" font-family="system-ui,sans-serif"
        text-anchor="middle">{title}</text>
</svg>"""
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


def _normalize_image_payload(item: dict | None) -> str | None:
    """Extract http(s) URL or data URI from an Imagine image object."""
    if not item or not isinstance(item, dict):
        return None
    url = item.get("url")
    if url and str(url).startswith(("http://", "https://", "data:")):
        return str(url)
    b64 = item.get("b64_json") or item.get("base64")
    if b64:
        raw = str(b64)
        if raw.startswith("data:"):
            return raw
        return f"data:image/png;base64,{raw}"
    return None


def _http_error_detail(status: int, body_text: str, *, limit: int = 280) -> str:
    text = (body_text or "").strip().replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    if not text:
        return f"xAI HTTP {status}"
    return f"xAI HTTP {status}: {text}"


def _classify_xai_http_error(status: int, body_text: str = "") -> dict[str, Any]:
    """Map xAI HTTP failures to agent-safe codes.

    401/402/403 are terminal for this run — agents must not re-call media skills.
    """
    detail = _http_error_detail(status, body_text)
    low = (body_text or "").lower()
    status_i = int(status or 0)

    # Billing / quota / spending limit (402 Payment Required or body signals)
    if status_i == 402 or any(
        m in low
        for m in (
            "insufficient",
            "spending limit",
            "spending_limit",
            "quota",
            "credits",
            "payment required",
            "out of credits",
            "balance",
        )
    ):
        return {
            "error": (
                f"{detail}. xAI Imagine credits/quota exhausted or payment required. "
                "DO NOT retry generate_image/edit_image/generate_video/generate_ad_creative/"
                "generate_product_shot until the workspace tops up xAI billing or XAI_API_KEY credits."
            ),
            "error_code": "xai_credits",
            "retryable": False,
            "agent_guidance": (
                "STOP: xAI media credits/quota unavailable. Tell the human to add xAI API credits "
                "or fix billing. Do not call media skills again in this conversation."
            ),
        }

    if status_i in (401, 403) or any(
        m in low
        for m in ("permission denied", "permission-denied", "unauthorized", "invalid api key", "invalid_api_key")
    ):
        return {
            "error": (
                f"{detail}. xAI auth/permission denied for Imagine. "
                "DO NOT retry media skills — fix XAI_API_KEY or account permissions first."
            ),
            "error_code": "xai_permission",
            "retryable": False,
            "agent_guidance": (
                "STOP: xAI refused this key (401/403). Do not thrash media tools. "
                "Ask a human to verify XAI_API_KEY / team access."
            ),
        }

    if status_i == 429:
        return {
            "error": (
                f"{detail}. xAI rate limit. Wait before retrying; do not loop generate_* immediately."
            ),
            "error_code": "xai_rate_limit",
            "retryable": True,
            "agent_guidance": (
                "Rate limited. Wait and try once later if the human still needs the asset; "
                "do not spam media skills."
            ),
        }

    return {
        "error": detail,
        "error_code": "xai_http",
        "retryable": status_i >= 500,
        "agent_guidance": (
            "Provider error. Do not rapidly re-call the same media skill; report the error to the human."
            if status_i < 500
            else "Transient provider error. One careful retry is OK if the human still needs the asset."
        ),
    }


def _resolve_image_model(style: str | None = None, quality: str | None = None) -> str:
    q = (quality or style or "").strip().lower()
    if q in ("quality", "premium", "high", "hq", "best"):
        return XAI_IMAGE_MODEL_QUALITY
    return XAI_IMAGE_MODEL


async def xai_generate_image(
    prompt: str,
    *,
    style: str | None = None,
    size: str | None = None,
    n: int = 1,
    allow_placeholder: bool = True,
) -> dict[str, Any]:
    """
    Call xAI Imagine image generation.

    Returns:
      ok, url, provider (xai | placeholder | none), model, error, note,
      error_code, retryable, agent_guidance (when failed / degraded)
    """
    prompt = (prompt or "").strip()
    if len(prompt) < 3:
        return {
            "ok": False,
            "url": None,
            "provider": "none",
            "model": None,
            "error": "prompt is required (min 3 chars)",
            "error_code": "validation",
            "retryable": False,
            "note": None,
            "agent_guidance": "Fix the prompt (min 3 chars) before calling again.",
        }

    model = _resolve_image_model(style)
    key = config.get_grok_token() or ""
    if not key:
        if allow_placeholder:
            return {
                "ok": True,
                "url": _svg_placeholder(prompt, "image"),
                "provider": "placeholder",
                "model": None,
                "error": None,
                "error_code": "xai_credentials_missing",
                "retryable": False,
                "note": (
                    "Preview placeholder only — no xAI credentials. "
                    "Set XAI_API_KEY (production) or sign in with Grok Super (dev) for real images. "
                    "Premium still bills."
                ),
                "agent_guidance": (
                    "No xAI key configured — placeholder only. Do not re-call generate_image "
                    "hoping for a real asset; ask human to set XAI_API_KEY."
                ),
            }
        return {
            "ok": False,
            "url": None,
            "provider": "none",
            "model": None,
            "error": (
                "xAI credentials missing. Set XAI_API_KEY on the server "
                "or configure Grok Super session (dev)."
            ),
            "error_code": "xai_credentials_missing",
            "retryable": False,
            "note": None,
            "agent_guidance": (
                "STOP: no xAI credentials. Do not thrash media skills."
            ),
        }

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": max(1, min(int(n or 1), 4)),
    }
    # size is accepted for API compatibility; xAI may ignore or map via aspect
    if size:
        payload["size"] = size

    try:
        import httpx
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                XAI_IMAGES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            body_text = r.text or ""
            if r.status_code >= 400:
                classified = _classify_xai_http_error(r.status_code, body_text)
                log.warning("xai_image_gen failed: %s", classified.get("error"))
                # Terminal billing/auth: never paper over with placeholder (stops agent thrash)
                if classified.get("retryable") is False and classified.get("error_code") in (
                    "xai_credits",
                    "xai_permission",
                ):
                    return {
                        "ok": False,
                        "url": None,
                        "provider": "xai",
                        "model": model,
                        "error": classified["error"],
                        "error_code": classified["error_code"],
                        "retryable": False,
                        "note": "Premium may still be billed for the attempt. Do not retry media skills.",
                        "agent_guidance": classified.get("agent_guidance"),
                    }
                if allow_placeholder:
                    return {
                        "ok": True,
                        "url": _svg_placeholder(prompt, "image"),
                        "provider": "placeholder",
                        "model": model,
                        "error": classified["error"],
                        "error_code": classified.get("error_code") or "xai_http",
                        "retryable": bool(classified.get("retryable")),
                        "note": (
                            f"xAI image API failed ({classified['error']}). "
                            "Returning placeholder. Premium still billed."
                        ),
                        "agent_guidance": classified.get("agent_guidance"),
                    }
                return {
                    "ok": False,
                    "url": None,
                    "provider": "xai",
                    "model": model,
                    "error": classified["error"],
                    "error_code": classified.get("error_code") or "xai_http",
                    "retryable": bool(classified.get("retryable")),
                    "note": None,
                    "agent_guidance": classified.get("agent_guidance"),
                }
            try:
                body = r.json()
            except Exception:
                body = {}
            items = body.get("data") or []
            url = _normalize_image_payload(items[0] if items else None)
            if not url:
                # Some SDKs return top-level url
                url = body.get("url") if isinstance(body.get("url"), str) else None
            if url:
                return {
                    "ok": True,
                    "url": url,
                    "provider": "xai",
                    "model": model,
                    "error": None,
                    "error_code": None,
                    "retryable": None,
                    "note": None,
                    "agent_guidance": None,
                }
            detail = "xAI returned no image URL"
            if allow_placeholder:
                return {
                    "ok": True,
                    "url": _svg_placeholder(prompt, "image"),
                    "provider": "placeholder",
                    "model": model,
                    "error": detail,
                    "error_code": "xai_empty",
                    "retryable": True,
                    "note": f"{detail}. Returning placeholder. Premium still billed.",
                    "agent_guidance": "Empty image response — one retry OK if human still needs the asset.",
                }
            return {
                "ok": False,
                "url": None,
                "provider": "xai",
                "model": model,
                "error": detail,
                "error_code": "xai_empty",
                "retryable": True,
                "note": None,
                "agent_guidance": "Empty image response — one retry OK if human still needs the asset.",
            }
    except Exception as e:
        detail = f"xAI image request error: {type(e).__name__}: {e}"
        log.warning(detail)
        if allow_placeholder:
            return {
                "ok": True,
                "url": _svg_placeholder(prompt, "image"),
                "provider": "placeholder",
                "model": model,
                "error": detail,
                "error_code": "xai_network",
                "retryable": True,
                "note": f"{detail}. Returning placeholder. Premium still billed.",
                "agent_guidance": "Network/provider error with placeholder. Do not loop retries.",
            }
        return {
            "ok": False,
            "url": None,
            "provider": "xai",
            "model": model,
            "error": detail,
            "error_code": "xai_network",
            "retryable": True,
            "note": None,
            "agent_guidance": "Network/provider error. One careful retry max.",
        }


async def xai_edit_image(
    prompt: str,
    image_url: str,
    *,
    style: str | None = None,
    allow_placeholder: bool = False,
) -> dict[str, Any]:
    """Edit a source image via xAI Imagine /images/edits."""
    prompt = (prompt or "").strip()
    image_url = (image_url or "").strip()
    if len(prompt) < 3:
        return {
            "ok": False,
            "url": None,
            "provider": "none",
            "model": None,
            "error": "prompt is required (min 3 chars)",
            "error_code": "validation",
            "retryable": False,
            "note": None,
            "agent_guidance": "Fix the edit prompt (min 3 chars) before calling again.",
        }
    if not image_url or not (
        image_url.startswith(("http://", "https://", "data:"))
    ):
        return {
            "ok": False,
            "url": None,
            "provider": "none",
            "model": None,
            "error": "image_url must be a public http(s) URL or data:image/... URI",
            "error_code": "validation",
            "retryable": False,
            "note": None,
            "agent_guidance": "Provide a valid public image URL or data URI.",
        }

    model = _resolve_image_model(style)
    key = config.get_grok_token() or ""
    if not key:
        return {
            "ok": False,
            "url": None,
            "provider": "none",
            "model": None,
            "error": (
                "xAI credentials missing. Set XAI_API_KEY on the server "
                "or configure Grok Super session (dev)."
            ),
            "error_code": "xai_credentials_missing",
            "retryable": False,
            "note": None,
            "agent_guidance": (
                "STOP: no xAI credentials for image edit. Do not thrash edit_image."
            ),
        }

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "image": {"url": image_url, "type": "image_url"},
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                XAI_IMAGES_EDIT_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            body_text = r.text or ""
            if r.status_code >= 400:
                classified = _classify_xai_http_error(r.status_code, body_text)
                log.warning("xai_image_edit failed: %s", classified.get("error"))
                return {
                    "ok": False,
                    "url": None,
                    "provider": "xai",
                    "model": model,
                    "error": classified["error"],
                    "error_code": classified.get("error_code") or "xai_http",
                    "retryable": bool(classified.get("retryable")),
                    "note": (
                        "Premium may still be billed. Do not retry media skills if credits/auth failed."
                        if classified.get("retryable") is False
                        else None
                    ),
                    "agent_guidance": classified.get("agent_guidance"),
                }
            try:
                body = r.json()
            except Exception:
                body = {}
            items = body.get("data") or []
            url = _normalize_image_payload(items[0] if items else None)
            if not url and isinstance(body.get("url"), str):
                url = body["url"]
            if url:
                return {
                    "ok": True,
                    "url": url,
                    "provider": "xai",
                    "model": model,
                    "error": None,
                    "error_code": None,
                    "retryable": None,
                    "note": None,
                    "agent_guidance": None,
                }
            return {
                "ok": False,
                "url": None,
                "provider": "xai",
                "model": model,
                "error": "xAI edit returned no image URL",
                "error_code": "xai_empty",
                "retryable": True,
                "note": None,
                "agent_guidance": "Empty edit response — one retry OK if human still needs the asset.",
            }
    except Exception as e:
        detail = f"xAI image edit error: {type(e).__name__}: {e}"
        log.warning(detail)
        return {
            "ok": False,
            "url": None,
            "provider": "xai",
            "model": model,
            "error": detail,
            "error_code": "xai_network",
            "retryable": True,
            "note": None,
            "agent_guidance": "Network/provider error. One careful retry max.",
        }


async def xai_generate_video(
    prompt: str,
    *,
    duration_sec: int = 6,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    image_url: str | None = None,
    poll_timeout_sec: float = VIDEO_POLL_TIMEOUT_SEC,
    poll_interval_sec: float = VIDEO_POLL_INTERVAL_SEC,
) -> dict[str, Any]:
    """
    Start xAI video generation and poll briefly.

    Status values:
      ready — video_url present
      pending — job accepted, still rendering (request_id set)
      failed — API rejected or job failed
      unavailable — no credentials / network could not start
    Always includes poster_url for UI.
    """
    prompt = (prompt or "").strip()
    poster = _svg_placeholder(prompt or "video", "video")
    if len(prompt) < 3:
        return {
            "ok": False,
            "video_url": None,
            "poster_url": poster,
            "request_id": None,
            "status": "failed",
            "provider": "none",
            "model": None,
            "duration_sec": duration_sec,
            "error": "prompt is required (min 3 chars)",
            "note": None,
        }

    try:
        duration = max(1, min(int(duration_sec or 6), 15))
    except (TypeError, ValueError):
        duration = 6

    key = config.get_grok_token() or ""
    if not key:
        return {
            "ok": True,
            "video_url": None,
            "poster_url": poster,
            "request_id": None,
            "status": "unavailable",
            "provider": "placeholder",
            "model": None,
            "duration_sec": duration,
            "error": "xAI credentials missing",
            "error_code": "xai_credentials_missing",
            "retryable": False,
            "note": (
                "Poster only — no xAI credentials for video. "
                "Set XAI_API_KEY (production) or Grok Super session (dev). "
                "Premium still bills."
            ),
            "agent_guidance": (
                "No xAI key — poster placeholder only. Do not re-call generate_video "
                "for a real MP4 until credentials are configured."
            ),
        }

    model = XAI_VIDEO_MODEL
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": (aspect_ratio or "16:9").strip() or "16:9",
        "resolution": (resolution or "720p").strip() or "720p",
    }
    img = (image_url or "").strip()
    if img and img.startswith(("http://", "https://", "data:")):
        payload["image"] = {"url": img}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                XAI_VIDEOS_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
            body_text = r.text or ""
            if r.status_code >= 400:
                classified = _classify_xai_http_error(r.status_code, body_text)
                log.warning("xai_video_start failed: %s", classified.get("error"))
                return {
                    "ok": False,
                    "video_url": None,
                    "poster_url": poster,
                    "request_id": None,
                    "status": "failed",
                    "provider": "xai",
                    "model": model,
                    "duration_sec": duration,
                    "error": classified["error"],
                    "error_code": classified.get("error_code") or "xai_http",
                    "retryable": bool(classified.get("retryable")),
                    "note": f"Video job could not start. {classified['error']}",
                    "agent_guidance": classified.get("agent_guidance"),
                }
            try:
                start_body = r.json()
            except Exception:
                start_body = {}
            request_id = start_body.get("request_id") or start_body.get("id")
            # Rare: synchronous complete
            if start_body.get("status") == "done" or start_body.get("video"):
                vid = (start_body.get("video") or {}) if isinstance(start_body.get("video"), dict) else {}
                vurl = vid.get("url") or start_body.get("url")
                if vurl:
                    return {
                        "ok": True,
                        "video_url": vurl,
                        "poster_url": poster,
                        "request_id": request_id,
                        "status": "ready",
                        "provider": "xai",
                        "model": model,
                        "duration_sec": vid.get("duration") or duration,
                        "error": None,
                        "error_code": None,
                        "retryable": None,
                        "note": None,
                        "agent_guidance": None,
                    }
            if not request_id:
                return {
                    "ok": False,
                    "video_url": None,
                    "poster_url": poster,
                    "request_id": None,
                    "status": "failed",
                    "provider": "xai",
                    "model": model,
                    "duration_sec": duration,
                    "error": "xAI video start returned no request_id",
                    "error_code": "xai_empty",
                    "retryable": True,
                    "note": "Video job could not be tracked.",
                    "agent_guidance": "No request_id — one careful retry max if human still needs video.",
                }

            # Poll until ready / failed / timeout
            deadline = time.monotonic() + float(poll_timeout_sec or VIDEO_POLL_TIMEOUT_SEC)
            last_status = "pending"
            while time.monotonic() < deadline:
                await asyncio.sleep(float(poll_interval_sec or VIDEO_POLL_INTERVAL_SEC))
                pr = await client.get(
                    XAI_VIDEO_STATUS_URL.format(request_id=request_id),
                    headers={"Authorization": f"Bearer {key}"},
                )
                if pr.status_code >= 400:
                    # Auth/credits on poll are terminal; transient poll errors keep waiting
                    if pr.status_code in (401, 402, 403):
                        classified = _classify_xai_http_error(pr.status_code, pr.text or "")
                        return {
                            "ok": False,
                            "video_url": None,
                            "poster_url": poster,
                            "request_id": request_id,
                            "status": "failed",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": duration,
                            "error": classified["error"],
                            "error_code": classified.get("error_code") or "xai_http",
                            "retryable": False,
                            "note": "Video poll hit auth/credits failure. Premium still billed.",
                            "agent_guidance": classified.get("agent_guidance"),
                        }
                    last_status = "pending"
                    continue
                try:
                    data = pr.json()
                except Exception:
                    continue
                st = (data.get("status") or "").lower()
                last_status = st or last_status
                if st == "done":
                    vid = data.get("video") or {}
                    vurl = vid.get("url") if isinstance(vid, dict) else None
                    if vurl:
                        return {
                            "ok": True,
                            "video_url": vurl,
                            "poster_url": poster,
                            "request_id": request_id,
                            "status": "ready",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": (vid.get("duration") if isinstance(vid, dict) else None) or duration,
                            "error": None,
                            "error_code": None,
                            "retryable": None,
                            "note": None,
                            "agent_guidance": None,
                        }
                    return {
                        "ok": False,
                        "video_url": None,
                        "poster_url": poster,
                        "request_id": request_id,
                        "status": "failed",
                        "provider": "xai",
                        "model": model,
                        "duration_sec": duration,
                        "error": "Video marked done but no URL returned",
                        "error_code": "xai_empty",
                        "retryable": False,
                        "note": None,
                        "agent_guidance": "Job done without URL — report to human; do not re-submit same job.",
                    }
                if st in ("failed", "expired"):
                    err = data.get("error") or {}
                    msg = None
                    if isinstance(err, dict):
                        msg = err.get("message") or err.get("code")
                    elif isinstance(err, str):
                        msg = err
                    return {
                        "ok": False,
                        "video_url": None,
                        "poster_url": poster,
                        "request_id": request_id,
                        "status": st,
                        "provider": "xai",
                        "model": model,
                        "duration_sec": duration,
                        "error": msg or f"Video job {st}",
                        "error_code": f"xai_video_{st}",
                        "retryable": False,
                        "note": f"xAI video job {st}. Premium still billed.",
                        "agent_guidance": (
                            f"Video job {st} (request_id={request_id}). "
                            "Do not immediately re-call generate_video with the same prompt."
                        ),
                    }

            return {
                "ok": True,
                "video_url": None,
                "poster_url": poster,
                "request_id": request_id,
                "status": "pending",
                "provider": "xai",
                "model": model,
                "duration_sec": duration,
                "error": None,
                "error_code": None,
                "retryable": None,
                "note": (
                    f"Video still rendering (request_id={request_id}, last_status={last_status}). "
                    "Poster ready now; use check_video / GET /media/video/{request_id} for the final MP4. "
                    "Premium billed on generate only."
                ),
                "agent_guidance": (
                    f"Job accepted and still pending (request_id={request_id}). "
                    "Share the poster + request_id. Next: call check_video with this request_id "
                    "(or GET /media/video/{request_id}). "
                    "Do NOT start a new generate_video for the same brief while this job is open."
                ),
                "next_skill": "check_video",
            }
    except Exception as e:
        detail = f"xAI video request error: {type(e).__name__}: {e}"
        log.warning(detail)
        return {
            "ok": False,
            "video_url": None,
            "poster_url": poster,
            "request_id": None,
            "status": "failed",
            "provider": "xai",
            "model": model,
            "duration_sec": duration,
            "error": detail,
            "error_code": "xai_network",
            "retryable": True,
            "note": "Video generation failed before a job was confirmed.",
            "agent_guidance": "Network/provider error before job start. One careful retry max.",
        }


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


@router.post("/image")
async def generate_image(data: ImageIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Generate an image and always charge tokens + credits (premium)."""
    ensure_credits(db, user.id, min_credits=0.01)
    prompt = (data.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(400, "prompt required")

    result = await xai_generate_image(prompt, style=data.style, size=data.size, allow_placeholder=True)
    charged = charge_event(db, user, "image", text=prompt)
    await _broadcast_usage(user.id, charged)
    # Terminal xAI billing/auth → clear 402 so clients/agents stop thrashing
    if result.get("error_code") in ("xai_credits", "xai_permission") and not result.get("ok"):
        raise HTTPException(
            402 if result.get("error_code") == "xai_credits" else 403,
            result.get("error") or "xAI media unavailable",
        )
    return {
        "ok": bool(result.get("ok")),
        "url": result.get("url"),
        "prompt": prompt,
        "provider": result.get("provider") or "managed",
        "model": result.get("model"),
        "error": result.get("error"),
        "error_code": result.get("error_code"),
        "retryable": result.get("retryable"),
        "usage": charged,
        "meter": meter_snapshot(db, user),
        "note": result.get("note") or "Premium image generation billed.",
        "agent_guidance": result.get("agent_guidance"),
    }


@router.post("/image/edit")
async def edit_image(data: ImageEditIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Edit an existing image with a text instruction; always charges image meter (premium)."""
    ensure_credits(db, user.id, min_credits=0.01)
    prompt = (data.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(400, "prompt required")
    if not (data.image_url or "").strip():
        raise HTTPException(400, "image_url required")

    result = await xai_edit_image(prompt, data.image_url, style=data.style or None)
    if not result.get("ok"):
        # Still bill failed attempts that hit the API? Prefer bill only on attempt with credentials path.
        # Consistent with premium: charge when user requested premium work.
        charged = charge_event(db, user, "image", text=prompt)
        await _broadcast_usage(user.id, charged)
        code = result.get("error_code")
        if code == "xai_credits":
            http_status = 402
        elif code in ("xai_permission", "xai_credentials_missing"):
            http_status = 403
        elif result.get("provider") == "xai":
            http_status = 502
        else:
            http_status = 400
        raise HTTPException(http_status, result.get("error") or "image edit failed")
    charged = charge_event(db, user, "image", text=prompt)
    await _broadcast_usage(user.id, charged)
    return {
        "ok": True,
        "url": result.get("url"),
        "prompt": prompt,
        "image_url": data.image_url,
        "provider": result.get("provider") or "xai",
        "model": result.get("model"),
        "usage": charged,
        "meter": meter_snapshot(db, user),
        "note": "Premium image edit billed.",
    }


async def xai_check_video(
    request_id: str,
    *,
    prompt_hint: str | None = None,
    poll_timeout_sec: float = 0.0,
    poll_interval_sec: float = VIDEO_POLL_INTERVAL_SEC,
) -> dict[str, Any]:
    """
    Poll an existing xAI video job by request_id (no new generation).

    poll_timeout_sec=0 → single status GET (default for check_video skill).
    Positive timeout → brief wait loop (same statuses as generate).
    """
    rid = (request_id or "").strip()
    poster = _svg_placeholder((prompt_hint or rid or "video")[:80], "video")
    if not rid or len(rid) < 4:
        return {
            "ok": False,
            "video_url": None,
            "poster_url": poster,
            "request_id": rid or None,
            "status": "failed",
            "provider": "none",
            "model": XAI_VIDEO_MODEL,
            "duration_sec": None,
            "error": "request_id is required (from generate_video when status=pending)",
            "error_code": "validation",
            "retryable": False,
            "note": None,
            "agent_guidance": "Pass request_id from the earlier generate_video result.",
        }

    key = config.get_grok_token() or ""
    if not key:
        return {
            "ok": False,
            "video_url": None,
            "poster_url": poster,
            "request_id": rid,
            "status": "unavailable",
            "provider": "placeholder",
            "model": XAI_VIDEO_MODEL,
            "duration_sec": None,
            "error": "xAI credentials missing — cannot poll video job",
            "error_code": "xai_credentials_missing",
            "retryable": False,
            "note": "Set XAI_API_KEY to check pending video jobs.",
            "agent_guidance": (
                "No xAI key — cannot complete pending video. "
                "Do not call generate_video again for the same brief."
            ),
        }

    model = XAI_VIDEO_MODEL
    timeout = max(0.0, float(poll_timeout_sec or 0))
    interval = max(1.0, float(poll_interval_sec or VIDEO_POLL_INTERVAL_SEC))
    deadline = time.monotonic() + timeout
    first = True

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            while first or time.monotonic() < deadline:
                if not first:
                    await asyncio.sleep(interval)
                first = False
                pr = await client.get(
                    XAI_VIDEO_STATUS_URL.format(request_id=rid),
                    headers={"Authorization": f"Bearer {key}"},
                )
                body_text = pr.text or ""
                if pr.status_code >= 400:
                    classified = _classify_xai_http_error(pr.status_code, body_text)
                    if classified.get("error_code") in ("xai_credits", "xai_permission"):
                        return {
                            "ok": False,
                            "video_url": None,
                            "poster_url": poster,
                            "request_id": rid,
                            "status": "failed",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": None,
                            "error": classified["error"],
                            "error_code": classified.get("error_code"),
                            "retryable": False,
                            "note": "Status poll hit auth/credits failure.",
                            "agent_guidance": classified.get("agent_guidance"),
                        }
                    # 404 / transient: still pending or unknown
                    if pr.status_code == 404:
                        return {
                            "ok": False,
                            "video_url": None,
                            "poster_url": poster,
                            "request_id": rid,
                            "status": "failed",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": None,
                            "error": f"Video job not found (request_id={rid})",
                            "error_code": "xai_not_found",
                            "retryable": False,
                            "note": None,
                            "agent_guidance": (
                                "request_id not found. Do not invent a new generate_video "
                                "unless the human wants a fresh job."
                            ),
                        }
                    if timeout <= 0:
                        return {
                            "ok": True,
                            "video_url": None,
                            "poster_url": poster,
                            "request_id": rid,
                            "status": "pending",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": None,
                            "error": classified.get("error"),
                            "error_code": classified.get("error_code") or "xai_http",
                            "retryable": True,
                            "note": "Status poll soft-failed; treat as still pending.",
                            "agent_guidance": (
                                f"Still pending or poll error (request_id={rid}). "
                                "Wait, then call check_video again — do not generate_video."
                            ),
                        }
                    continue
                try:
                    data = pr.json()
                except Exception:
                    if timeout <= 0:
                        break
                    continue
                st = (data.get("status") or "").lower()
                if st == "done" or data.get("video"):
                    vid = data.get("video") or {}
                    vurl = vid.get("url") if isinstance(vid, dict) else None
                    if not vurl and isinstance(data.get("url"), str):
                        vurl = data["url"]
                    if vurl:
                        return {
                            "ok": True,
                            "video_url": vurl,
                            "poster_url": poster,
                            "request_id": rid,
                            "status": "ready",
                            "provider": "xai",
                            "model": model,
                            "duration_sec": (vid.get("duration") if isinstance(vid, dict) else None),
                            "error": None,
                            "error_code": None,
                            "retryable": None,
                            "note": "Video ready from prior generate_video job.",
                            "agent_guidance": None,
                        }
                    return {
                        "ok": False,
                        "video_url": None,
                        "poster_url": poster,
                        "request_id": rid,
                        "status": "failed",
                        "provider": "xai",
                        "model": model,
                        "duration_sec": None,
                        "error": "Video marked done but no URL returned",
                        "error_code": "xai_empty",
                        "retryable": False,
                        "note": None,
                        "agent_guidance": "Job done without URL — report to human.",
                    }
                if st in ("failed", "expired"):
                    err = data.get("error") or {}
                    msg = None
                    if isinstance(err, dict):
                        msg = err.get("message") or err.get("code")
                    elif isinstance(err, str):
                        msg = err
                    return {
                        "ok": False,
                        "video_url": None,
                        "poster_url": poster,
                        "request_id": rid,
                        "status": st,
                        "provider": "xai",
                        "model": model,
                        "duration_sec": None,
                        "error": msg or f"Video job {st}",
                        "error_code": f"xai_video_{st}",
                        "retryable": False,
                        "note": f"xAI video job {st}.",
                        "agent_guidance": (
                            f"Video job {st} (request_id={rid}). "
                            "Only re-run generate_video if the human wants a new attempt."
                        ),
                    }
                # pending / processing / empty
                if timeout <= 0 or time.monotonic() >= deadline:
                    return {
                        "ok": True,
                        "video_url": None,
                        "poster_url": poster,
                        "request_id": rid,
                        "status": "pending",
                        "provider": "xai",
                        "model": model,
                        "duration_sec": None,
                        "error": None,
                        "error_code": None,
                        "retryable": None,
                        "note": f"Still rendering (request_id={rid}, last_status={st or 'pending'}).",
                        "agent_guidance": (
                            f"Still pending (request_id={rid}). Wait, then check_video again. "
                            "Do NOT call generate_video for this brief."
                        ),
                    }
            return {
                "ok": True,
                "video_url": None,
                "poster_url": poster,
                "request_id": rid,
                "status": "pending",
                "provider": "xai",
                "model": model,
                "duration_sec": None,
                "error": None,
                "error_code": None,
                "retryable": None,
                "note": f"Still rendering after brief poll (request_id={rid}).",
                "agent_guidance": (
                    f"Still pending (request_id={rid}). Use check_video later; do not resubmit."
                ),
            }
    except Exception as e:
        detail = f"xAI video status error: {type(e).__name__}: {e}"
        log.warning(detail)
        return {
            "ok": False,
            "video_url": None,
            "poster_url": poster,
            "request_id": rid,
            "status": "failed",
            "provider": "xai",
            "model": model,
            "duration_sec": None,
            "error": detail,
            "error_code": "xai_network",
            "retryable": True,
            "note": "Status check failed.",
            "agent_guidance": "Network error on check_video — one careful retry; do not generate_video.",
        }


@router.post("/video")
async def generate_video(data: VideoIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Generate a short video via xAI Imagine (async poll); always charge tokens (premium)."""
    ensure_credits(db, user.id, min_credits=0.05)
    prompt = (data.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(400, "prompt required")

    result = await xai_generate_video(
        prompt,
        duration_sec=data.duration_sec,
        aspect_ratio=data.aspect_ratio,
        resolution=data.resolution,
        image_url=data.image_url,
    )
    charged = charge_event(db, user, "video", text=prompt)
    await _broadcast_usage(user.id, charged)
    if result.get("error_code") in ("xai_credits", "xai_permission") and not result.get("ok"):
        raise HTTPException(
            402 if result.get("error_code") == "xai_credits" else 403,
            result.get("error") or "xAI video unavailable",
        )
    return {
        "ok": bool(result.get("ok")),
        "poster_url": result.get("poster_url"),
        "video_url": result.get("video_url"),
        "request_id": result.get("request_id"),
        "status": result.get("status"),
        "prompt": prompt,
        "duration_sec": result.get("duration_sec") or data.duration_sec,
        "provider": result.get("provider") or "managed",
        "model": result.get("model"),
        "error": result.get("error"),
        "error_code": result.get("error_code"),
        "retryable": result.get("retryable"),
        "usage": charged,
        "meter": meter_snapshot(db, user),
        "note": result.get("note") or "Premium video generation billed.",
        "agent_guidance": result.get("agent_guidance"),
        "next_skill": (
            "check_video"
            if result.get("status") == "pending" and result.get("request_id")
            else None
        ),
    }


@router.get("/video/{request_id}")
async def check_video_status(
    request_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Poll an existing xAI video job — no new generation, no premium video charge."""
    ensure_credits(db, user.id)
    rid = (request_id or "").strip()
    if len(rid) < 4:
        raise HTTPException(400, "request_id required")
    result = await xai_check_video(rid)
    if result.get("error_code") in ("xai_credits", "xai_permission") and not result.get("ok"):
        raise HTTPException(
            402 if result.get("error_code") == "xai_credits" else 403,
            result.get("error") or "xAI video status unavailable",
        )
    return {
        "ok": bool(result.get("ok")),
        "poster_url": result.get("poster_url"),
        "video_url": result.get("video_url"),
        "request_id": result.get("request_id") or rid,
        "status": result.get("status"),
        "provider": result.get("provider") or "managed",
        "model": result.get("model"),
        "error": result.get("error"),
        "error_code": result.get("error_code"),
        "retryable": result.get("retryable"),
        "meter": meter_snapshot(db, user),
        "note": result.get("note") or "Video status check (no generate charge).",
        "agent_guidance": result.get("agent_guidance"),
        "next_skill": (
            "check_video"
            if result.get("status") == "pending"
            else None
        ),
    }
