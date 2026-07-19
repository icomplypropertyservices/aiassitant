"""Canonical tag normalization for CRM customers, products, and Shopify."""
from __future__ import annotations


def normalize_tags(tags) -> str:
    """Accept list or comma/semicolon string → clean comma-separated tags (no spaces)."""
    if tags is None:
        return ""
    if isinstance(tags, (list, tuple, set)):
        parts = [str(t).strip() for t in tags if str(t).strip()]
    else:
        raw = str(tags).replace(";", ",")
        parts = [t.strip() for t in raw.split(",") if t.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return ",".join(out)


def tags_list(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]
