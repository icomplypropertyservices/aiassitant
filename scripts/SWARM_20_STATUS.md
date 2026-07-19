# Swarm 20 status

**Scanned:** 2026-07-19 (filesystem + report artifacts under `scripts/`)  
**Workspace:** `C:\Users\E-Store\ai-business-assistant\ai-business-assistant`  
**Production host (from reports):** `https://www.aibusinessagent.xyz`

Factual status only — no secrets.

---

## 1. UI container work — **in progress**

Auto-chain UI surfaces exist in the local SPA tree and were modified 2026-07-19. Treat as **work in progress** (local frontend; not re-asserted as fully shipped on production SPA build).

| Surface | File | What is present |
|---------|------|-----------------|
| Tasks board columns / chain tags | `frontend/src/pages/TasksBoard.jsx` | `chainMeta()`, `ChainTags` (Goal / Auto-chain / Step / Parent #), column layout (`todo` → `failed`) |
| Dashboard goals strip | `frontend/src/pages/Dashboard.jsx` | Counts open tasks with labels `goal` or `auto-chain` from board API |
| Agent chat goal-chain card | `frontend/src/pages/AgentChat.jsx` | Parses `r.goal_chain` from chat API; renders “Goal chain started / already running” meta |
| App shell | `frontend/src/components/AppLayout.jsx` | Layout shell (Header / Sider / Content); route hosts tasks/chat/dashboard |

**Status:** UI container work for auto-chain / goal display is **in progress** in local source.

---

## 2. Auto-chain files (inventory)

### Core + docs

| Path | Role | Present |
|------|------|---------|
| `backend/app/task_chain.py` | Goal → parent → children → roll-up (`looks_like_goal`, `start_goal_chain`, `maybe_auto_chain_from_chat`, `on_task_finished`, …) | **Yes** |
| `docs/AUTO_CHAIN.md` | End-to-end auto-chain documentation | **Yes** |
| `scripts/SWARM_STATUS.md` | Prior swarm inventory (task_chain + browser + blockers) | **Yes** |

### Wiring (consumers)

| Path | How used |
|------|----------|
| `backend/app/routers/agents.py` | Chat path → `maybe_auto_chain_from_chat` |
| `backend/app/task_runner.py` | On complete/fail → `on_task_finished` |
| `backend/app/agent_skills.py` | Skill `execute_goal` → `start_goal_chain` |
| `backend/app/agent_prompts.py` | Prompts agents to use `execute_goal` for multi-step goals |

### Probes / reports (auto-chain specific)

| Path | Present | Notes |
|------|---------|-------|
| `scripts/_live_chat_chain_probe.py` | **Yes** | Production chat auto-chain probe |
| `scripts/_live_chat_chain_probe.log` | **Yes** | Partial log (HEALTH/LOGIN/ME/TRIAL/ENSURE_ORCH/AGENTS/CHAT) |
| `scripts/live_chain_report.json` | **Yes** | Generated `2026-07-19T11:43:16Z` |
| `scripts/_live_team_probe.py` | **Yes** | Team/hierarchy probe for delegation headroom |
| `scripts/live_team_report.json` | **Yes** | Generated same window; see §4 |

### Frontend (auto-chain UI — see §1)

- `frontend/src/pages/TasksBoard.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/AgentChat.jsx`

---

## 3. Live browser status (reports exist)

### Artifacts

| Artifact | Present | Timestamp (local) |
|----------|---------|-------------------|
| `scripts/live_browser_report_A.json` | **Yes** | 2026-07-19 ~13:42 |
| `scripts/live_browser_report_B.json` | **Yes** | 2026-07-19 ~13:41 |
| `scripts/live_browser_e2e.mjs` | **Yes** | Playwright suite |
| `scripts/live_browser_A_run.log` | **Yes** | Agent A run log |
| `scripts/live_browser_B_stdout.txt` | **Yes** | Agent B stdout |
| `scripts/live-screenshots/` | **Yes** | 14 PNGs (A nav/dashboard/hierarchy/templates/agents; B chat/tasks/meetings/billing) |

### Agent A — `live_browser_report_A.json`

| Field | Value |
|-------|--------|
| Base | `https://www.aibusinessagent.xyz` |
| Email | `test+live1784460867@aibusinessagent.xyz` |
| Result | **10 pass / 0 fail** |
| `at` | `2026-07-19T11:42:03.605Z` |

Passed checks: `dashboard_loaded`, `nav/business`, `nav/workspace`, `nav/`, `create_company_api` (existing company / plan limit — 1 company “Live Demo Co” id=16), `agents_page`, `ensure_orchestrator` (id=9), `templates_catalog` (count=41), `hierarchy_page`, `spawn_agent` (treated pass as existing plan limit — 3 agents already).

### Agent B — `live_browser_report_B.json`

| Field | Value |
|-------|--------|
| Base | same |
| Email | same |
| Result | **11 pass / 0 fail** |
| `at` | `2026-07-19T11:41:18.152Z` |

Passed checks: `have_agent` (id=9), `agent_chat_page`, `chat_instruction`, `chat_ui_send`, `create_task` (id=36 queued), `save_file`, `save_picture`, `create_meeting` (id=14), `meeting_room_ui`, `tasks_page`, `billing_page`.

### Screenshots on disk

`a_dashboard`, `a_nav__business`, `a_nav__workspace`, `a_nav__`, `a_agents_console`, `a_templates`, `a_hierarchy`, `b_chat_ui_send`, `b_meetings`, `b_meeting_room`, `b_tasks`, `b_billing`, `b_agent_chat`, `b_agent_chat_after`.

**Browser verdict:** Latest A/B E2E reports are **green** (A 10/0, B 11/0). Plan caps are still reflected in A details (1 company, 3 agents).

---

## 4. Related live probes (not browser UI)

### `live_chain_report.json` (API auto-chain probe)

- `generated_at`: `2026-07-19T11:43:16.071473+00:00`
- `user_id`: 19, `agent_id`: 9
- `ensure_orchestrator`: **HTTP 200**, id=9 OK
- Subsequent steps (`skills_catalog`, `execute_goal_skill`, `chat_goal`, `create_task_fallback`, `list_tasks`): **HTTP 401** `"Invalid API key"`
- Summary flags: `execute_goal_ok: false`, `chat_auto_chain_detected: false`, `parent_goal_found: false`
- `deploy_note` in file claims production may lack `execute_goal` / local `task_chain` deploy — **this run’s step errors are auth 401**, so deploy vs auth cannot be cleanly separated from this artifact alone

### `live_team_report.json`

- Top-level `"ok": true` but steps mostly **401 Invalid API key** (trial, orchestrator, seed-starter-team, agents, hierarchy)
- `agent_count`: 0 in report body (auth failure, not a live empty org vs browser-proven 3 agents)

### `_live_chat_chain_probe.log` (partial)

- HEALTH 200, version 1.5.0 production  
- LOGIN 200, ME 200 trial  
- ENSURE_ORCH 200 id=9, AGENTS 200 count=3  
- CHAT posting to agent 9 … (log ends mid-run in captured file)

### Browser vs API probe mismatch

Browser E2E used SPA/`localStorage` session successfully. Later JSON chain/team probes show **invalid API key** for many endpoints — treat browser A/B as authoritative for UI reachability; treat chain/team JSON as **incomplete / auth-broken for that key**, not as a full auto-chain production proof.

---

## 5. One-line Swarm 20 verdict

**UI container work for auto-chain (TasksBoard / Dashboard / AgentChat) is in progress in local frontend.**  
**Auto-chain backend module + wiring + docs + probes exist locally.**  
**Live browser A/B reports exist and pass (10/0 and 11/0).**  
**Dedicated auto-chain API report exists but did not prove chain creation (401s after orchestrator ensure).**

*Generated from filesystem + `scripts/*report*` artifacts. Secrets omitted.*
