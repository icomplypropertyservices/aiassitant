"""
Managed LLM router — single primary path.

Clients only pass neutral model ids (fast, quality, reasoning, large, ...).
Inference goes to managed Ollama (RunPod URL or local). Optional OpenAI-compatible fallback.

No silent swallow of primary-path errors in production.
"""
from __future__ import annotations

import json
import asyncio
import logging
import random

import httpx

from . import config

log = logging.getLogger("app.llm")

# Serialize GPU-bound Ollama calls (one Vercel instance can still pile up; semaphore helps per process)
_ollama_sem: asyncio.Semaphore | None = None


def _get_ollama_sem() -> asyncio.Semaphore:
    global _ollama_sem
    if _ollama_sem is None:
        n = int(getattr(config, "OLLAMA_MAX_CONCURRENT", 1) or 1)
        _ollama_sem = asyncio.Semaphore(max(1, n))
    return _ollama_sem


MOCK_BODIES = {
    "sales": "Based on what you've described, I'd lead with the customer's pain point, keep the pitch to two sentences, and close with a clear next step such as booking a 10-minute call. Want me to draft the outreach message?",
    "support": "I'd acknowledge the issue first, confirm the details we have on file, then offer the fastest resolution path. If it needs escalation I'll flag it and keep the customer updated. Shall I draft the reply?",
    "coding": "I'd break this into: (1) reproduce / clarify requirements, (2) minimal design, (3) implementation with tests, (4) edge cases. Paste the file or error and I'll produce a concrete patch.",
    "general": "I've considered the context you've given me. My recommendation is to break this into small concrete steps, handle the highest-impact item first, and I can prepare drafts or summaries for any of them. Tell me which part to start on.",
}


async def _mock_stream(mode: str):
    reply = (
        f"{random.choice(['Here is my take.', 'Right, here is what I would suggest.'])} "
        f"{MOCK_BODIES.get(mode, MOCK_BODIES['general'])}"
    )
    for word in reply.split(" "):
        yield word + " "
        await asyncio.sleep(0.02)


def _ollama_base() -> str:
    """Admin connection (DB) → RUNPOD_OLLAMA_URL → local Ollama (dev only)."""
    try:
        from .runpod_fleet import ollama_base as fleet_base
        url = (fleet_base() or "").rstrip("/")
        if url:
            is_loopback = any(
                h in url for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")
            )
            if is_loopback and (
                config.IS_PRODUCTION
                or getattr(config, "IS_VERCEL", False)
                or (getattr(config, "APP_ENV", "") or "").lower() == "production"
            ):
                return ""
            return url
    except Exception:
        pass
    runpod = (getattr(config, "RUNPOD_OLLAMA_URL", None) or "").rstrip("/")
    if runpod:
        return runpod
    local = (getattr(config, "OLLAMA_URL", None) or "").rstrip("/")
    if not local:
        return ""
    is_loopback = any(
        h in local for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")
    )
    if is_loopback and (
        config.IS_PRODUCTION
        or getattr(config, "IS_VERCEL", False)
        or (getattr(config, "APP_ENV", "") or "").lower() == "production"
    ):
        return ""
    return local


def _resolve_tag(neutral: str) -> str:
    try:
        from .runpod_fleet import resolve_ollama_tag
        return resolve_ollama_tag(neutral)
    except Exception:
        m = (neutral or "fast").lower()
        return {
            "fast": getattr(config, "OLLAMA_MODEL_FAST", "qwen2.5:7b"),
            "quality": getattr(config, "OLLAMA_MODEL_QUALITY", "qwen2.5:14b"),
            "reasoning": "deepseek-r1:14b",
            "large": getattr(config, "OLLAMA_MODEL_QWEN_32B", "qwen2.5:32b"),
            "small": "qwen2.5:3b",
            "medium": "qwen2.5:7b",
        }.get(m, m)


