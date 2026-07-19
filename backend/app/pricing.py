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
    # Internal staff ids map to quality rates if they leak into billing rows
    "grok-max": 12.00,
}

# Flat USD + meter token weights per event (tokens always applied)
EVENT_PRICING = {
    "voice-stt": {"usd": 0.004, "meter_tokens": 120},   # speech → text
    "voice-tts": {"usd": 0.003, "meter_tokens": 100},   # text → speech
    "voice-call": {"usd": 0.08, "meter_tokens": 400},
    "image": {"usd": 0.06, "meter_tokens": 1200},
    "video": {"usd": 0.25, "meter_tokens": 4000},
    "premium-comm": {"usd": 0.02, "meter_tokens": 100},
    # Non-LLM skill actions — tokens meter, included pool first (no forced wallet flat)
    "skill-read": {"usd": None, "meter_tokens": 20},
    "skill-write": {"usd": None, "meter_tokens": 50},
    "skill-action": {"usd": None, "meter_tokens": 35},
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
}

MODEL_GROUPS = [
    ("managed", "Managed chat"),
    ("media", "Media"),
]

# Client-visible order
_ORDER = ["fast", "quality", "reasoning", "large", "small", "medium", "image", "video"]

MODEL_CATALOG = [
    {
        "id": mid,
        "label": MODEL_LABELS[mid],
        "provider": "managed",
        "group": "media" if mid in ("image", "video") else "managed",
        "group_label": "Media" if mid in ("image", "video") else "Managed chat",
        "blurb": MODEL_BLURBS.get(mid, ""),
        "usd_per_1m": PRICING[mid],
    }
    for mid in _ORDER
]


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    m = (model or "fast").lower().strip().replace("_", "-")
    # Map staff / legacy ids to billed tiers
    if m in ("grok-max", "grok") or m.startswith("grok"):
        m = "quality"
    if m.startswith("vps-") or m.startswith("qwen") or m.startswith("ollama"):
        try:
            from .agent_scaffold import map_model
            m = map_model(m)
        except Exception:
            m = "fast"
    rate = PRICING.get(m, PRICING.get("fast", 1.50))
    return round((input_tokens + output_tokens) * rate / 1_000_000, 6)


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


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
        out.append({
            "id": kind,
            "label": MODEL_LABELS.get(kind, kind.title()),
            "blurb": f"Flat ${row['usd']:.2f} per generation",
            "usd_per_1m": PRICING.get(kind, 0),
            "flat_usd": row["usd"],
            "group": "media",
        })
    return out
