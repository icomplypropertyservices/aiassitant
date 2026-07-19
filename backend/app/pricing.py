"""Customer-facing model catalog + rates.

CLIENTS MUST ONLY SEE NEUTRAL GENERIC NAMES.
Never expose: Grok, xAI, Claude, Anthropic, RunPod, VPS, Ollama, Super, session, etc.

Clients only ever see:
  Fast, Quality, Reasoning, Large Context, Small, Medium, Image, Video

Actual inference (RunPod Qwen/DeepSeek; staff Grok JWT) is hidden.
You charge customers via included tokens + wallet.
"""

# USD per 1,000,000 tokens (input+output combined for simple billing)
# Tuned for healthy margin on managed fleet while staying competitive.
PRICING = {
    "small": 0.90,       # light / teaser tier
    "fast": 1.50,        # day-to-day chat & agents
    "medium": 2.40,      # balanced
    "quality": 3.50,     # better answers
    "large": 5.00,       # large context / top Qwen 32b class
    "reasoning": 6.00,   # deep reasoning
    # Media + voice (also used as model ids on TokenUsage rows)
    "image": 12.00,
    "video": 40.00,
    "voice-stt": 4.00,
    "voice-tts": 3.50,
    "voice-call": 8.00,
    "premium-comm": 6.00,
    # Skill actions (included pool first, then wallet at these rates)
    "skill-read": 0.80,      # list/get/search
    "skill-write": 1.20,     # create/update/move/spawn
    "skill-action": 1.00,    # generic skill meter
    # Internal staff / orchestrator Grok ids
    "grok-max": 12.00,
    "grok-4.3": 5.50,   # Main AI Orchestrator
    "grok-4.5": 12.00,
}

# Flat USD + meter token weights per event (tokens always applied)
# Skill floors raised so CRM/write work is not under-metered vs real LLM cost.
EVENT_PRICING = {
    "voice-stt": {"usd": 0.004, "meter_tokens": 200},   # speech → text
    "voice-tts": {"usd": 0.003, "meter_tokens": 160},   # text → speech
    "voice-call": {"usd": 0.08, "meter_tokens": 600},
    "image": {"usd": 0.06, "meter_tokens": 1500},
    "video": {"usd": 0.25, "meter_tokens": 5000},
    "premium-comm": {"usd": 0.02, "meter_tokens": 180},
    # Non-LLM skill actions — tokens meter, included pool first (no forced wallet flat)
    "skill-read": {"usd": None, "meter_tokens": 80},
    "skill-write": {"usd": None, "meter_tokens": 200},
    "skill-action": {"usd": None, "meter_tokens": 120},
}



def event_usd(kind: str) -> float | None:
    row = EVENT_PRICING.get(kind)
    if row is None:
        return None
    if isinstance(row, dict):
        if row.get("usd") is None:
            return None  # skill-read/write: pool rates only, no flat wallet fee
        return float(row.get("usd") or 0)
    return float(row)


def event_meter_tokens(kind: str) -> int:
    row = EVENT_PRICING.get(kind)
    if isinstance(row, dict):
        return int(row.get("meter_tokens") or 50)
    return 50


MODEL_LABELS = {
    "fast": "Fast",
    "quality": "Quality",
    "reasoning": "Reasoning",
    "large": "Large Context",
    "small": "Small",
    "medium": "Medium",
    "image": "Image",
    "video": "Video",
    "grok-4.3": "Grok 4.3",
    "grok-max": "Grok Max",
}

MODEL_BLURBS = {
    "small": "Quick replies · lowest cost",
    "fast": "Everyday agents & chat",
    "medium": "Stronger answers, still snappy",
    "quality": "Best balance for most work",
    "reasoning": "Hard problems & analysis",
    "large": "Long documents & big context",
    "image": "Image generation (per event)",
    "video": "Video generation (per event)",
    "grok-4.3": "Main orchestrator — hire, projects, late work",
    "grok-max": "Highest capacity (staff / special agents)",
}

MODEL_GROUPS = [
    ("managed", "Managed chat"),
    ("flagship", "Flagship"),
    ("media", "Media"),
]

