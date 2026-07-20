"""Content generation / research / time / media skill handlers.

Media skill ids (xAI Imagine when configured):
  generate_image, generate_video, check_video, edit_image,
  generate_ad_creative, generate_product_shot
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops
from .bridge import (
    get_skill_catalog,
    charge_premium,
)

log = logging.getLogger("aba.skills.content")


def _skill_meta(skill_id: str) -> dict:
    return next((s for s in get_skill_catalog() if s["id"] == skill_id), {})


def _media_error_fields(result: dict | None) -> dict[str, Any]:
    """Propagate terminal/retry guidance so agents stop thrashing on 402/403."""
    r = result or {}
    out: dict[str, Any] = {}
    if r.get("error"):
        out["error"] = r["error"]
    if r.get("error_code"):
        out["error_code"] = r["error_code"]
    if r.get("retryable") is not None:
        out["retryable"] = bool(r["retryable"])
    if r.get("agent_guidance"):
        out["agent_guidance"] = r["agent_guidance"]
        out["message"] = r["agent_guidance"]
    # Terminal codes always fail closed for skill dispatch
    if r.get("error_code") in ("xai_credits", "xai_permission"):
        out["ok"] = False
        out["retryable"] = False
        if not out.get("agent_guidance"):
            out["agent_guidance"] = (
                "STOP: xAI media unavailable (credits/permission). "
                "Do not re-call media skills until billing/key is fixed."
            )
            out["message"] = out["agent_guidance"]
    return out


async def _skill_generate_image(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or args.get("description") or "").strip()
    if len(prompt) < 3:
        return {
            "ok": False,
            "error": "prompt is required (min 3 chars)",
            "error_code": "validation",
            "retryable": False,
        }
    style = args.get("style") or args.get("quality")
    size = args.get("size")
    meta = _skill_meta("generate_image")
    # If execute_skill already charged premium, avoid double-charge
    if not args.get("_billed"):
        charge_premium(db, user, meta, float(meta.get("cost_credits") or 0.06), text=prompt)

    try:
        from ..routers.media import xai_generate_image
        result = await xai_generate_image(prompt, style=style, size=size, allow_placeholder=True)
    except Exception as e:
        log.warning("generate_image crashed: %s", e)
        return {
            "ok": False,
            "error": f"image generation failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "premium_billed": True,
            "agent_guidance": "Media helper error. Do not thrash generate_image; report to human.",
            "message": "Media helper error. Do not thrash generate_image; report to human.",
        }

    provider = result.get("provider") or "none"
    terminal = result.get("error_code") in ("xai_credits", "xai_permission")
    ok = bool(result.get("ok")) and not terminal
    if not result.get("url") and result.get("error"):
        ok = False
    title = "Image generated" if result.get("url") and provider == "xai" and ok else "Image result"
    try:
        await emit_ops(
            user.id, kind="action", status="done" if ok else "error",
            title=title, detail=prompt[:120], agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    out: dict[str, Any] = {
        "ok": ok,
        "url": result.get("url"),
        "prompt": prompt,
        "style": style,
        "size": size,
        "provider": provider,
        "model": result.get("model"),
        "premium_billed": True,
        "note": result.get("note") or (
            "Premium image generation billed (tokens/credits)."
            if provider == "xai" and ok
            else None
        ),
    }
    out.update(_media_error_fields(result))
    if terminal:
        out["ok"] = False
        out["url"] = None  # never hand a fake asset on credits/auth failure
    return out


async def _skill_edit_image(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or args.get("instruction") or args.get("edit") or "").strip()
    image_url = (
        args.get("image_url")
        or args.get("url")
        or args.get("source_url")
        or args.get("image")
        or ""
    )
    image_url = str(image_url).strip()
    if len(prompt) < 3:
        return {
            "ok": False,
            "error": "prompt is required (describe the edit)",
            "error_code": "validation",
            "retryable": False,
        }
    if not image_url:
        return {
            "ok": False,
            "error": "image_url is required (public URL or data URI)",
            "error_code": "validation",
            "retryable": False,
        }

    meta = _skill_meta("edit_image")
    if not args.get("_billed"):
        charge_premium(db, user, meta, float(meta.get("cost_credits") or 0.08), text=prompt)

    try:
        from ..routers.media import xai_edit_image
        result = await xai_edit_image(prompt, image_url, style=args.get("style"))
    except Exception as e:
        log.warning("edit_image crashed: %s", e)
        return {
            "ok": False,
            "error": f"image edit failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "prompt": prompt,
            "image_url": image_url,
            "premium_billed": True,
            "agent_guidance": "Media helper error. Do not thrash edit_image.",
            "message": "Media helper error. Do not thrash edit_image.",
        }

    try:
        await emit_ops(
            user.id, kind="action",
            status="done" if result.get("ok") else "error",
            title="Image edited" if result.get("ok") else "Image edit failed",
            detail=prompt[:120], agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    if not result.get("ok"):
        out = {
            "ok": False,
            "error": result.get("error") or "image edit failed",
            "prompt": prompt,
            "image_url": image_url,
            "provider": result.get("provider"),
            "model": result.get("model"),
            "premium_billed": True,
            "note": result.get("note") or (
                "Premium image edit billed even when the provider rejected the request."
            ),
        }
        out.update(_media_error_fields(result))
        return out
    return {
        "ok": True,
        "url": result.get("url"),
        "prompt": prompt,
        "image_url": image_url,
        "provider": result.get("provider") or "xai",
        "model": result.get("model"),
        "premium_billed": True,
        "note": "Premium image edit billed (tokens/credits).",
    }


def _channel_ad_framing(channel: str) -> str:
    """Aspect / composition cues by ad placement."""
    c = (channel or "social").strip().lower()
    if c in ("instagram", "ig", "reels", "tiktok", "stories", "story"):
        return (
            "Vertical 4:5 or 9:16 social-first frame, bold focal subject upper-third, "
            "safe margins for UI chrome."
        )
    if c in ("facebook", "meta", "feed", "linkedin", "twitter", "x", "social"):
        return (
            "Square or 1.91:1 feed-friendly frame, strong center-weighted subject, "
            "readable at thumbnail size."
        )
    if c in ("youtube", "display", "banner", "web", "landing", "hero"):
        return (
            "Wide 16:9 cinematic hero frame, product or offer as clear hero element, "
            "generous negative space for headline overlay."
        )
    if c in ("print", "ooh", "billboard", "poster"):
        return "Large-format poster composition, high contrast from a distance, minimal clutter."
    return "Social-ready commercial frame with clear focal hierarchy and overlay-safe margins."


def _build_ad_creative_prompt(
    *,
    product: str,
    headline: str,
    audience: str,
    channel: str,
    style: str,
) -> str:
    """High-converting default ad brief for Imagine (when caller skips raw prompt)."""
    parts = [
        f"Award-winning advertising still for {channel or 'social'} — photoreal commercial quality.",
        f"Hero subject / offer: {product or 'brand campaign'}.",
        _channel_ad_framing(channel),
        (
            "Cinematic lighting with soft key + subtle rim, rich but natural color grade, "
            "shallow depth of field on product, crisp edges, high dynamic range, "
            "premium brand aesthetic, no watermark, no stock-photo look."
        ),
        (
            "Composition: single clear focal point, balanced negative space for headline/CTA overlay, "
            "no illegible micro-text, no random gibberish letters, marketing-ready."
        ),
    ]
    if headline:
        parts.append(
            f"Concept message (do not render as tiny unreadable type): {headline}."
        )
    if audience:
        parts.append(f"Visual tone tuned for audience: {audience}.")
    if style:
        parts.append(f"Art direction / style: {style}.")
    parts.append(
        "Avoid: cluttered backgrounds, distorted hands/faces, low-res blur, oversharpening halos."
    )
    return " ".join(parts)


def _build_product_shot_prompt(
    *,
    product: str,
    angle: str,
    background: str,
    style: str,
    brand: str,
    props: str,
) -> str:
    """E-commerce PDP / catalog quality default for Imagine."""
    parts = [
        f"High-end e-commerce product photograph of {product}.",
        f"Camera angle: {angle or 'hero 3/4 front'}.",
        f"Background: {background or 'clean seamless studio white'}.",
        (
            "Studio softbox lighting with soft contact shadow, accurate true-to-life color, "
            "sharp focus on materials and edges, subtle specular highlights, "
            "commercial catalog / Amazon PDP quality, no watermark, no logo inventions."
        ),
        (
            "Framing: product fills ~70% of frame, centered, square-crop friendly, "
            "no cropped critical edges, isolated subject unless props specified."
        ),
    ]
    if brand:
        parts.append(f"Brand context (keep packaging/label authentic if visible): {brand}.")
    if props:
        parts.append(f"Styling props only as specified (do not invent extras): {props}.")
    if style:
        parts.append(f"Look & style: {style}.")
    parts.append(
        "Avoid: warped geometry, floating without shadow, busy lifestyle clutter unless requested, "
        "text overlays, fake reflections."
    )
    return " ".join(parts)


async def _skill_generate_ad_creative(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Marketing ad creative: structured prompt → premium image generation."""
    product = (args.get("product") or args.get("offer") or args.get("brand") or "").strip()
    headline = (args.get("headline") or args.get("cta") or "").strip()
    audience = (args.get("audience") or "").strip()
    channel = (args.get("channel") or args.get("platform") or "social").strip()
    style = (args.get("style") or "vivid commercial photography, premium brand, photoreal").strip()
    raw_prompt = (args.get("prompt") or "").strip()

    if raw_prompt and len(raw_prompt) >= 3:
        # Still reinforce quality floor when user supplies a short prompt
        if len(raw_prompt) < 80:
            prompt = (
                f"{raw_prompt}. Commercial advertising quality, clean composition, "
                f"overlay-safe margins for {channel}, no illegible text, no watermark."
            )
        else:
            prompt = raw_prompt
    elif product or headline:
        prompt = _build_ad_creative_prompt(
            product=product,
            headline=headline,
            audience=audience,
            channel=channel,
            style=style,
        )
    else:
        return {
            "ok": False,
            "error": "Provide prompt, or product/headline for the ad creative",
            "error_code": "validation",
            "retryable": False,
        }

    meta = _skill_meta("generate_ad_creative")
    if not args.get("_billed"):
        charge_premium(db, user, meta, float(meta.get("cost_credits") or 0.08), text=prompt)

    try:
        from ..routers.media import xai_generate_image
        result = await xai_generate_image(prompt, style=style, size=args.get("size"), allow_placeholder=True)
    except Exception as e:
        log.warning("generate_ad_creative crashed: %s", e)
        return {
            "ok": False,
            "error": f"ad creative failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "premium_billed": True,
            "agent_guidance": "Media helper error. Do not thrash generate_ad_creative.",
            "message": "Media helper error. Do not thrash generate_ad_creative.",
        }

    terminal = result.get("error_code") in ("xai_credits", "xai_permission")
    ok = bool(result.get("ok")) and not terminal
    if not result.get("url") and result.get("error"):
        ok = False
    try:
        await emit_ops(
            user.id, kind="action", status="done" if ok else "error",
            title="Ad creative generated" if ok else "Ad creative failed",
            detail=prompt[:120], agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    out: dict[str, Any] = {
        "ok": ok,
        "url": None if terminal else result.get("url"),
        "prompt": prompt,
        "product": product or None,
        "headline": headline or None,
        "audience": audience or None,
        "channel": channel,
        "style": style,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "premium_billed": True,
        "note": result.get("note") or "Premium ad creative (image) billed (tokens/credits).",
    }
    out.update(_media_error_fields(result))
    if terminal:
        out["ok"] = False
    return out


async def _skill_generate_product_shot(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """E-commerce / catalog product photography: structured prompt → premium image."""
    product = (
        args.get("product")
        or args.get("name")
        or args.get("sku")
        or args.get("item")
        or ""
    )
    product = str(product).strip()
    background = (args.get("background") or args.get("backdrop") or "clean seamless studio white").strip()
    angle = (args.get("angle") or args.get("view") or "hero 3/4 front").strip()
    style = (
        args.get("style")
        or "professional product photography, sharp focus, commercial catalog, softbox lighting"
    )
    style = str(style).strip()
    raw_prompt = (args.get("prompt") or "").strip()
    props = (args.get("props") or args.get("accessories") or "").strip()
    brand = (args.get("brand") or "").strip()

    if raw_prompt and len(raw_prompt) >= 3:
        if len(raw_prompt) < 80:
            prompt = (
                f"{raw_prompt}. E-commerce product photo, studio softbox lighting, "
                f"soft contact shadow, true color, sharp materials, no watermark."
            )
        else:
            prompt = raw_prompt
    elif product:
        prompt = _build_product_shot_prompt(
            product=product,
            angle=angle,
            background=background,
            style=style,
            brand=brand,
            props=props,
        )
    else:
        return {
            "ok": False,
            "error": "Provide product (or prompt) for the product shot",
            "error_code": "validation",
            "retryable": False,
        }

    meta = _skill_meta("generate_product_shot")
    if not args.get("_billed"):
        charge_premium(db, user, meta, float(meta.get("cost_credits") or 0.07), text=prompt)

    try:
        from ..routers.media import xai_generate_image
        result = await xai_generate_image(prompt, style=style, size=args.get("size"), allow_placeholder=True)
    except Exception as e:
        log.warning("generate_product_shot crashed: %s", e)
        return {
            "ok": False,
            "error": f"product shot failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "premium_billed": True,
            "agent_guidance": "Media helper error. Do not thrash generate_product_shot.",
            "message": "Media helper error. Do not thrash generate_product_shot.",
        }

    terminal = result.get("error_code") in ("xai_credits", "xai_permission")
    ok = bool(result.get("ok")) and not terminal
    if not result.get("url") and result.get("error"):
        ok = False
    try:
        await emit_ops(
            user.id, kind="action", status="done" if ok else "error",
            title="Product shot generated" if ok else "Product shot failed",
            detail=prompt[:120], agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    out: dict[str, Any] = {
        "ok": ok,
        "url": None if terminal else result.get("url"),
        "prompt": prompt,
        "product": product or None,
        "background": background,
        "angle": angle,
        "style": style,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "premium_billed": True,
        "note": result.get("note") or "Premium product shot (image) billed (tokens/credits).",
    }
    out.update(_media_error_fields(result))
    if terminal:
        out["ok"] = False
    return out


async def _skill_generate_video(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    prompt = (args.get("prompt") or args.get("description") or "").strip()
    if len(prompt) < 3:
        return {
            "ok": False,
            "error": "prompt is required (min 3 chars)",
            "error_code": "validation",
            "retryable": False,
        }
    try:
        duration = int(args.get("duration_sec") or args.get("duration") or 6)
    except (TypeError, ValueError):
        duration = 6
    aspect = args.get("aspect_ratio") or args.get("aspect") or "16:9"
    resolution = args.get("resolution") or "720p"
    image_url = args.get("image_url") or args.get("poster") or args.get("image")

    meta = _skill_meta("generate_video")
    if not args.get("_billed"):
        charge_premium(db, user, meta, float(meta.get("cost_credits") or 0.25), text=prompt)

    try:
        from ..routers.media import xai_generate_video
        result = await xai_generate_video(
            prompt,
            duration_sec=duration,
            aspect_ratio=str(aspect),
            resolution=str(resolution),
            image_url=str(image_url) if image_url else None,
        )
    except Exception as e:
        log.warning("generate_video crashed: %s", e)
        return {
            "ok": False,
            "error": f"video generation failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "status": "failed",
            "request_id": None,
            "poster_url": None,
            "video_url": None,
            "premium_billed": True,
            "agent_guidance": "Media helper error. Do not thrash generate_video.",
            "message": "Media helper error. Do not thrash generate_video.",
        }

    status = result.get("status") or "unavailable"
    terminal = result.get("error_code") in ("xai_credits", "xai_permission")
    ok = bool(result.get("ok")) and not terminal
    title_map = {
        "ready": "Video ready",
        "pending": "Video rendering",
        "failed": "Video failed",
        "expired": "Video expired",
        "unavailable": "Video poster only",
    }
    try:
        await emit_ops(
            user.id, kind="action",
            status="done" if ok else "error",
            title=title_map.get(status, "Video job"),
            detail=prompt[:120], agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    out: dict[str, Any] = {
        "ok": ok,
        "poster_url": result.get("poster_url"),
        "video_url": result.get("video_url"),
        "request_id": result.get("request_id"),
        "status": status,
        "prompt": prompt,
        "duration_sec": result.get("duration_sec") or duration,
        "aspect_ratio": aspect,
        "resolution": resolution,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "premium_billed": True,
        "note": result.get("note") or "Premium video generation billed (tokens/credits).",
    }
    out.update(_media_error_fields(result))
    if terminal:
        out["ok"] = False
        out["status"] = "failed"

    # Honest status messages; pending always points at check_video (no resubmit)
    if status == "ready" and result.get("video_url"):
        out["message"] = out.get("message") or "Video ready."
    elif status == "pending" and result.get("request_id"):
        rid = result.get("request_id")
        pending_msg = (
            f"Video job accepted and still rendering. Poster ready; request_id={rid}. "
            f"Next: call check_video with request_id={rid} (or GET /media/video/{rid}). "
            "Do NOT start another generate_video for the same brief while this job is open."
        )
        # Merge provider guidance with canonical no-resubmit path
        prev = (out.get("agent_guidance") or out.get("message") or "").strip()
        if prev and "check_video" in prev.lower() and "generate_video" in prev.lower():
            out["agent_guidance"] = prev
            out["message"] = prev
        elif prev:
            out["agent_guidance"] = f"{prev} {pending_msg}"
            out["message"] = out["agent_guidance"]
        else:
            out["message"] = pending_msg
            out["agent_guidance"] = pending_msg
        out["next_skill"] = "check_video"
        out["retryable"] = False  # do not re-submit generate_video; job already accepted
    elif status == "unavailable":
        out["message"] = out.get("message") or (
            "No xAI video credentials — poster placeholder only. "
            "Do not re-call generate_video expecting a real MP4 until XAI_API_KEY is set."
        )
        out["agent_guidance"] = out.get("agent_guidance") or out["message"]
        out["retryable"] = False
    elif not out.get("message"):
        out["message"] = result.get("error") or f"Video status: {status}"
    if result.get("next_skill") and not out.get("next_skill"):
        out["next_skill"] = result["next_skill"]
    return out


async def _skill_check_video(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    """Poll a pending generate_video job by request_id — no new generation / no video premium bill."""
    request_id = (
        args.get("request_id")
        or args.get("id")
        or args.get("job_id")
        or args.get("video_id")
        or ""
    )
    request_id = str(request_id).strip()
    if len(request_id) < 4:
        return {
            "ok": False,
            "error": "request_id is required (from generate_video when status=pending)",
            "error_code": "validation",
            "retryable": False,
            "agent_guidance": "Use the request_id returned by generate_video; do not invent one.",
        }
    prompt_hint = (args.get("prompt") or args.get("prompt_hint") or "").strip() or None
    try:
        wait = float(args.get("wait_sec") or args.get("poll_timeout_sec") or 0)
    except (TypeError, ValueError):
        wait = 0.0
    wait = max(0.0, min(wait, 90.0))

    try:
        from ..routers.media import xai_check_video
        result = await xai_check_video(
            request_id,
            prompt_hint=prompt_hint,
            poll_timeout_sec=wait,
        )
    except Exception as e:
        log.warning("check_video crashed: %s", e)
        return {
            "ok": False,
            "error": f"video status check failed: {type(e).__name__}: {e}",
            "error_code": "media_internal",
            "retryable": False,
            "request_id": request_id,
            "status": "failed",
            "agent_guidance": "check_video helper error. Do not thrash generate_video.",
            "message": "check_video helper error. Do not thrash generate_video.",
        }

    status = result.get("status") or "failed"
    terminal = result.get("error_code") in ("xai_credits", "xai_permission")
    ok = bool(result.get("ok")) and not terminal
    try:
        await emit_ops(
            user.id, kind="action",
            status="done" if ok and status == "ready" else ("error" if not ok else "done"),
            title={
                "ready": "Video ready",
                "pending": "Video still rendering",
                "failed": "Video check failed",
                "expired": "Video expired",
                "unavailable": "Video check unavailable",
            }.get(status, "Video status"),
            detail=f"request_id={request_id}",
            agent_id=agent.id, db=db,
        )
    except Exception:
        pass

    out: dict[str, Any] = {
        "ok": ok,
        "poster_url": result.get("poster_url"),
        "video_url": result.get("video_url"),
        "request_id": result.get("request_id") or request_id,
        "status": status,
        "provider": result.get("provider"),
        "model": result.get("model"),
        "duration_sec": result.get("duration_sec"),
        "premium_billed": False,
        "note": result.get("note") or "Video status check only — no generate_video charge.",
    }
    out.update(_media_error_fields(result))
    if terminal:
        out["ok"] = False
        out["status"] = "failed"

    if status == "ready" and result.get("video_url"):
        out["message"] = "Video ready — use video_url; do not re-generate."
        out["next_skill"] = None
    elif status == "pending":
        out["message"] = (
            f"Still rendering (request_id={request_id}). Wait, then check_video again. "
            "Do NOT call generate_video for this job."
        )
        out["agent_guidance"] = out["message"]
        out["next_skill"] = "check_video"
        out["retryable"] = None  # check again later is OK; not a hard fail
    elif not out.get("message"):
        out["message"] = result.get("error") or f"Video status: {status}"
    return out


async def _skill_generate_content(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    ctype = args.get("type") or args.get("format") or "email"
    topic = (args.get("topic") or args.get("subject") or args.get("prompt") or "").strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    audience = args.get("audience") or ""
    tone = args.get("tone") or "professional"
    length = args.get("length") or "medium"
    keywords = args.get("keywords") or ""
    brief = (
        f"Write {ctype} content.\n"
        f"Topic: {topic}\n"
        f"Audience: {audience or 'general'}\n"
        f"Tone: {tone}\n"
        f"Length: {length}\n"
        f"Keywords: {keywords or 'n/a'}\n"
        "Produce the full deliverable, not an outline."
    )
    return {
        "ok": True,
        "request": {
            "type": ctype,
            "topic": topic,
            "audience": audience,
            "tone": tone,
            "length": length,
            "keywords": keywords,
        },
        "message": f"Content brief ready ({ctype}): {topic[:80]}",
        "brief": brief,
    }

async def _skill_research(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    query = (args.get("query") or args.get("topic") or args.get("q") or "").strip()
    if not query:
        return {"ok": False, "error": "query or topic is required"}
    depth = args.get("depth") or "normal"
    focus = args.get("focus") or ""
    # Structure a research brief; catalog_deliverable path used for mega packs.
    # Core research skill returns a structured request the chat loop can expand.
    return {
        "ok": True,
        "request": {"query": query, "depth": depth, "focus": focus},
        "message": f"Research brief prepared for: {query[:120]}",
        "brief": (
            f"Research topic: {query}\n"
            f"Depth: {depth}\n"
            f"Focus: {focus or 'general'}\n"
            "Produce findings with sources, risks, and next actions."
        ),
    }

async def _skill_summarize(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    text = (
        args.get("text")
        or args.get("content")
        or args.get("body")
        or args.get("source")
        or ""
    )
    text = str(text).strip()
    if not text:
        return {"ok": False, "error": "text is required to summarize"}
    style = args.get("style") or args.get("format") or "bullets"
    try:
        max_points = min(20, max(3, int(args.get("max_points") or 8)))
    except (TypeError, ValueError):
        max_points = 8
    return {
        "ok": True,
        "request": {
            "text_preview": text[:400],
            "text_len": len(text),
            "format": style,
            "max_points": max_points,
        },
        "message": f"Summarize ({style}, up to {max_points} points)",
        "brief": (
            f"Summarize the following as {style} (max {max_points} points):\n\n{text[:6000]}"
        ),
    }

async def _skill_get_time(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from datetime import datetime, timezone
    tz = args.get("timezone") or "UTC"
    now = datetime.now(timezone.utc)
    return {"ok": True, "iso": now.isoformat(), "timezone": tz, "note": "Use for scheduling logic."}

async def _skill_suggest_times(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "suggestions": ["Tomorrow 10:00", "Tomorrow 14:30", "Friday 09:00"], "duration_minutes": args.get("duration_minutes", 30)}

async def _skill_create_invoice_draft(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    return {"ok": True, "draft": True, "customer_id": args.get("customer_id"), "items": args.get("items", []), "message": "Invoice draft prepared."}


__all__ = [
    '_skill_generate_image',
    '_skill_edit_image',
    '_skill_generate_ad_creative',
    '_skill_generate_product_shot',
    '_skill_generate_video',
    '_skill_check_video',
    '_skill_generate_content',
    '_skill_research',
    '_skill_summarize',
    '_skill_get_time',
    '_skill_suggest_times',
    '_skill_create_invoice_draft',
]
