# Strict code quality review — 2026-07-19

Scope: recent product work (meetings, auto-chain, Twilio/Gmail, human notify, speed, privacy, UI shell).

## Verdict

**Do not rubber-stamp.** Behavior largely works on production, but there are **structural debt** items that fail the skill’s approval bar until addressed over time. **High-priority correctness fixes below were applied before redeploy.**

---

## Blockers / high conviction

### 1. `agent_skills.py` (~5025 lines) — file-size explosion

**Presumptive blocker.** This file should not keep absorbing every skill implementation.

| Action | Recommendation |
|--------|----------------|
| Extract | `skills_comms.py` (Twilio/email/Gmail wrappers) |
| Extract | `skills_meta.py` (spawn/clone/enable packs) |
| Extract | `skills_social.py` (FB/IG/X/LinkedIn) |
| Keep | Catalog + `execute_skill` dispatcher + thin imports |

Until split, every change risks merge conflict and review fatigue.

### 2. `_run_app` mutated `conn.app_id` (fixed)

**Bug/smell fixed:** temporarily writing `conn.app_id = "gmail"` risked dirty session state if commit ran mid-flight.

**Fix:** `run_app_action(..., app_id=...)` override; no mutation.

### 3. Sequential notify channels (fixed)

Email → SMS → push were sequential with no dependency.

**Fix:** `asyncio.gather` in `human_notify.notify_human`.

### 4. Bootstrap brand leakage (fixed earlier)

Hardcoded iComply/FAD companies for all users was a privacy/product boundary leak.

**Fix:** `default_companies_for_user()` only.

### 5. Public homepage private-looking stats (fixed earlier)

Marketing hero used real-looking tenant branding.

**Fix:** generic “Your company / Private to you”.

---

## Structural concerns (not all fixed this pass)

| Issue | Severity | Notes |
|-------|----------|--------|
| Giant skill catalog + handlers co-located | High | Needs extraction plan above |
| `integration_actions.py` ~950 lines | Medium | Near 1k; split Gmail into `gmail_actions.py` next |
| `api.js` GET cache magic | Medium | Works; document `invalidateApiCache` contract for page authors |
| Multiple skill aliases (`initiate_call`/`send_sms`) | Low | OK for agents; keep aliases → one implementation |
| Frontend page files bloated (AgentDetail 1.6k+ lines) | High | Pre-existing + UI waves; PageShell helps layout only |

---

## What is in good shape

- **`task_chain.py`**: clear goal → steps → rollup model
- **`agent_serialize` lean lists**: batch stats deletes N+1 on agent list
- **`dashboard` aggregates**: SQL sums/counts instead of loading all rows
- **`human_notify`**: single place for email+SMS+push + branded HTML
- **`channels`**: Twilio TTS + SMTP/Resend with clear configure errors
- **Meetings stack**: separate modules (`meeting_runner`, `serialize`, `extract`)

---

## Fixes applied in this review pass

1. `run_app_action(..., app_id=)` — no conn mutation  
2. `_run_app` uses override for gmail-via-google token  
3. `notify_human` parallelizes email/SMS/push  
4. Redeploy to production after fixes  

---

## Approval bar (skill)

| Criterion | Status |
|-----------|--------|
| No structural regression from review fixes | Pass |
| Dramatic simplification of agent_skills | **Fail** (debt remains) |
| File &gt;1k unjustified | **Fail** (`agent_skills.py`) |
| Spaghetti special-cases | Mitigated on `_run_app` / notify |
| Boundary leaks (brands) | Pass after privacy fix |

**Recommendation:** Ship the correctness fixes + redeploy. Schedule **agent_skills decomposition** as the next maintainability PR (non-optional for long-term health).

---

## Redeploy

Production target: `https://www.aibusinessagent.xyz` via `vercel --prod`.
