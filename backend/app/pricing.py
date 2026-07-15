"""Customer-facing model catalog + rates (USD per 1M tokens)."""

# Full public model picker — keep labels clear; rates include SaaS markup.
PRICING = {
    # ── Our VPS (generic) ─────────────────────────────────────────
    "vps-fast": 0.80,
    "vps-quality": 1.60,
    # ── Our VPS — Qwen fleet ──────────────────────────────────────
    "vps-qwen-fast": 0.95,
    "vps-qwen-7b": 0.90,
    "vps-qwen-14b": 1.40,
    "vps-qwen-32b": 2.20,
    "vps-qwen-coder": 1.90,
    "vps-qwen-coder-7b": 1.20,
    "vps-qwen-coder-14b": 1.70,
    "vps-qwen-coder-32b": 2.40,
    "vps-qwen-large": 3.80,
    "vps-qwen-72b": 3.80,
    # ── Anthropic Claude ──────────────────────────────────────────
    "claude-haiku": 4.50,
    "claude-sonnet": 18.00,
    "claude-opus": 45.00,
    # ── xAI Grok ──────────────────────────────────────────────────
    "grok-fast": 4.00,
    "grok-mini": 4.00,
    "grok": 12.00,
    "grok-2": 10.00,
    "grok-3": 12.00,
    "grok-4": 15.00,
}

MODEL_LABELS = {
    "vps-fast": "Our VPS – Fast",
    "vps-quality": "Our VPS – Quality",
    "vps-qwen-fast": "Our VPS – Qwen Fast",
    "vps-qwen-7b": "Our VPS – Qwen 7B",
    "vps-qwen-14b": "Our VPS – Qwen 14B",
    "vps-qwen-32b": "Our VPS – Qwen 32B",
    "vps-qwen-coder": "Our VPS – Qwen Coder",
    "vps-qwen-coder-7b": "Our VPS – Qwen Coder 7B",
    "vps-qwen-coder-14b": "Our VPS – Qwen Coder 14B",
    "vps-qwen-coder-32b": "Our VPS – Qwen Coder 32B",
    "vps-qwen-large": "Our VPS – Qwen Large",
    "vps-qwen-72b": "Our VPS – Qwen 72B",
    "claude-haiku": "Premium Claude Haiku",
    "claude-sonnet": "Premium Claude Sonnet",
    "claude-opus": "Premium Claude Opus",
    "grok-fast": "Premium xAI Grok Fast",
    "grok-mini": "Premium xAI Grok Mini",
    "grok": "Premium xAI Grok",
    "grok-2": "Premium xAI Grok 2",
    "grok-3": "Premium xAI Grok 3",
    "grok-4": "Premium xAI Grok 4",
}

MODEL_GROUPS = [
    ("vps", "Our VPS"),
    ("qwen", "Our VPS – Qwen"),
    ("anthropic", "Premium Claude"),
    ("xai", "Premium xAI Grok"),
]


def _provider(model_id: str) -> str:
    if model_id.startswith("claude"):
        return "anthropic"
    if model_id.startswith("grok"):
        return "xai"
    return "ollama"


def _group(model_id: str) -> str:
    if model_id.startswith("claude"):
        return "anthropic"
    if model_id.startswith("grok"):
        return "xai"
    if "qwen" in model_id:
        return "qwen"
    return "vps"


# Ordered catalog for UI (stable picker order)
_ORDER = [
    "vps-fast", "vps-quality",
    "vps-qwen-fast", "vps-qwen-7b", "vps-qwen-14b", "vps-qwen-32b",
    "vps-qwen-coder", "vps-qwen-coder-7b", "vps-qwen-coder-14b", "vps-qwen-coder-32b",
    "vps-qwen-large", "vps-qwen-72b",
    "claude-haiku", "claude-sonnet", "claude-opus",
    "grok-fast", "grok-mini", "grok", "grok-2", "grok-3", "grok-4",
]

MODEL_CATALOG = [
    {
        "id": mid,
        "label": MODEL_LABELS[mid],
        "provider": _provider(mid),
        "group": _group(mid),
        "group_label": dict(MODEL_GROUPS).get(_group(mid), "Other"),
    }
    for mid in _ORDER
    if mid in PRICING
]


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = PRICING.get(model, 0.80)
    return round((input_tokens + output_tokens) * rate / 1_000_000, 6)


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def format_token_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
