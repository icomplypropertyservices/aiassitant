# Swarm monitor status

**Project:** `C:\Users\E-Store\ai-business-assistant\ai-business-assistant`  
**Production:** `https://www.aibusinessagent.xyz`  
**Updated:** 2026-07-19

Operator doc for the **2-minute durable swarm monitor** and its **task backlog**.  
Not part of the product runtime; pairs with product auto-chain docs in [`docs/AUTO_CHAIN.md`](../docs/AUTO_CHAIN.md).

---

## 1. What the monitor is

A **session scheduler** keeps a continuous coding swarm full:

| Field | Value |
|-------|--------|
| Interval | **every 2 minutes** (`2m`) |
| Scheduler id | `019f7a30d212` |
| Mode | **durable** (survives session restarts where supported) |
| First fire | **`fire_immediately`** (runs once on create, then every 2m) |
| Creation log | `scripts/swarm_monitor.log` |

### Purpose each tick

1. Count how many general-purpose background subagents are still working on this project.  
2. If fewer than **20**, spawn replacements from the backlog until the target is restored.  
3. Prefer **concrete** code / UI / API / deploy / test work — not idle planning-only agents.  
4. Protect product integrity: **auto-chain**  
   `prompt → task → delegate → monitor → complete` must stay intact (see `docs/AUTO_CHAIN.md`).

### Log file

`scripts/swarm_monitor.log` — append-only events, e.g.:

```text
2026-07-19T swarm monitor created: scheduler 019f7a30d212 every 2m durable + fire_immediately
2026-07-19T manual wave M01-M20 spawned by parent
2026-07-19T13:44:56+02:00 refill: S01 done -> R01 Workspace page cards
```

| Event style | Meaning |
|-------------|---------|
| `swarm monitor created` | Scheduler registered (id, interval, durable, fire_immediately) |
| `manual wave M01–M20` | Parent seeded an initial batch of 20 agents |
| `refill: … done -> …` | A finished agent was replaced from the backlog |

---

## 2. Backlog source of truth

**File:** [`scripts/swarm_backlog.json`](swarm_backlog.json)

| Key | Role |
|-----|------|
| `target` | Concurrent subagent count (**20**) |
| `project` | Absolute workspace path |
| `base_url` | Production host for live smoke / e2e |
| `rules` | Hard rules for every monitor tick and every subagent |
| `task_pool` | Ordered pool of concrete work items to assign on refill |

### Rules (from backlog)

1. Always keep **exactly 20** general-purpose background subagents busy on this project.  
2. When any finish, **immediately** spawn replacements until 20 are running.  
3. Prefer concrete code/UI/API/deploy/test tasks — no idle planning-only agents.  
4. **UI rule:** Ant Design Cards/containers, centered max-width page shells.  
5. **Product rule:** auto-chain `prompt→task→delegate→monitor→complete` stays intact.

### Task pool themes

| Theme | Examples in `task_pool` |
|-------|-------------------------|
| Deploy / ops | `vercel --prod`, health verify, autonomy tick-all secret |
| UI shell | PageShell / AppLayout, `global.css`, centered cards on main pages |
| Auto-chain product | `task_chain.py`, `execute_goal`, chat auto-chain, rollup, TasksBoard tags |
| Plans / trial | trial agent/company caps, billing cards |
| Live proof | demo login, browser e2e A/B, create_test_account, smoke |
| Docs / schema | keep `docs/AUTO_CHAIN.md` accurate; `parent_task_id` migrate |
| Runtime polish | build fix, TypeError cleanup, TokenMeter / TopUpModal |

Monitor refills should **pick unfinished pool items** (or close siblings of finished ones) rather than inventing open-ended research tasks.

---

## 3. How monitor relates to product auto-chain

| Layer | Mechanism | Interval / trigger |
|-------|-----------|--------------------|
| **Swarm monitor (this doc)** | External 2m scheduler + `swarm_backlog.json` | Every **2m**, durable |
| **Product auto-chain** | `task_chain.py` parent `goal,auto-chain,monitor` + child steps | Human chat / `execute_goal` |
| **Product autonomy** | `autonomy.py` queue drain + cron `tick-all` | User interval / Vercel cron |

Do not confuse:

- Parent task label **`monitor`** on a goal chain = product parent watching children.  
- **Swarm monitor** = operator loop that keeps coding agents busy on the repo.

Both must respect the same product rule: hierarchy delegate + rollup behavior documented in `docs/AUTO_CHAIN.md` must not be broken by UI or skill edits.

---

## 4. Related status artifacts

| Path | Role |
|------|------|
| `scripts/swarm_backlog.json` | Target, rules, task pool |
| `scripts/swarm_monitor.log` | Scheduler create + refill events |
| `scripts/SWARM_STATUS.md` | task_chain wiring, demo login, browser blockers |
| `scripts/SWARM_20_STATUS.md` | UI container WIP + live A/B + chain probe notes |
| `scripts/ECOSYSTEM_STATUS.md` | Deploy / health / inventory |
| `docs/AUTO_CHAIN.md` | Product auto-chain E2E |
| `docs/LAUNCH_100.md` | Historical continuous-swarm scorecard |

### Live proof (typical re-check)

```powershell
cd C:\Users\E-Store\ai-business-assistant\ai-business-assistant
python scripts/create_test_account.py
node scripts/live_browser_e2e.mjs --agent=A
node scripts/live_browser_e2e.mjs --agent=B
```

---

## 5. Operator checklist (monitor healthy)

1. Scheduler id still active: **`019f7a30d212`**, interval **2m**, durable.  
2. `swarm_backlog.json` `target` remains **20**; rules include auto-chain product guard.  
3. On each 2m tick (or after agents finish): running count → if &lt; 20, refill from `task_pool`.  
4. Append notable create/refill lines to `swarm_monitor.log`.  
5. After product changes that touch chain/UI: update `docs/AUTO_CHAIN.md` and re-run browser A/B when possible.  
6. Do not mark production ops “done” from local-only work — prove on `base_url` when the pool item is deploy/smoke.

---

## 6. One-line status

**Swarm monitor scheduler `019f7a30d212` runs every 2 minutes (durable + fire_immediately), refills to 20 agents from `scripts/swarm_backlog.json`, and must keep product auto-chain intact while burning down the UI/deploy/test pool.**

*Secrets omitted. Log timestamps may be partial.*
