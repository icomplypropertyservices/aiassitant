"""Audit SKILL_CATALOG vs HANDLER_TABLE + handlers_all implementations."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_skills import (  # noqa: E402
    SKILL_CATALOG,
    DEFAULT_ENABLED,
    HANDLER_TABLE,
    DEFAULT_SKILL_HANDLER,
    CUSTOM_SKILL_HANDLER,
)
from app.skills import handlers_all as _handlers  # noqa: E402

ids = [s["id"] for s in SKILL_CATALOG]
uniq = list(dict.fromkeys(ids))
dups = [i for i, c in Counter(ids).items() if c > 1]

handler_funcs = {
    n for n, v in vars(_handlers).items() if n.startswith("_skill_") and callable(v)
}

# Dedicated wiring: HANDLER_TABLE entry whose function exists
table_wired = set()
table_broken = []
for sid, entry in HANDLER_TABLE.items():
    fname = entry[0] if isinstance(entry, tuple) else entry
    if fname in handler_funcs or hasattr(_handlers, fname):
        table_wired.add(sid)
    else:
        table_broken.append((sid, fname))

# Catalog skills not in table fall through to DEFAULT_SKILL_HANDLER (catalog deliverable)
default_ok = DEFAULT_SKILL_HANDLER in handler_funcs or hasattr(
    _handlers, DEFAULT_SKILL_HANDLER
)
custom_ok = CUSTOM_SKILL_HANDLER in handler_funcs or hasattr(
    _handlers, CUSTOM_SKILL_HANDLER
)

catalog_in_table = [i for i in uniq if i in HANDLER_TABLE]
catalog_default = [i for i in uniq if i not in HANDLER_TABLE]
# "Unwired" only if no table entry AND no default deliverable handler
unwired = catalog_default if not default_ok else []

premium = sorted({s["id"] for s in SKILL_CATALOG if s.get("premium")})
by_role = Counter()
for s in SKILL_CATALOG:
    for r in s.get("roles") or []:
        by_role[r] += 1

prefix = Counter()
for i in uniq:
    prefix[i.split("_")[0]] += 1

print("=== SKILL AUDIT ===")
print(f"catalog_entries:     {len(ids)}")
print(f"unique_ids:          {len(uniq)}")
print(f"duplicate_ids:       {dups or 'none'}")
print(f"DEFAULT_ENABLED:     {len(DEFAULT_ENABLED) if hasattr(DEFAULT_ENABLED, '__len__') else DEFAULT_ENABLED}")
print(f"premium_skills:      {len(premium)}")
print(f"HANDLER_TABLE:       {len(HANDLER_TABLE)}")
print(f"_skill_* handlers:   {len(handler_funcs)}")
print(f"table_wired:         {len(table_wired)}")
print(f"table_broken:        {len(table_broken)} {table_broken[:10]}")
print(f"catalog_in_table:    {len(catalog_in_table)}")
print(f"catalog_default:     {len(catalog_default)} (via {DEFAULT_SKILL_HANDLER})")
print(f"default_handler_ok:  {default_ok}")
print(f"custom_handler_ok:   {custom_ok}")
print(f"truly_unwired:       {len(unwired)}")
if unwired:
    print("unwired_sample:", ", ".join(unwired[:30]))
print("roles:", dict(by_role))
print("top_prefixes:", prefix.most_common(15))

lines = [
    "# Skills audit",
    "",
    f"- Catalog entries: **{len(ids)}**",
    f"- Unique IDs: **{len(uniq)}**",
    f"- Duplicate IDs: **{', '.join(dups) or 'none'}**",
    f"- Premium (wallet): **{len(premium)}**",
    f"- HANDLER_TABLE entries: **{len(HANDLER_TABLE)}**",
    f"- `_skill_*` functions (handlers_all): **{len(handler_funcs)}**",
    f"- Table-wired catalog skills: **{len(catalog_in_table)}**",
    f"- Default deliverable path: **{len(catalog_default)}** via `{DEFAULT_SKILL_HANDLER}`",
    f"- Default handler present: **{default_ok}**",
    f"- Custom skill handler present: **{custom_ok}**",
    f"- Truly unwired (no table + no default): **{len(unwired)}**",
    f"- Broken table entries (missing fn): **{len(table_broken)}**",
    "",
    "## Architecture",
    "",
    "1. `HANDLER_TABLE` maps skill_id → implementation for side-effect skills.",
    "2. Catalog skills without a table entry run `_skill_catalog_deliverable` (LLM brief).",
    "3. Workspace-created skills use `_skill_run_created`.",
    "",
    "## Duplicates",
    "",
]
if dups:
    for d in dups:
        lines.append(f"- `{d}` × {ids.count(d)}")
else:
    lines.append("_none_")

lines += ["", "## Broken HANDLER_TABLE entries", ""]
if table_broken:
    for sid, fname in table_broken:
        lines.append(f"- `{sid}` → `{fname}` **MISSING**")
else:
    lines.append("_none_")

lines += ["", "## Premium skills", ""]
for p in premium:
    meta = next(s for s in SKILL_CATALOG if s["id"] == p)
    lines.append(
        f"- `{p}` — {meta.get('name')} — "
        f"${meta.get('cost_credits', '?')} — meter `{meta.get('meter_kind', 'premium-comm')}`"
    )

lines += ["", "## HANDLER_TABLE (dedicated side-effect skills)", ""]
lines.append("| ID | Handler | Mode |")
lines.append("|----|---------|------|")
for sid, entry in sorted(HANDLER_TABLE.items()):
    fname, mode, extras = entry
    extra_s = f" {extras}" if extras else ""
    lines.append(f"| `{sid}` | `{fname}` | {mode}{extra_s} |")

lines += ["", "## Sample catalog-default skills (first 40)", ""]
for i in catalog_default[:40]:
    lines.append(f"- `{i}`")
if len(catalog_default) > 40:
    lines.append(f"- … and {len(catalog_default) - 40} more")

out = ROOT / "SKILLS_AUDIT.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nWrote {out}")
