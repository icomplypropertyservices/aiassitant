# Swarm status

**Scanned:** 2026-07-19 (filesystem + report artifacts under `scripts/`)  
**Workspace:** `C:\Users\E-Store\ai-business-assistant\ai-business-assistant`  
**Production host (from reports):** `https://www.aibusinessagent.xyz`

Factual inventory only — no secrets written here.

---

## 1. `task_chain.py` — present and wired

| Item | Path / evidence |
|------|-----------------|
| Module exists | `backend/app/task_chain.py` |
| Purpose (module docstring) | Goal → parent task → subtasks → hierarchy delegate → queue → roll-up on complete/fail |
| Used by | chat, skills (`execute_goal` / related), `task_runner` |

### Public entry points (in module)

| Function | Role |
|----------|------|
| `looks_like_goal(text)` | Heuristic for long / action-oriented prompts |
| `start_goal_chain(...)` | Full auto chain: parent goal + delegated children + optional auto-queue |
| `maybe_auto_chain_from_chat(...)` | Chat path: if goal-like → `start_goal_chain` (dedupes similar open auto-chain tasks) |
| `on_task_finished(...)` | Roll-up / next-step handling when a task completes or fails |
| `pick_assignee` / `decompose_goal` | Assignment + step breakdown helpers |

### Wiring

| Consumer | File | How |
|----------|------|-----|
| **Chat** | `backend/app/routers/agents.py` (~1501–1519) | After skill post-process: `from ..task_chain import maybe_auto_chain_from_chat` → appends “Auto-chain started…” / “already running” to assistant reply |
| **Task runner** | `backend/app/task_runner.py` (~175–178 complete, ~226–229 fail) | On success/fail: `from .task_chain import on_task_finished` → `await on_task_finished(db, t, final_status=...)` |
| **`execute_goal` skill** | `backend/app/agent_skills.py` | Skill catalog id `"execute_goal"` (~103–110); dispatcher `skill_id == "execute_goal"` → `_skill_execute_goal` (~2364–2365); `_skill_execute_goal` imports `start_goal_chain` and calls it with goal/title/priority/steps (~2956–2992) |
| **Prompts** | `backend/app/agent_prompts.py` | Instructs agents to use `execute_goal` for multi-step human goals |

**Status:** Code path is complete in-repo. Live chat E2E (report B) exercised agent chat + task create; it did not specifically assert auto-chain parent/child labels in the JSON report.

---

## 2. Demo login path

### A. Credentials artifacts (local, gitignored-style hidden files)

| File | Present | Role |
|------|---------|------|
| `scripts/.demo_login.json` | **Yes** (2026-07-19) | JSON: `email`, `password`, `api_key`, `user_id`, `agent_id` for live browser E2E |
| `scripts/.demo_token` | **Yes** (2026-07-19) | Token cache for API smoke (`demo_smoke_report.json` → `token_source: scripts/.demo_token`) |

Do not commit these files. Do not paste keys into docs/tickets.

### B. Live browser consumer

- `scripts/live_browser_e2e.mjs` reads `scripts/.demo_login.json`
- Injects `api_key` / `token` / `user` into SPA `localStorage` on `/agents/login`, or can use form login
- Default base: `https://www.aibusinessagent.xyz` → app at `/agents`

### C. Account bootstrap scripts

| Script | Role |
|--------|------|
| `scripts/create_test_account.py` | Register/login throwaway on prod (`BASE_URL` default `https://www.aibusinessagent.xyz`), default password `TestAgent1`, activates trial, bootstrap orchestrator |
| `scripts/bootstrap_demo_ecosystem.py` | Fuller demo: register/login → trial → orchestrator → tasks → meeting (`DEMO_PASSWORD` / `ABA_*` env) |

### D. Product login (production SPA)

1. `https://www.aibusinessagent.xyz/agents/login`
2. `POST /api/auth/login` or `POST /api/auth/register`
3. New users: plan gate → `POST /api/billing/plan` `{ "plan": "trial" }` before org/agents (402 without plan)
4. Local-only seed admin `admin@local` is **not** production (prod login 401; seed gated off when production) — see `backend/app/main.py` `allow_demo = not IS_PRODUCTION …`

### E. Marketing demo (no auth)

- `website/demo.html` + `website/js/demo.js` — client mock walkthrough, no API login

---

## 3. Live browser reports (present)

### Reports & logs

