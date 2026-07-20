# Squad ship notes — market-leading tool access

Operator-facing summary of shippable product work. Architecture & how-to: **[AGENT_TOOLS_AND_FLOWS.md](AGENT_TOOLS_AND_FLOWS.md)** · growth checklist: [GROWTH_TOOL_ACCESS.md](GROWTH_TOOL_ACCESS.md) · packs: [SKILL_PACKS_OVERVIEW.md](SKILL_PACKS_OVERVIEW.md) · chains: [AUTO_CHAIN.md](AUTO_CHAIN.md).

**Not product UI:** multi-agent growth is `spawn_agent` / hierarchy / `ensure-orchestrator` / workflow presets — there is **no** in-app “Grok Build manager” that spawns coding subagents.

---

## Trial: 12 agents

Source of truth: `backend/app/plans.py` (`TRIAL_AGENTS = 12`).

| Cap | Trial value |
|-----|------------:|
| Agents | **12** |
| Tokens (pool) | 50,000 |
| Companies | 2 |
| Projects | 3 |
| Skills enabled / agent | 120 |
| Domain skill packs | 6 of 20 |
| Premium skills flag | false (bill-per-use media still chargeable) |
| Trial length | 14 days one-shot (`subscription_expires_at`) |

Assert locally: `python scripts/assert_trial_plan.py` (optional `--prod`).

---

## Full tool defaults + tool-access API

- Spawn/repair (`ensure_agent_skills`) applies **role + `template_type` pack** via `skills_for_template` — not a bare empty set.
- **`_CORE_ALWAYS`** always re-attached (tasks, CRM CRUD, meetings, drafts, workflows, patterns, …).
- **`LEAD_FLOW_SKILLS` expanded** (always re-attached for leads — cannot strip via UI saves):  
  `run_workflow` + `create_workflow` / `execute_goal` / patterns / review · task ops (`list_tasks`, `complete_task`, `claim_task`, …) · full CRM funnel (customers, leads qualify/score, deals win/lose, pipelines) · meetings · **all 5 media** · `use_app` · `send_email` / `draft_email` · spawn/team. Source: `agent_skills.LEAD_FLOW_SKILLS`.
- **`GET /agents/{id}/tool-access`** — single payload (`agents_tasks.py`):

  | Field | Meaning |
  |-------|---------|
  | `enabled_skills` / `enabled_skills_count` | Live enable set |
  | `enabled_by_category` | Counts by category |
  | `core_skills_count` | Intersection with `_CORE_ALWAYS` |
  | `workflows` | Suggested presets for template/role |
  | `all_workflows` | Full `WORKFLOW_PRESETS` catalog |
  | `can_create_flows` / `lead_flow_skills` | Lead/orchestrator multi-agent toolkit (includes expanded LEAD_FLOW) |
  | `plan_caps` | `plan_skill_caps(user.plan)` |

- **`GET /agents/{id}/dashboard`** embeds the same tool-access surface for Agent Home.

---

## CRM lead skills

- Core free CRM always on via `_CORE_ALWAYS`: customers, deals, pipelines, diary, products, activity, lead qualify/score (`skills/crm.py` + `crm_service`).
- Sales templates layer pipeline keywords; sales workflows hand off CRM → outreach.
- Leads keep expanded **`LEAD_FLOW_SKILLS`** (pipeline + media + `run_workflow`).
- UI: **Agent manage → Skills → “Enable recommended pack”** turns on CRM + workflow core in one click (`AgentSkillsPanel` / `RECOMMENDED_CRM_WORKFLOW_SKILLS`).

---

## Media skills (5) + stop-thrash

Premium, bill-per-use (`skills/content.py` → `routers/media.py` / xAI Imagine). Catalog costs in `agent_skills.py`:

| Skill | `cost_credits` |
|-------|---------------:|
| `generate_image` | 0.06 |
| `edit_image` | 0.08 |
| `generate_ad_creative` | 0.08 |
| `generate_product_shot` | 0.07 |
| `generate_video` | 0.25 |

**Stop-thrash fields** (`_media_error_fields` on every media skill result):

| Field | Meaning |
|-------|---------|
| `ok` | false on terminal provider/billing failure |
| `retryable` | **false** for `xai_credits` / `xai_permission` — agent must not re-call |
| `error_code` | e.g. `xai_credits`, `xai_permission`, `validation`, `media_internal` |
| `agent_guidance` / `message` | “STOP… Do not re-call media skills until billing/key is fixed.” |

Video may return **`pending` + `request_id` + poster** — do **not** re-submit the same brief while pending. Marketing/lead packs can enable `_MEDIA_FOR_DOMAIN` even when plan `premium_skills` is false (still charges). Needs credits + `XAI_API_KEY` (or user key) for live output.

---

## 24 workflows + `run_workflow` skill

Exactly **`len(WORKFLOW_PRESETS) == 24`** in `workflows.py` — sales, support, marketing, coding, ops, product.

