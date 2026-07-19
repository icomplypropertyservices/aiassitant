# Auto-chain: prompt → task → delegate → monitor → complete

Automatic multi-agent execution from a single human prompt (or agent skill).

**Product pipeline (must stay intact):**

```
prompt  →  task  →  delegate  →  monitor  →  complete
```

| Stage | What happens | Code |
|-------|----------------|------|
| **prompt** | Goal text from human chat or agent skill | chat / `execute_goal` |
| **task** | Parent goal task created (`goal,auto-chain,monitor`) | `start_goal_chain()` |
| **delegate** | Steps decomposed; assigned down hierarchy | `decompose_goal()` + `pick_assignee()` |
| **monitor** | Parent stays `in_progress`; autonomy runs queued children; progress events | autonomy tick + `on_task_finished` |
| **complete** | Siblings unlock sequentially; parent rolls up to `completed` / `review` / `failed` | `on_task_finished()` |

**Core module:** `backend/app/task_chain.py`  
**Execution:** `backend/app/task_runner.py` + `backend/app/autonomy.py`  
**Skills:** `backend/app/agent_skills.py` (`execute_goal`, `create_task`, `announce_plan`, …)

---

## End-to-end flow

```
one human prompt
        │
        ├─► chat auto-chain (orchestrator/lead + goal-like text)
        │       maybe_auto_chain_from_chat()
        │       · REST  POST /api/agents/{id}/chat
        │       · Live  WebSocket agent chat
        │
        └─► skill execute_goal  (```skill { "skill": "execute_goal", ... }```)
                _skill_execute_goal() → start_goal_chain()
                        │
                        ▼
              parent Task  (labels: goal,auto-chain,monitor)
              status: in_progress  ·  owner: orchestrator/lead
                        │
                        ▼
              decompose_goal()  →  N child steps (max 6 default, ≤12 via skill)
                        │
                        ▼
              hierarchy delegate  (pick_assignee per step)
              labels: auto-chain,step,{i}
              step 1 → queued (if assignee active)
              steps 2..N → todo  (sequential unlock)
                        │
                        ▼
              live_ops + WebSocket  (goal_chain_started)
                        │
                        ▼
              autonomy tick  (GET|POST /api/ops/autonomy/tick
                              or cron /api/ops/autonomy/tick-all)
                        │
                        ▼
              run_user_cycle → _run_queued_tasks → run_agent_task()
                        │
                        ▼
              on_task_finished()
                 · queue next sibling step (todo → queued)
                 · on fail: mark remaining todos failed (skipped)
                 · parent rollup when all children terminal
                 · escalate failed children (requeue=False)
                 · emit goal_chain_progress
```

---

## 1. Prompt (entry points)

A multi-step goal can start from:

| Source | When |
|--------|------|
| **Chat auto-chain** | Human messages orchestrator / lead (or sole agent) with goal-like text |
| **Skill `execute_goal`** | Agent emits a skill block during chat or task run |
| **Skill `create_task`** | Single task (optional `parent_task_id` for manual DAG) |
| **Skill `announce_plan`** | Plan banner + parent/children; string steps stay on announcer; dict steps may hierarchy-route |
| **HTTP** | `POST /api/agents/{id}/tasks`, `POST /api/agents/{id}/delegate`, skills run API |

### Goal detection (chat only)

`looks_like_goal(text)` in `task_chain.py`:

- length **&lt; 24** → not a goal  
- length **≥ 80** → treated as goal  
- otherwise requires action verbs: *build, create, launch, plan, run, execute, delegate, ship, research, implement, coordinate, organise/organize, set up, deliver, campaign, hire, analyse/analyze, fix, grow, scale, automate, manage, finish, complete, do this, get this done, make sure, ensure, …*

Chat auto-chain also requires the receiving agent to be **orchestrator**, **lead**, or `permission_level` in `admin` / `lead` — unless the workspace has only one active agent.

Dedup: if a similar open `auto-chain` task already exists (description head match against recent open statuses `todo`/`queued`/`in_progress`), chat returns `deduped: true` and does not spawn another chain.

---

## 2. Chat auto-chain

Automatic path — no skill block required. After the LLM reply (and optional skill parse), both chat surfaces call:

```text
maybe_auto_chain_from_chat(db, user, agent, human_text, skill_results=...)
```