| Artifact | Present | Summary |
|----------|---------|---------|
| `scripts/live_browser_report_A.json` | **Yes** | Agent A: **9 pass / 1 fail** — `2026-07-19T11:40:32.932Z` |
| `scripts/live_browser_report_B.json` | **Yes** | Agent B: **11 pass / 0 fail** — `2026-07-19T11:41:18.152Z` |
| `scripts/live_browser_e2e.mjs` | **Yes** | Playwright suite (`--agent=A\|B\|ALL`) |
| `scripts/live_browser_A_run.log` | **Yes** | Run log for A |
| `scripts/live_browser_B_stdout.txt` | **Yes** | Stdout for B |
| `scripts/live-screenshots/` | **Yes** | PNGs for A (dashboard, nav, hierarchy, templates, agents) and B (chat, tasks, meetings, billing, …) |
| `scripts/demo_smoke_report.json` | **Yes** | API smoke (not browser): health OK; some 402/404 |

### Agent A (`live_browser_report_A.json`)

- Base: `https://www.aibusinessagent.xyz`
- Email (demo account): `test+live1784460867@aibusinessagent.xyz`
- **Passed:** dashboard, nav/business, nav/workspace, nav/, create_company_api (existing company / plan limit noted), agents page, ensure_orchestrator (`id=9`), templates catalog (`count=41`), hierarchy page
- **Failed:** `spawn_agent` → **HTTP 400** — `"Your plan allows up to 3 agents. Upgrade on Billing."`
- Screenshots dir: `scripts/live-screenshots`

### Agent B (`live_browser_report_B.json`)

- Same base + email
- **All passed:** have_agent, agent_chat_page, chat_instruction (`/api/agents/9/chat` reply), chat_ui_send, create_task (queued), save_file (`/api/training/upload`), save_picture (`/api/media/image`), create_meeting (`id=14`), meeting_room_ui, tasks_page, billing_page

### Related smoke (API)

`demo_smoke_report.json`: templates non-empty (41); at least one **402** on `POST /api/agents/ensure-orchestrator` for the token used at that earlier smoke (“Choose a subscription plan…”) — trial must be active before org/agent bootstrap.

---

## 4. Remaining blockers

### Plan limits (confirmed live by browser report A)

| Limit | Evidence |
|-------|----------|
| **Max agents = 3** on trial/current plan | A `spawn_agent` failed 400 with plan allows up to 3 agents |
| **Max companies = 1** | A `create_company_api` detail: `"Your plan allows 1 companies. Upgrade on Billing."` (existing company kept; count=1, id=16 “Live Demo Co”) |
| **Subscription gate** | Without trial/paid plan: org/agents return **402** (“Choose a subscription plan to continue”) — bootstrap must call `POST /api/billing/plan` `{ "plan": "trial" }` |

Implication for swarm demos: multi-agent hierarchy / extra specialists cannot be spawned beyond plan caps until upgrade or higher plan limits in billing.

### Deploy / production ops (from `scripts/ECOSYSTEM_STATUS.md` scan + health payloads)

| # | Blocker | Evidence |
|---|---------|----------|
| D1 | **`CRON_SECRET` unset** | Health: `cron_secret_configured: false` — autonomy tick-all not safely secret-gated |
| D2 | **AgentBay not ready** | `/bay/api/health` → `ready: false`, issue: `BRIDGE_SECRET missing or weak` — agent bridge disabled |
| D3 | **Local ≠ clean deploy tree** | Workspace dirty vs production commit; deploys noted `gitDirty` — risk of drift (`task_chain` and other local work may not match what Vercel runs until redeploy) |
| D4 | Soft: email verify/reset inbox | Code present; not re-proven in latest browser pass |
| D5 | Soft: marketing cold start | `/` can be slow on cold; SPA/API healthier |
| D6 | Soft: sporadic 500s | Low-volume runtime errors noted in status scan |

### What is already green (do not treat as blockers)

- Production SPA login + trial + orchestrator ensure (browser A/B against live account with agent id 9)
- Chat instruction, task create, meetings, media/training upload (browser B)
- Templates catalog (41)
- Demo admin disabled on prod
- `task_chain` module + call sites present in **local** backend tree

---

## 5. Quick reference — re-run swarm checks

```powershell
cd C:\Users\E-Store\ai-business-assistant\ai-business-assistant

# Throwaway account + trial + orchestrator (writes nothing by default; live setup may also write .demo_login.json)
python scripts/create_test_account.py

# Full API-ish ecosystem bootstrap
python scripts/bootstrap_demo_ecosystem.py

# Browser E2E (requires scripts/.demo_login.json)
node scripts/live_browser_e2e.mjs --agent=A
node scripts/live_browser_e2e.mjs --agent=B
```

---

## 6. One-line swarm verdict

**`task_chain` is implemented and wired to chat, task_runner, and `execute_goal` in the local backend.**  
**Demo login path is scripted + cached in `.demo_login.json` / `.demo_token`.**  
**Live browser A/B reports exist (A: plan-limit fail on spawn; B: full pass).**  
**Remaining hard constraints: trial plan caps (agents/companies), prod cron/bridge secrets, and clean redeploy of local chain work if not yet on Vercel.**

*Generated from filesystem + `scripts/*report*` artifacts. Secrets omitted.*
