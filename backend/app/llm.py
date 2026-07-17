"""LLM router: Claude → Anthropic, Grok → xAI, VPS/Qwen → Ollama.
Falls back: selected provider → Ollama → built-in mock so the app never breaks."""
import json
import asyncio
import random

import httpx

from . import config

MOCK_BODIES = {
    "sales": "Based on what you've described, I'd lead with the customer's pain point, keep the pitch to two sentences, and close with a clear next step such as booking a 10-minute call. Want me to draft the outreach message?",
    "support": "I'd acknowledge the issue first, confirm the details we have on file, then offer the fastest resolution path. If it needs escalation I'll flag it and keep the customer updated. Shall I draft the reply?",
    "coding": "I'd break this into: (1) reproduce / clarify requirements, (2) minimal design, (3) implementation with tests, (4) edge cases. Paste the file or error and I'll produce a concrete patch.",
    "general": "I've considered the context you've given me. My recommendation is to break this into small concrete steps, handle the highest-impact item first, and I can prepare drafts or summaries for any of them. Tell me which part to start on.",
}

# App model id → Ollama tag from config
OLLAMA_MAP = {
    "vps-fast": lambda: config.OLLAMA_MODEL_FAST,
    "vps-quality": lambda: config.OLLAMA_MODEL_QUALITY,
    "vps-qwen-fast": lambda: config.OLLAMA_MODEL_QWEN_FAST,
    "vps-qwen-7b": lambda: config.OLLAMA_MODEL_QWEN_7B,
    "vps-qwen-14b": lambda: config.OLLAMA_MODEL_QWEN_14B,
    "vps-qwen-32b": lambda: config.OLLAMA_MODEL_QWEN_32B,
    "vps-qwen-coder": lambda: config.OLLAMA_MODEL_QWEN_CODER,
    "vps-qwen-coder-7b": lambda: config.OLLAMA_MODEL_QWEN_CODER_7B,
    "vps-qwen-coder-14b": lambda: config.OLLAMA_MODEL_QWEN_CODER_14B,
    "vps-qwen-coder-32b": lambda: config.OLLAMA_MODEL_QWEN_CODER_32B,
    "vps-qwen-large": lambda: config.OLLAMA_MODEL_QWEN_LARGE,
    "vps-qwen-72b": lambda: config.OLLAMA_MODEL_QWEN_72B,
}


async def _mock_stream(mode: str):
    reply = (
        f"{random.choice(['Here is my take.', 'Right, here is what I would suggest.'])} "
        f"{MOCK_BODIES.get(mode, MOCK_BODIES['general'])}"
    )
    for word in reply.split(" "):
        yield word + " "
        await asyncio.sleep(0.03)


def _anthropic_model_id(model: str) -> str:
    m = model.lower()
    if "opus" in m:
        return "claude-opus-4-20250514"
    if "haiku" in m:
        return "claude-haiku-4-5-20251001"
    return "claude-sonnet-4-6"


async def _anthropic_stream(messages, model, api_key: str | None = None):
    import anthropic
    key = api_key or config.ANTHROPIC_API_KEY
    if not key:
        raise RuntimeError("No Anthropic API key")
    client = anthropic.AsyncAnthropic(api_key=key)
    model_id = _anthropic_model_id(model)
    async with client.messages.stream(model=model_id, max_tokens=2048, messages=messages) as stream:
        async for text in stream.text_stream:
            yield text


def _xai_model_id(model: str) -> str:
    m = model.lower()
    if m in ("grok-fast", "grok-mini") or "mini" in m or "fast" in m:
        return config.XAI_MODEL_FAST
    if "grok-4" in m or m == "grok-4":
        return config.XAI_MODEL_GROK4
    if "grok-2" in m or m == "grok-2":
        return config.XAI_MODEL_GROK2
    if "grok-3" in m or m in ("grok", "grok-3"):
        return config.XAI_MODEL_GROK3
    return config.XAI_MODEL_QUALITY


async def _xai_stream(messages, model, api_key: str | None = None):
    """xAI Grok via OpenAI-compatible Chat Completions API."""
    key = api_key or config.XAI_API_KEY
    if not key:
        raise RuntimeError("No xAI API key")
    model_id = _xai_model_id(model)
    base = config.XAI_BASE_URL.rstrip("/")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": True,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", headers=headers, json=payload,
        ) as r:
            r.raise_for_status()
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