| Surface | File / route |
|---------|----------------|
| REST chat | `POST /api/agents/{agent_id}/chat` in `backend/app/routers/agents.py` |
| Live WebSocket chat | same router, WebSocket agent chat handler |

Order on **REST and live WebSocket** chat:

1. LLM reply  
2. Optional skill blocks via `run_skills_from_text` (may include `execute_goal`)  
3. **Then** `maybe_auto_chain_from_chat(..., skill_results=skill_results)`  

If `skill_results` already contains a successful `execute_goal`, the helper returns that payload with `from_skill: true` and **does not** create a second parent (prevents double chain). The assistant reply is annotated:

> — Goal chain started via execute_goal: task #… with N delegated steps.

On auto-chain success (not deduped / not from skill):

> — Auto-chain started: goal task #… with N delegated steps (hierarchy). Autonomy will run/monitor them.

On dedupe:

> — Goal chain already running (#…).

Both surfaces return `goal_chain` on the response (`REST` body field / WS `done` payload) so AgentChat can show the goal alert.

Internally, chat auto-chain calls `start_goal_chain(..., priority="high", auto_queue=True)`.

**Note:** Agents are still prompted to prefer `execute_goal` for explicit multi-step goals (`agent_prompts.py` autonomy blurb). Chat auto-chain is the fallback when the model does not emit the skill.

---

## 3. Skill: `execute_goal`

Catalog entry (`SKILL_CATALOG` in `agent_skills.py`):

| Field | Value |
|-------|--------|
| **id** | `execute_goal` |
| **name** | Execute goal (auto chain) |
| **roles** | orchestrator, lead, member |
| **policy** | `core` (`skills_policy.py`) |
| **permission** | `can_delegate` (lead/admin) **or** orchestrator |

Description (product intent): one prompt → parent goal → break into steps → delegate down hierarchy → company/project targets → queue active agents → monitor completion.

Agents invoke via skill fence:

````text
```skill
{"skill":"execute_goal","goal":"Launch spring campaign for Fire Alarms Dublin","max_steps":5}
```
````

or `POST /api/agents/{id}/skills/run` with `{ "skill": "execute_goal", "args": { ... } }`.

Handler: `_skill_execute_goal` → `start_goal_chain(...)`.

### Args

| Arg | Notes |
|-----|--------|
| `goal` / `prompt` / `description` / `title` | Required goal text (`goal` preferred; others accepted) |
| `title` | Optional short parent title |
| `priority` | Default `high` |
| `steps` | Optional list (or newline string) — skips auto-decompose when provided |
| `company_id` / `project_id` | Scope override; else chain owner agent / first company |
| `max_steps` | 2–12, default 6 |

`auto_queue=True` is always passed from the skill handler.

**Gates** (`execute_skill`): skill enabled for agent (orchestrator bypasses enable list), role in catalog (orchestrator bypasses), and delegate permission as above.

System prompt guidance (`agent_prompts.py`): for multi-step human goals always use `execute_goal` or `create_task` with `parent_task_id` so the chain is monitored to completion.

---

## 4. Task (parent)

`start_goal_chain()` creates one **parent** task:

| Field | Value |
|-------|--------|
| Title | `Goal: {first line of prompt}` |
| Description | Full prompt (≤8000) |
| Status | `in_progress` (monitors while children run) |
| Labels | `goal,auto-chain,monitor` |
| `agent_id` | Chain owner — prefers **orchestrator** if caller is a leaf specialist (not orchestrator/lead) |
| Company/project | From args → chain owner agent → first owned company |

Parent stays non-terminal until children finish (see **complete** / rollup).

---

## 5. Delegate (hierarchy)

### Step breakdown — `decompose_goal(prompt, max_steps=6)`

1. Numbered / bulleted lines from the human  
2. Else sentence/chunk split if ≥2 chunks  
3. Else synthesized template (up to `max_steps`):

   1. Clarify goal & success criteria *(orchestrator)*  
   2. Set company/project targets *(lead)*  
   3. Break into owned workstreams *(lead)*  
   4. Execute primary deliverable *(specialist)*  
   5. QA / review & pack result *(orchestrator)*  
   6. Monitor completion & escalate blockers *(orchestrator)*

Deterministic — no extra LLM call for breakdown.

### Assignee — `pick_assignee()`

Order of preference:

1. Explicit `agent_id` on the step  
2. `role_hint` / role / template / name match  
3. Keyword map on step text → template types (sales, marketing, support, coding, finance, research, design, ops)  
4. Direct reports of chain owner (round-robin by step index)  
5. Any lead, then other non-orchestrator agents  
6. Fall back to chain owner  

Each **child** task:

- `parent_task_id` = parent  
- Title `[i/N] {step}`  
- Labels `auto-chain,step,{i}`  
- **Sequential status** (not `initial_task_status`):  
  - first step (`i == 0`) + `auto_queue` + assignee `active` → **`queued`**  
  - all later steps → **`todo`** until unlock  
- Description includes parent goal id and “Assigned via hierarchy auto-chain…”

Side effects on start:

- `live_ops` plan + step events  
- WebSocket `agents:{user_id}` → `goal_chain_started`

---

## 6. Monitor (autonomy tick)

Queued children are executed by the self-running workspace engine (`backend/app/autonomy.py`). Parent labels include `monitor` while children run; progress is also pushed on WebSocket / live ops.

### Per-user cycle — `run_user_cycle`

If `WorkspaceSettings.autonomy_enabled`:

| Phase | Behavior |
|-------|----------|
| Cooldown | If within `autonomy_interval_sec` (min floor `AUTONOMY_MIN_INTERVAL_SEC`), **still drain queue** (`_run_queued_tasks` only); skip stuck scan + never_idle feed |
| Full tick | Ensure orchestrator → stuck/failed/high-priority escalation → never_idle feed → run queued |
| Queue drain | Up to `AUTONOMY_MAX_TASKS_PER_TICK` tasks with `status=queued` → `schedule(run_agent_task(...))` |
| Permissions | Agents that cannot execute may be escalated (`permission`) via `resolve_runtime` |

Default settings (created on first access): `autonomy_enabled=True`, `autonomy_interval_sec=300`, `task_stuck_minutes=30`.

### Global / cron — `run_global_tick`

Eligible users: `subscription_active` **or** `role == admin` **or** non-empty plan not `"none"`. Fallback: sample of users if query empty. Used by production cron.

### Local loop

`autonomy_background_loop()` — long-running loop for non-Vercel local deploys (interval from enabled workspaces).

### Task run — `run_agent_task` (`task_runner.py`)

1. Mark task running, call LLM with agent system prompt + skills  
2. Parse/run skill blocks from output (`run_skills_from_text`)  
3. On success → `status=completed`, then **`on_task_finished(..., final_status="completed", commit=False)`**  
4. On failure → `status=failed`, then **`on_task_finished(..., final_status="failed", commit=False)`**  
5. Single DB commit for billing + terminal status + chain mutations  
6. Broadcast `task_done` / usage events  

`commit=False` keeps a **single-writer** transaction: task_runner owns commit after chain rollup/flush.

### HTTP surfaces

| Method | Path | Auth | Role |
|--------|------|------|------|
| `GET` | `/ops/autonomy` | user | Settings + permission catalog |
| `PUT` | `/ops/autonomy` | user | Enable / interval / stuck minutes |
| `GET`\|`POST` | `/ops/autonomy/tick` | user | One workspace cycle (`run_user_cycle`) |
| `GET`\|`POST` | `/ops/autonomy/tick-all` | **cron secret or admin** | Global tick (`run_global_tick`) |

**Cron (production):** Vercel `vercel.json` → `GET /api/ops/autonomy/tick-all` schedule `0 6 * * *` (daily 06:00 UTC).  
Auth: `X-Cron-Secret: <CRON_SECRET>` or `Authorization: Bearer <CRON_SECRET>` (see `docs/PRODUCTION_APIS.md`).

---

## 7. Complete (`on_task_finished` rollup)

Called for any finished child that has `parent_task_id` (from task_runner with `commit=False`, or other callers with default `commit=True`).

Terminal statuses for “open” check: anything **not** in `completed` / `failed` / `review`.

### Sequential unlock

If child **completed** and siblings remain open:

- Find next sibling with `todo` + active agent → set **`queued`**  
- Stop if something is already `queued` or `in_progress`  
- Skip inactive assignees and keep scanning for a runnable `todo`

### Failure path

If child **failed**:

- Remaining siblings still in **`todo`** are marked **`failed`** with result  
  `Skipped: prior chain step #{id} failed` (so the parent is not stuck with open children forever)  
- In-flight (`queued` / `in_progress`) siblings are left alone  
- Parent labels get `,child-failed`  
- `escalate_task(..., requeue=False, commit=commit)` — log escalation without un-failing the child  
- Live ops + WebSocket `goal_chain_progress`

### Parent rollup (parent labels contain `goal`, `auto-chain`, or `plan`)

When **no open children** remain:

| Children | Parent status | Result note |
|----------|---------------|-------------|
| All completed | `completed` | “All N chain steps completed.” |
| Mix of fail + ok | `review` | Needs human/agent review |
| All failed (no completed) | `failed` | Chain failed summary |

While children still open, parent is kept `in_progress`.

---

## Task statuses

Canonical set (`task_status.py`):  
`todo` · `queued` · `in_progress` · `review` · `completed` · `failed`

Create-time rules (`initial_task_status`) — used by `create_task` skill, `announce_plan`, and general task APIs (**not** by `start_goal_chain` children, which use sequential queueing above):

- Human assignee → `todo`  
- `run_now=false` → `todo`  
- Active agent + run_now → `queued`  
- Else → `todo`

---

## Skills (chain-related and supporting)

Catalog lives in `SKILL_CATALOG` (`agent_skills.py`). Agents invoke via:

````text
```skill
{"skill":"<id>", ...args}
```
````

or `POST /api/agents/{id}/skills/run`.

### Primary auto-chain skills

| Skill id | Role | Permission | What it does |
|----------|------|------------|--------------|
| **`execute_goal`** | orchestrator, lead, member | delegate | Full chain: parent + hierarchy steps + sequential queue |
| **`create_task`** | orchestrator, lead, member | delegate | One task; optional `parent_task_id`, `run_now`; under goal parent adds `auto-chain` label |
| **`announce_plan`** | all roles | execute | Ops banner + plan DAG; string steps stay on announcer; dict steps may use `pick_assignee` |
| **`spawn_agent`** | orchestrator, lead | delegate | Grow hierarchy for later assignment |
| **`message_agent`** | all | delegate | Cross-agent coordination |
| **`assign_human`** | orchestrator, lead, member | delegate | Hand work to human |
| **`escalate_to_human`** | orchestrator, lead, member | (execute path) | Explicit human handoff |

### Useful during step execution

| Group | Skill ids (examples) |
|-------|----------------------|
| Memory / training | `save_memory`, `save_training`, `search_memory`, `search_knowledge` |
| CRM / diary | `list_customers`, `get_customer`, `update_customer`, `log_customer_activity`, `create_deal`, `schedule_meeting`, `list_diary` |
| Meetings | `open_meeting`, `post_to_meeting`, `run_meeting_round`, `close_meeting`, `extract_meeting_tasks` |
| Comms (draft free / send premium) | `draft_email`, `send_email`, `draft_sms`, `send_sms`, `send_whatsapp`, `make_voice_call`, `send_message`, `log_communication` |
| Media (premium) | `generate_image`, `generate_video` |
| Content / research | `generate_content`, `research`, `summarize` |
| Team ops | `list_team`, `spawn_team`, `spawn_specialist`, `clone_agent`, `promote_to_lead`, `configure_agent`, … |
| Domain packs | sales, support, marketing, eng, finance, legal, design, analytics, ops (150+ catalog entries) |

Premium skills bill wallet/credits before run (`premium: true` on catalog entries).

Role + enable list + permission gates are enforced in `execute_skill()`.

---

## API surfaces

Base: **`/api`** (e.g. `https://aibusinessagent.xyz/api`).  
Auth: `Authorization: Bearer <JWT or aba_… API key>` unless noted.

### Chat & skills (start chain)

| Method | Path | Role in chain |
|--------|------|----------------|
| `POST` | `/agents/{agent_id}/chat` | Human prompt; skill parse then chat auto-chain |
| WS | agent live chat | Same auto-chain as REST after stream completes |
| `POST` | `/agents/{agent_id}/skills/run` | Run one skill (e.g. `execute_goal`) |
| `GET` | `/agents/{agent_id}/skills` | Enabled skills + catalog slice |
| `PUT` | `/agents/{agent_id}/skills` | Enable/disable skills |

### Tasks & hierarchy

| Method | Path | Role in chain |
|--------|------|----------------|
| `GET` | `/agents/hierarchy` | Tree used for delegation |
| `POST` | `/agents/ensure-orchestrator` | Top of hierarchy |
| `PUT` | `/agents/{agent_id}/hierarchy` | Parent / role wiring |
| `POST` | `/agents/{agent_id}/delegate` | Lead → report task (`labels=delegated`) |
| `POST` | `/agents/{agent_id}/tasks` | Assign task; `run_now` → queue/run |
| `GET` | `/agents/{agent_id}/tasks` | List agent tasks |
| `GET` | `/agents/tasks/board` | Board view |
| `GET` | `/agents/tasks/{task_id}` | Single task |
| `PATCH` | `/agents/tasks/{task_id}` | Status / fields |
| `POST` | `/agents/tasks/{task_id}/run` | Force run via task_runner |

### Autonomy & live ops

| Method | Path | Auth | Role in chain |
|--------|------|------|----------------|
| `GET` | `/ops/autonomy` | user | Settings + permission catalog |
| `PUT` | `/ops/autonomy` | user | Enable / interval / stuck minutes |
| `GET`\|`POST` | `/ops/autonomy/tick` | user | One workspace cycle (drain queue) |
| `GET`\|`POST` | `/ops/autonomy/tick-all` | **cron secret or admin** | Global tick (Vercel Cron) |
| `GET` | `/ops/live` | user | Live ops feed |
| `GET` | `/ops/visual` | user | Visual snapshot |
| `POST` | `/ops/plan` | user | Manual plan event |
| `POST` | `/ops/scaffold` | user | One-shot team repair (not every tick) |
| `GET` | `/ops/escalations` | user | Escalation log |
| `GET` | `/ops/permissions` | user | Permission / escalate-when options |

### WebSocket / events

Channel `agents:{user_id}` (see `backend/app/ws.py`):

| Event | When |
|-------|------|
| `goal_chain_started` | Parent + children created |
| `goal_chain_progress` | Child finished; next queued / parent rolled up / skips |
| `task_done` | Task runner finished |
| `task_updated` | e.g. skill `create_task` |

Also `tokens:{user_id}` for usage metering.

### Related CLI / bootstrap

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/cli/bootstrap` | Orchestrator + companies + starter tasks |
| `GET` | `/cli/status` | Workspace snapshot |
| `GET` | `/cli/guidance` | Operator guidance |

---

## Labels cheat sheet

| Labels | Meaning |
|--------|---------|
| `goal,auto-chain,monitor` | Parent goal from auto-chain (monitor stage) |
| `auto-chain,step,{n}` | Delegated step child |
| `plan` / `plan-step` | From `announce_plan` (same rollup rules on parent labels) |
| `skill-created` | From `create_task` skill |
| `skill-created,auto-chain` | `create_task` under a goal parent |
| `delegated` | From HTTP delegate |
| `autonomy,self-run` | never_idle proactive feed |
| `escalated` / `child-failed` | Escalation markers |

---

## Source map

| File | Responsibility |
|------|----------------|
| `backend/app/task_chain.py` | Goal detect, decompose, start chain, sequential unlock, rollup |
| `backend/app/agent_skills.py` | Skill catalog + `execute_goal` / create / plan |
| `backend/app/routers/agents.py` | REST + live chat auto-chain hook, tasks, delegate, skills HTTP |
| `backend/app/routers/ops.py` | Autonomy settings, tick, tick-all, live ops |
| `backend/app/autonomy.py` | Tick cycle, queue drain, escalate, never_idle |
| `backend/app/task_runner.py` | LLM task execution + `on_task_finished` hooks (`commit=False`) |
| `backend/app/task_status.py` | Status allow-list + `initial_task_status` |
| `backend/app/agent_hierarchy.py` / `agent_roles.py` | Orchestrator, leads, hierarchy tree |
| `backend/app/agent_prompts.py` | Autonomy + `execute_goal` skill guidance |
| `backend/app/agent_scaffold.py` | `resolve_runtime` for execute permission on ticks |
| `backend/app/live_ops.py` | Ops banner events |
| `backend/app/ws.py` | Real-time broadcasts |
| `backend/app/skills_policy.py` | `execute_goal` as core skill |
| root `vercel.json` | Cron path `/api/ops/autonomy/tick-all` |

---

## Operator checklist

1. Ensure **Main AI Orchestrator** exists (`POST /agents/ensure-orchestrator` or CLI bootstrap).  
2. Hierarchy: leads + specialists with `parent_id` / roles set.  
3. Agents **active**, permissions that allow execute/delegate, relevant skills enabled.  
4. Autonomy on: `PUT /ops/autonomy` `{ "autonomy_enabled": true }`.  
5. Send a goal prompt to orchestrator/lead **or** run skill `execute_goal`.  
6. Confirm parent + children on Tasks board; first step `queued`, rest `todo`.  
7. Tick: UI Ops “Run tick”, `POST /ops/autonomy/tick`, or wait for cron `tick-all`.  
8. Watch live ops + WebSocket progress until parent `completed` / `review` / `failed`.

---

## Design notes

- **Pipeline integrity:** UI, skills, and deploy work must not break  
  `prompt → task → delegate → monitor → complete` (hierarchy chain + sequential unlock + rollup).  
- **Deterministic decompose** — no extra LLM call for step breakdown (numbered lines preferred).  
- **Sequential children** — only step 1 is queued at start; later steps stay `todo` until the previous completes (queuing every child broke unlock / ran parallel).  
- **Failed step stops the chain** — remaining `todo` siblings are skipped/failed so the parent can roll up.  
- **Chat + skill can both fire** — chat auto-chain runs after skill parse; similar open chains dedupe on chat.  
- **Cooldown still drains queue** — production cron and manual ticks keep chains moving even when idle feeds are skipped.  
- **`announce_plan` vs `execute_goal`** — plan is ops-oriented DAG (string steps on announcer; dicts can hierarchy-route); execute_goal always creates a monitoring parent and **delegates across hierarchy** with sequential unlock.  
- **Single-writer on finish** — task_runner passes `commit=False` into `on_task_finished` / escalate so billing + status + rollup share one commit.  
- Scaffold/repair (`POST /ops/scaffold`) is **not** part of every tick — only explicit repair of team config.

---

## Swarm monitor (operator) vs product `monitor` label

Two different “monitor” concepts appear in this repo. Keep them separate:

| Concept | What it is | Cadence | Source of truth |
|---------|------------|---------|-----------------|
| **Product parent `monitor`** | Parent task labels `goal,auto-chain,monitor` while children run; rollup via `on_task_finished` | Task/autonomy lifecycle | This doc + `task_chain.py` |
| **Swarm monitor scheduler** | External durable job that keeps **20** coding subagents busy on the monorepo | **Every 2 minutes** (`2m`), `fire_immediately` on create | `scripts/swarm_backlog.json`, `scripts/swarm_monitor_status.md`, `scripts/swarm_monitor.log` |

### Swarm scheduler facts

- **Scheduler id:** `019f7a30d212`  
- **Interval:** `2m` · **durable** · **fire_immediately**  
- **Target concurrency:** `20` (`swarm_backlog.json` → `target`)  
- **Refill rule:** when any subagent finishes, spawn replacements from `task_pool` until 20 are running  
- **Hard product rule in backlog:** auto-chain **`prompt → task → delegate → monitor → complete` must stay intact** — UI, skills, and deploy work must not break hierarchy chain or rollup  

### Backlog (`scripts/swarm_backlog.json`)

Operator task pool for continuous work: deploy/health, Card/PageShell UI polish, TasksBoard goal-chain tags, `task_chain` / `execute_goal` verify, trial plan caps, browser e2e A/B, smoke, schema migrate checks, and **keep this `AUTO_CHAIN.md` accurate**.

Full operator write-up: **`scripts/swarm_monitor_status.md`**.

### Related status files

| Path | Role |
|------|------|
| `scripts/swarm_monitor_status.md` | 2m monitor + backlog description |
| `scripts/swarm_backlog.json` | Target 20, rules, task_pool |
| `scripts/swarm_monitor.log` | Create / refill events |
| `scripts/SWARM_STATUS.md` / `SWARM_20_STATUS.md` | Swarm inventory + live probe notes |
