# Code review + skills fixes — 2026-07-19

**Scope:** AI Business Assistant monorepo — skill runtime, catalog dispatch, local smoke.  
**Standard:** Strict maintainability review (structure + correctness).  
**Verdict:** Skills runtime is **healthy enough to ship** after this pass. Catalog is fully dispatchable; critical NameError bugs in handlers are fixed. Giant-file debt remains (handlers_all ~3.4k, agent_skills ~2.9k) but is improved vs the historical 6k+ god file.

---

## What was broken (and fixed)

| Issue | Severity | Fix |
|-------|----------|-----|
| `handlers_all.py` used `skills_for_template` / `set_enabled_skills` / pack helpers **without importing them** | **Critical** | Late-bound helpers on `skills/bridge.py`; handlers import them at module level |
| `use_app` accepted numeric connection ids (`"1"`) as app keys | High UX | Gate in `skills_policy.integration_skill_available` + clearer handler errors |
| `research` / `summarize` / `generate_content` ignored required fields | Medium | Validate inputs; return structured `brief` for chat follow-through |
| `AgentMessage(status=…)` fragile on older schemas | Medium | Conditional kwargs + `schema_migrate` columns for `agent_messages` / `agent_memories` |
| Audit script only scanned `agent_skills.py` (reported 1261 “unwired”) | Tooling | Rewrote to measure `HANDLER_TABLE` + `handlers_all` + default deliverable path |
| `DEFAULT_ENABLED` = entire 1282-id catalog | Product | Member role pack via `default_enabled_for_role` |

---

## Skills architecture (current)

```text
execute_skill
  → permission / plan / integration gates
  → _dispatch_skill
       ├─ HANDLER_TABLE[skill_id] → _skill_* in handlers_all (146 side-effect skills)
       ├─ custom CreatedSkill     → _skill_run_created
       └─ else                    → _skill_catalog_deliverable (1136 mega-pack skills)
```

| Metric | Value |
|--------|------:|
| Catalog unique IDs | 1282 |
| HANDLER_TABLE entries | 146 |
| `_skill_*` functions | 129 |
| Broken table entries | 0 |
| Truly unwired | 0 |
| Premium | 31 |

---

## Local verification

- Backend: `http://127.0.0.1:8000` (`/health` 200, version 1.5.0)
- Frontend: `http://127.0.0.1:5173/` (Vite ready)
- Smoke: `backend/scripts/skill_smoke_local.py` → **23/23 PASS**
  - CRM, messaging, spawn, assign_human, catalog deliverable (`qualify_lead`), expected soft-fails for unconnected `use_app`

---

## Remaining structural debt (not blockers for this pass)

1. **`handlers_all.py` ~3.4k lines** — next split: `skills/crm.py`, `skills/comms.py`, `skills/meta_agents.py`, `skills/integrations.py`, `skills/meetings.py`
2. **`agent_skills.py` still holds catalog + dispatch + enable logic** — catalog extract to `skills/catalog.py` would finish the decomposition
3. **Frontend god pages** (AgentDetail, Settings, Business, global.css) — unchanged this pass
4. **Live production skill test** (`scripts/test_skills_live.py`) still needs redeploy for these fixes to hit `aibusinessagent.xyz`

---

## Approval bar

| Criterion | Status |
|-----------|--------|
| No clear skill runtime regression | **Pass** |
| Catalog fully dispatchable | **Pass** |
| Missing imports / NameErrors fixed | **Pass** |
| File-size under 1k ideal | **Fail** (debt reduced, not eliminated) |
| Spaghetti elif dispatch | **Pass** (already registry / HANDLER_TABLE) |

**Recommendation:** Keep local servers running; redeploy backend when ready so production picks up the handler import + `use_app` gate fixes.