def _resolve_ollama_model(model: str) -> str:
    if model in OLLAMA_MAP:
        return OLLAMA_MAP[model]()
    if "coder-32" in model or model.endswith("coder-32b"):
        return config.OLLAMA_MODEL_QWEN_CODER_32B
    if "coder-14" in model:
        return config.OLLAMA_MODEL_QWEN_CODER_14B
    if "coder-7" in model:
        return config.OLLAMA_MODEL_QWEN_CODER_7B
    if "coder" in model:
        return config.OLLAMA_MODEL_QWEN_CODER
    if "72" in model or "large" in model:
        return config.OLLAMA_MODEL_QWEN_72B
    if "32" in model:
        return config.OLLAMA_MODEL_QWEN_32B
    if "14" in model:
        return config.OLLAMA_MODEL_QWEN_14B
    if "7" in model or "qwen" in model:
        return config.OLLAMA_MODEL_QWEN_7B
    if model == "vps-quality":
        return config.OLLAMA_MODEL_QUALITY
    return config.OLLAMA_MODEL_FAST


async def _ollama_stream(messages, model):
    ollama_model = _resolve_ollama_model(model)
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            f"{config.OLLAMA_URL}/api/chat",
            json={"model": ollama_model, "messages": messages, "stream": True},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    return


async def stream_completion(
    messages: list[dict],
    model: str,
    mode: str = "general",
    credentials: dict | None = None,
):
    """
    credentials: optional subscriber keys {anthropic, xai, ...} — preferred over platform env.

    Order:
      1) Selected premium stack (Claude / Grok) if keys exist
      2) Local / VPS Ollama (for vps-* and as fallback)
      3) Platform xAI Grok (always try if key set — works on Vercel without Ollama)
      4) Platform Anthropic
      5) Mock (dev only) or production error
    """
    creds = credentials or {}
    anthropic_key = creds.get("anthropic") or config.ANTHROPIC_API_KEY
    xai_key = creds.get("xai") or config.XAI_API_KEY
    m = (model or "").lower().strip() or "vps-fast"

    # Premium Claude — subscriber key first, then platform
    if m.startswith("claude") and anthropic_key:
        try:
            async for c in _anthropic_stream(messages, model, api_key=anthropic_key):
                yield c
            return
        except Exception:
            pass  # fall through to Ollama / Grok

    # Premium xAI Grok (selected model)
    if m.startswith("grok") and xai_key:
        try:
            async for c in _xai_stream(messages, model, api_key=xai_key):
                yield c
            return
        except Exception:
            pass

    # Local / VPS Ollama (default for vps-* fleet; also after premium failure)
    try:
        ollama_model = model if (m.startswith("vps") or "qwen" in m) else "vps-fast"
        async for c in _ollama_stream(messages, ollama_model):
            yield c
        return
    except Exception:
        pass

    # Platform Grok fallback — use your xAI key even when UI selected a VPS model
    # (common on Vercel serverless where localhost Ollama is unreachable)
    if xai_key:
        try:
            fallback = "grok-fast" if ("fast" in m or "mini" in m or m.startswith("vps")) else "grok-quality"
            if m.startswith("grok"):
                fallback = model
            async for c in _xai_stream(messages, fallback, api_key=xai_key):
                yield c
            return
        except Exception:
            pass

    if anthropic_key:
        try:
            async for c in _anthropic_stream(messages, "claude-sonnet", api_key=anthropic_key):
                yield c
            return
        except Exception:
            pass

    # Fail closed in production — never invent business answers with mock LLM
    if config.IS_PRODUCTION or getattr(config, "APP_ENV", "").lower() == "production":
        yield (
            "No live LLM is available for this request. "
            "Set XAI_API_KEY (or Anthropic), or start Ollama on OLLAMA_URL with a pulled model "
            "(e.g. qwen2.5:3b). Mock replies are disabled in production."
        )
        return

    async for c in _mock_stream(mode):
        yield c


def provider_hint(
    model: str,
    credentials: dict | None = None,
) -> str:
    """Best-effort provider label for REST responses (selected model + keys present).

    Does not detect actual fallback path — only which stack the request would
    prefer given model id and whether user/platform keys exist.
    """
    creds = credentials or {}
    m = (model or "").lower()
    has_anthropic = bool(creds.get("anthropic") or config.ANTHROPIC_API_KEY)
    has_xai = bool(creds.get("xai") or config.XAI_API_KEY)

    if m.startswith("claude") or "claude" in m:
        return "anthropic" if has_anthropic else "mock"
    if m.startswith("grok") or "grok" in m:
        return "xai" if has_xai else "mock"
    if m.startswith("vps") or "qwen" in m or "ollama" in m:
        return "ollama"
    # Non-premium / unknown → treat as Ollama path if it looks local, else mock
    if not m.startswith(("claude", "grok")):
        return "ollama"
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
