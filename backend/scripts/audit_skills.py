"""Audit SKILL_CATALOG vs execute_skill handlers."""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_skills import SKILL_CATALOG, DEFAULT_ENABLED  # noqa: E402

src = (ROOT / "app" / "agent_skills.py").read_text(encoding="utf-8")

ids = [s["id"] for s in SKILL_CATALOG]
uniq = list(dict.fromkeys(ids))
dups = [i for i, c in Counter(ids).items() if c > 1]

exec_start = src.find("async def execute_skill")
if exec_start < 0:
    exec_start = src.find("def execute_skill")
exec_sec = src[exec_start:] if exec_start >= 0 else ""

funcs = set(re.findall(r"(?:async )?def _skill_([a-z0-9_]+)", src))
eq_handlers = set(re.findall(r'skill_id\s*==\s*["\']([a-z0-9_]+)["\']', exec_sec))
in_sets = re.findall(r"skill_id\s+in\s+\{([^}]+)\}", exec_sec)
for block in in_sets:
    eq_handlers |= set(re.findall(r'["\']([a-z0-9_]+)["\']', block))

mentioned = {i for i in uniq if i in exec_sec}
has_func = {i for i in uniq if i in funcs or f"skill_{i}" in funcs}

implementedish = mentioned | has_func
stub_or_missing = [i for i in uniq if i not in implementedish]

premium = sorted({s["id"] for s in SKILL_CATALOG if s.get("premium")})
by_role = Counter()
for s in SKILL_CATALOG:
    for r in s.get("roles") or []:
        by_role[r] += 1

# Group by prefix
prefix = Counter()
for i in uniq:
    prefix[i.split("_")[0]] += 1

print("=== SKILL AUDIT ===")
print(f"catalog_entries: {len(ids)}")
print(f"unique_ids:      {len(uniq)}")
print(f"duplicate_ids:   {dups}")
print(f"DEFAULT_ENABLED: {len(DEFAULT_ENABLED) if hasattr(DEFAULT_ENABLED, '__len__') else DEFAULT_ENABLED}")
print(f"premium_skills:  {len(premium)} -> {premium}")
print(f"mentioned_in_execute: {len(mentioned)}")
print(f"_skill_* handlers:    {len(funcs)}")
print(f"likely_unwired:       {len(stub_or_missing)}")
if stub_or_missing:
    print("unwired_sample:", ", ".join(stub_or_missing[:50]))
print("roles:", dict(by_role))
print("top_prefixes:", prefix.most_common(25))

# Write markdown report
lines = [
    "# Skills audit",
    "",
    f"- Catalog entries: **{len(ids)}**",
    f"- Unique IDs: **{len(uniq)}**",
    f"- Duplicate IDs: **{', '.join(dups) or 'none'}**",
    f"- Premium (wallet): **{len(premium)}**",
    f"- Mentioned in `execute_skill`: **{len(mentioned)}**",
    f"- `_skill_*` functions: **{len(funcs)}**",
    f"- Likely unwired / draft-only: **{len(stub_or_missing)}**",
    "",
    "## Duplicates",
    "",
]
for d in dups:
    lines.append(f"- `{d}` × {ids.count(d)}")
lines += ["", "## Premium skills", ""]
for p in premium:
    meta = next(s for s in SKILL_CATALOG if s["id"] == p)
    lines.append(
        f"- `{p}` — {meta.get('name')} — "
        f"${meta.get('cost_credits', '?')} — meter `{meta.get('meter_kind', 'premium-comm')}`"
    )
lines += ["", "## Full unique catalog", ""]
lines.append("| ID | Name | Roles | Premium | In execute? |")
lines.append("|----|------|-------|---------|-------------|")
for s in SKILL_CATALOG:
    if s["id"] in {x["id"] for x in SKILL_CATALOG if x is not s and x["id"] == s["id"]}:
        # only first occurrence rows for dups still listed once via uniq loop below
        pass
seen = set()
for s in SKILL_CATALOG:
    if s["id"] in seen:
        continue
    seen.add(s["id"])
    roles = ",".join(s.get("roles") or [])
    prem = "yes" if s.get("premium") else ""
    wired = "yes" if s["id"] in implementedish else "**NO**"
    lines.append(
        f"| `{s['id']}` | {s.get('name','').replace('|','/')} | {roles} | {prem} | {wired} |"
    )
lines += ["", "## Unwired / draft-only (not found in execute_skill)", ""]
for i in stub_or_missing:
    lines.append(f"- `{i}`")

out = ROOT / "SKILLS_AUDIT.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nWrote {out}")