| Entry | Role |
|-------|------|
| Skill **`run_workflow`** | Agent launches named preset (`workflow_id` or `list=true`); handler `_skill_run_workflow` → `start_workflow` (`skills/meta_agents.py`). In **LEAD_FLOW**. Prefer this over free-text `execute_goal` for recipes. |
| `GET /agents/workflows` | Full preset catalog |
| `POST /agents/workflows/run` | HTTP same engine |
| Dashboard / tool-access | `workflows` suggested · `all_workflows` full list |

Leads/orchestrators see the full catalog; members get template-filtered suggestions.

---

## Autonomy fail-smart

- Tick still drains queue; stuck recovery requeues normal stalls.
- **Never requeues** terminal provider failures: spending limit, permission denied, credits exhausted, LLM unavailable (`autonomy._is_terminal_provider_task` + labels/result phrases).
- Labels: `llm_unavailable`, `credits_exhausted`, `llm_permission_denied`, `spending_limit`.
- Cron: `GET /api/ops/autonomy/tick-all` (`vercel.json` `0 6 * * *`) + **`CRON_SECRET`**. User tick: `POST /ops/autonomy/tick`.

---

## Frontend poll (sparse) + pack / billing CTAs

- Shell meter poll **sparse** in `useShellSession.js`:
  - interval **`METER_POLL_MS = 45000`** (was ~25s tight loops)
  - debounce **`METER_DEBOUNCE_MS = 3000`**
  - min gap **`METER_MIN_GAP_MS = 12000`**
- Live ops / WS-first where possible; REST fallback when quiet.
- **AgentSkillsPanel**: “Enable recommended pack” CTA for CRM + workflow core.
- **Billing CTAs** from `GET /billing/meter` (`usage_billing.meter_snapshot`):
  - `upgrade_cta_path` · `primary_cta` / `secondary_cta` (`label`, `path`, `action`)
  - `cta_buy_credits_path` → `/billing` · `cta_subscribe_path` → `/subscribe`
  - No plan / trial ended → **Subscribe**; hard block / low fuel → **Buy credits** primary + upgrade secondary
  - Header + `TokenMeter` navigate via these paths (not hard-coded guesses only)

---

## Billing lifecycle

- Free trial **one-shot 14 days**; re-POST → `already_active` (no pool refill) or **402** after end (`TRIAL_ENDED_MSG`).
- Paid plans clear trial expiry; org/agents **402** without active plan.
- Premium skills fail closed if credits/billing fail.
- Meter CTAs (above) keep humans on the right path when pool/wallet is empty.

---

## Operator go-live checklist

Use this before calling a workspace “live” for real customers.

### A. Platform (once per deploy)

- [ ] `APP_ENV=production`, strong `JWT_SECRET` (≥32), `ENCRYPTION_KEY`, Postgres `DATABASE_URL`
- [ ] `FRONTEND_URL` + `CORS_ORIGINS` match the public origin
- [ ] Platform LLM: `XAI_API_KEY` and/or `ANTHROPIC_API_KEY` (mock only for demos)
- [ ] Strong **`CRON_SECRET`**; cron hits `GET /api/ops/autonomy/tick-all` with `X-Cron-Secret` (or Bearer)
- [ ] Optional live send: Resend/SMTP + Twilio; Stripe if charging

### B. Workspace (per customer / trial)

- [ ] Plan active — trial (12 agents) or paid (`POST /billing/plan` / Subscribe UI)
- [ ] Token pool / wallet funded enough for expected premium media/sends
- [ ] Orchestrator present: `POST /agents/ensure-orchestrator`
- [ ] Domain leads + specialists with correct `template_type` (sales / marketing / support / coding / research)
- [ ] Agents **active** with execute permission (`operator`+); fill toward plan agent cap as needed
- [ ] Skills: pack defaults via spawn **or** “Enable recommended pack” / `PUT /agents/{id}/skills`
- [ ] Integrations connected + **allocated** to agents (`PUT …/connections/{id}/agents`)
- [ ] Autonomy on: `PUT /ops/autonomy` `{ "autonomy_enabled": true }` (interval e.g. 300s)

### C. Smoke (≤10 minutes)

1. `GET /agents/{id}/tool-access` → non-empty `enabled_skills`, `workflows` / `all_workflows` (24 presets), `plan_caps`; lead shows `run_workflow` in `lead_flow_skills` / enabled set
2. Launch a preset: skill **`run_workflow`** (`workflow_id` or `list=true`) **or** `POST /agents/workflows/run` / `execute_goal` → parent + children on task board
3. CRM: `list_customers` or create customer/deal → row in CRM
4. Autonomy: `POST /ops/autonomy/tick` drains queue; terminal provider fails stay **failed** (not requeued)
5. Optional media: one of the 5 skills bills credits; on xAI 402/403 result has `retryable: false` + `agent_guidance` (no thrash)
6. `GET /billing/meter` → `upgrade_cta_path` / `primary_cta` sensible for plan state; header CTA opens `/subscribe` or `/billing`
7. Header meter: no poll storm (sparse ~45s when WS quiet)

### Done when

Agents act through **skills + `run_workflow` / workflows** (not chat prose alone), CRM/media/integrations are wired, media failures stop-thrash, billing CTAs route correctly, autonomy keeps chains moving fail-smart, and trial/paid caps match `plans.py`.