async def _ollama_stream(messages: list[dict], model: str):
    base = _ollama_base()
    if not base:
        raise RuntimeError("No managed Ollama URL configured (RUNPOD_OLLAMA_URL / OLLAMA_URL)")

    tag = _resolve_tag(model)
    headers = {"Content-Type": "application/json"}
    try:
        from .runpod_fleet import get_connection
        key = (get_connection(include_secrets=True).get("api_key") or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        elif getattr(config, "RUNPOD_API_KEY", None):
            headers["Authorization"] = f"Bearer {config.RUNPOD_API_KEY}"
    except Exception:
        if getattr(config, "RUNPOD_API_KEY", None):
            headers["Authorization"] = f"Bearer {config.RUNPOD_API_KEY}"

    # Cap context/output so a single chat cannot pin the whole GPU
    keep_alive = getattr(config, "OLLAMA_KEEP_ALIVE", "2m") or "2m"
    num_predict = int(getattr(config, "OLLAMA_NUM_PREDICT", 1024) or 1024)
    num_ctx = int(getattr(config, "OLLAMA_NUM_CTX", 4096) or 4096)
    # Prefer smaller footprint for "small"/"fast" tiers
    mlow = (model or "").lower()
    if mlow in ("small", "fast"):
        num_predict = min(num_predict, 768)
        num_ctx = min(num_ctx, 3072)

    payload = {
        "model": tag,
        "messages": messages,
        "stream": True,
        "keep_alive": keep_alive,
        "options": {
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }

    sem = _get_ollama_sem()
    async with sem:
        log.info(
            "ollama_chat model=%s tag=%s concurrent_slots=%s base=%s",
            mlow or model,
            tag,
            getattr(config, "OLLAMA_MAX_CONCURRENT", 1),
            base[:48],
        )
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            # Prefer non-stream first on serverless — simpler + clearer errors
            try:
                non_stream = {**payload, "stream": False}
                r = await client.post(f"{base}/api/chat", headers=headers, json=non_stream)
                ctype = (r.headers.get("content-type") or "").lower()
                text_body = r.text or ""
                if r.status_code >= 400 or "text/html" in ctype or text_body.lstrip().startswith("<!"):
                    hint = (
                        "RunPod Ollama is offline or not listening on port 11434 "
                        "(proxy shows Waiting for service). Start ollama serve on the pod."
                    )
                    raise RuntimeError(
                        f"Ollama unavailable HTTP {r.status_code}: {hint} body={text_body[:180]!r}"
                    )
                data = r.json()
                chunk = (data.get("message") or {}).get("content") or data.get("response") or ""
                if chunk:
                    yield chunk
                    return
                raise RuntimeError("Ollama returned empty message")
            except RuntimeError:
                raise
            except Exception as e:
                log.warning("ollama non-stream failed, trying stream: %s", e)

            async with client.stream(
                "POST",
                f"{base}/api/chat",
                headers=headers,
                json=payload,
            ) as r:
                if r.status_code >= 400:
                    body = (await r.aread())[:500]
                    raise RuntimeError(f"Ollama HTTP {r.status_code}: {body!r}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    if line.lstrip().startswith("<"):
                        raise RuntimeError(
                            "Ollama proxy returned HTML — GPU pod service is not ready. "
                            "Start Ollama on RunPod (port 11434)."
                        )
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        return


async def _openai_compat_stream(messages: list[dict], model: str):
    base = (
        getattr(config, "RUNPOD_OPENAI_BASE_URL", None)
        or getattr(config, "RUNPOD_BASE_URL", None)
        or ""
    ).rstrip("/")
    key = getattr(config, "RUNPOD_API_KEY", None) or ""
    if not base or not key:
        raise RuntimeError("OpenAI-compatible backend not configured")

    tag = _resolve_tag(model)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": tag,
        "messages": messages,
        "stream": True,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", headers=headers, json=payload,
        ) as r:
            if r.status_code >= 400:
                body = (await r.aread())[:500]
                raise RuntimeError(f"OpenAI-compat HTTP {r.status_code}: {body!r}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    yield text


def _is_grok_model(model: str) -> bool:
    m = (model or "").lower().strip()
    return m in ("grok-max", "grok", "premium", "xai") or m.startswith("grok")


def _grok_only() -> bool:
    """When true (default), every chat completion goes to xAI Grok — no Ollama/RunPod."""
    return bool(getattr(config, "LLM_GROK_ONLY", True))


def _xai_model_id(model: str) -> str:
    """Map neutral/staff ids to real xAI Grok model names."""
    m = (model or "quality").lower().strip()
    fast = getattr(config, "XAI_MODEL_FAST", None) or "grok-4.20-0309-non-reasoning"
    quality = getattr(config, "XAI_MODEL_QUALITY", None) or getattr(config, "XAI_MODEL_GROK4", None) or "grok-4.5"
    reasoning = getattr(config, "XAI_MODEL_REASONING", None) or quality
    grok4 = getattr(config, "XAI_MODEL_GROK4", None) or "grok-4.5"
    grok3 = getattr(config, "XAI_MODEL_GROK3", None) or "grok-4.3"

    # Explicit Grok family
    if m in ("grok-max", "grok", "premium", "xai", "grok-4.5") or m.startswith("grok-4.5"):
        return grok4
    if "4.3" in m or m in ("grok-3", "grok-4.3"):
        return grok3
    if m.startswith("grok"):
        return grok4

    # Neutral tiers (client-facing) → Grok
    if m in ("small", "fast", "medium", "vps-fast") or "fast" in m or "mini" in m or "non-reason" in m:
        return fast
    if m in ("reasoning", "large") or "reason" in m or "opus" in m:
        return reasoning
    if m in ("quality", "vps-quality") or "quality" in m or "sonnet" in m:
        return quality
    # Default everything else (incl. legacy vps-*) to quality Grok
    return quality


async def _xai_stream(messages: list[dict], model: str, credentials: dict | None = None):
    """xAI chat via API key (prod) or Grok Super JWT (local/dev)."""
    user_key = None
    if credentials:
        # Only accept JWT-shaped BYOK; ignore developer api keys when JWT-only
        cand = credentials.get("xai") or credentials.get("grok")
        if cand and str(cand).startswith("eyJ"):
            user_key = cand
        elif cand and not getattr(config, "XAI_USE_JWT_ONLY", True):
            user_key = cand
    token = config.get_grok_token(user_key)
    if not token:
        raise RuntimeError(
            "Grok not available. Set XAI_API_KEY on Vercel (production) or sign in with the "
            "grok CLI (~/.grok/auth.json) / GROK_SESSION_TOKEN for Super session."
        )

    base = (getattr(config, "XAI_BASE_URL", None) or "https://api.x.ai/v1").rstrip("/")
    xai_model = _xai_model_id(model)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": xai_model,
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
    }
    log.info("xai_chat model_in=%s xai_model=%s", model, xai_model)
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", headers=headers, json=payload,
        ) as r:
            if r.status_code >= 400:
                body = (await r.aread())[:500]
                raise RuntimeError(f"xAI HTTP {r.status_code}: {body!r}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    yield text


async def stream_completion(
    messages: list[dict],
    model: str,
    mode: str = "general",
    credentials: dict | None = None,
):
    """
    Default (LLM_GROK_ONLY=true): all chat → xAI Grok only.
    Optional fleet path: RunPod Ollama → OpenAI-compat → xAI fallback (only if LLM_GROK_ONLY=false).
    """
    m = (model or "quality").lower().strip()
    last_err: Exception | None = None

    # Media ids are handled elsewhere; treat as quality chat if they land here
    if m in ("image", "video"):
        m = "quality"

    # Grok-only mode (production default): never call Ollama/RunPod
    if _grok_only() or _is_grok_model(m):
        try:
            async for c in _xai_stream(messages, m, credentials=credentials):
                yield c
            return
        except Exception as e:
            last_err = e
            log.warning("xai_stream failed: %s", e)
    else:
        if _ollama_base():
            try:
                async for c in _ollama_stream(messages, m):
                    yield c
                return
            except Exception as e:
                last_err = e
                log.warning("ollama_stream failed: %s", e)
        try:
            async for c in _openai_compat_stream(messages, m):
                yield c
            return
        except Exception as e:
            last_err = e
            log.warning("openai_compat_stream failed: %s", e)

        # GPU / Ollama down — keep conversations alive via xAI if configured
        try:
            log.warning("falling back to xAI for model=%s after ollama failure", m)
            async for c in _xai_stream(messages, m, credentials=credentials):
                yield c
            return
        except Exception as e:
            last_err = e
            log.warning("xai fallback failed: %s", e)

    if config.IS_PRODUCTION or getattr(config, "APP_ENV", "").lower() == "production":
        detail = str(last_err) if last_err else "no backend configured"
        log.error("LLM unavailable: %s", detail)
        yield (
            "Grok is not available right now. Check XAI_API_KEY / GROK_SESSION_TOKEN on the server. "
            f"({detail[:220]})"
        )
        return

    async for c in _mock_stream(mode):
        yield c


def provider_hint(model: str, credentials: dict | None = None) -> str:
    """Client-safe label only — never expose raw provider names."""
    m = (model or "").lower()
    if m in ("image", "video"):
        return "managed-media"
    if _grok_only() or _is_grok_model(m):
        return "managed"
    if _ollama_base() or getattr(config, "RUNPOD_OPENAI_BASE_URL", None):
        return "managed"
    return "mock"


async def complete(
    messages: list[dict],
    model: str,
    mode: str = "general",
    credentials: dict | None = None,
) -> str:
    out = ""
    async for c in stream_completion(messages, model, mode, credentials=credentials):
        out += c
    return out.strip()