# Client-visible order
_ORDER = ["fast", "quality", "reasoning", "large", "small", "medium", "grok-4.3", "image", "video"]

def _catalog_group(mid: str) -> tuple[str, str]:
    if mid in ("image", "video"):
        return "media", "Media"
    if mid in ("grok-4.3", "grok-max", "grok-4.5"):
        return "flagship", "Flagship"
    return "managed", "Managed chat"


MODEL_CATALOG = [
    {
        "id": mid,
        "label": MODEL_LABELS[mid],
        "provider": "managed",
        "group": _catalog_group(mid)[0],
        "group_label": _catalog_group(mid)[1],
        "blurb": MODEL_BLURBS.get(mid, ""),
        "usd_per_1m": PRICING[mid],
    }
    for mid in _ORDER
]


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    m = (model or "fast").lower().strip().replace("_", "-")
    # Map staff / legacy ids to billed tiers (keep grok-4.3 / grok-max rates)
    if m in PRICING:
        pass
    elif m in ("grok-max",) or m.startswith("grok-4.5"):
        m = "grok-max"
    elif "4.3" in m or m in ("grok-3", "grok"):
        m = "grok-4.3"
    elif m.startswith("grok"):
        m = "grok-4.3"
    elif m.startswith("vps-") or m.startswith("qwen") or m.startswith("ollama"):
        try:
            from .agent_scaffold import map_model
            m = map_model(m)
        except Exception:
            m = "fast"
    rate = PRICING.get(m, PRICING.get("fast", 1.50))
    return round((input_tokens + output_tokens) * rate / 1_000_000, 6)


def estimate_tokens(text: str) -> int:
    """Estimate tokens for billing (slightly aggressive so we do not under-charge).

    Rules of thumb:
      - English prose ≈ 4 chars/token; code/JSON/CJK denser ≈ 2.5–3.5
      - We use ~3.0 chars/token + word heuristic + small padding
    """
    s = text or ""
    if not s:
        return 0
    n = len(s)
    # Char heuristic (ceil)
    by_chars = max(1, (n + 2) // 3)
    # Word heuristic — punctuation/symbols inflate real BPE counts
    words = len(s.split())
    by_words = max(1, int(words * 1.35) + 1)
    # Dense JSON / skill blocks: few spaces → boost
    if n > 40 and (s.count(" ") + s.count("\n")) < max(1, n // 20):
        by_chars = max(by_chars, (n + 1) // 2)
    return max(by_chars, by_words)


def estimate_messages_tokens(messages: list[dict] | None) -> int:
    """Count all chat roles + framing overhead (not just last user line)."""
    total = 0
    for m in messages or []:
        # Per-message role / separator overhead (OpenAI-style chat markup)
        total += 8
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            # Multimodal content blocks
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text") or part.get("content") or ""))
                else:
                    total += estimate_tokens(str(part))
        else:
            total += estimate_tokens(str(content or ""))
    return max(1, total) if messages else 0


def format_token_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def public_rates() -> list[dict]:
    """Transparent rates table for Billing UI."""
    out = []
    for mid in _ORDER:
        if mid in ("image", "video"):
            continue
        out.append({
            "id": mid,
            "label": MODEL_LABELS[mid],
            "blurb": MODEL_BLURBS.get(mid, ""),
            "usd_per_1m": PRICING[mid],
            "group": "managed",
        })
    # Event pricing summary rows
    for kind, row in EVENT_PRICING.items():
        if kind.startswith("voice") or kind == "premium-comm":
            continue
        usd = row.get("usd") if isinstance(row, dict) else None
        meter_tok = int(row.get("meter_tokens") or 0) if isinstance(row, dict) else 0
        if usd is None:
            blurb = (
                f"Token-metered skill action (~{meter_tok} tokens from included pool)"
                if meter_tok
                else "Token-metered action (included pool first)"
            )
        else:
            blurb = f"Flat ${float(usd):.2f} per generation"
        out.append({
            "id": kind,
            "label": MODEL_LABELS.get(kind, kind.replace("-", " ").title()),
            "blurb": blurb,
            "usd_per_1m": PRICING.get(kind, 0),
            "flat_usd": usd,
            "group": "media" if usd is not None else "skills",
        })
    return out
