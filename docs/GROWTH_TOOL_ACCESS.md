# Growth: maximize agent tool usage

Operator checklist to get market-leading tool coverage on a workspace. Architecture: [AGENT_TOOLS_AND_FLOWS.md](AGENT_TOOLS_AND_FLOWS.md) · ship notes / go-live: [SQUAD_SHIP_NOTES.md](SQUAD_SHIP_NOTES.md) · packs: [SKILL_PACKS_OVERVIEW.md](SKILL_PACKS_OVERVIEW.md) · chains: [AUTO_CHAIN.md](AUTO_CHAIN.md).

**Caps source:** `backend/app/plans.py` — **trial = 12 agents**, 120 skills/agent, 6 packs, 50k tokens, 14-day one-shot, `premium_skills=false` by default (media still bill-per-use).

**Not product:** there is no in-app Grok Build manager that spawns coding subagents. Grow the team with product hierarchy (`spawn_agent`, ensure-orchestrator, seed team) and the 24 workflow presets.

---

## 1. Plan & credits

- [ ] Activate trial or paid plan (`POST /billing/plan` or Subscribe UI) — org/agents return **402** without a plan.
- [ ] Confirm trial caps if on free tier: **12 agents**, 2 companies, 3 projects (`GET /billing/…` / public plans or `scripts/assert_trial_plan.py`).
- [ ] Keep token pool / wallet funded; premium skills (`send_*`, five media skills, voice) fail closed without credits.
- [ ] Set platform LLM: `XAI_API_KEY` and/or `ANTHROPIC_API_KEY` (or user keys in Settings → API keys).

## 2. Team shape (use the agent cap)

- [ ] Ensure main **orchestrator** (`POST /agents/ensure-orchestrator`) — full skill pack.
- [ ] Spawn **leads** + specialists with correct `template_type` (`sales`, `marketing`, `support`, `coding`, `research`) so domain packs auto-enable.
- [ ] Fill toward plan agent limit (trial **12**); leave orchestrator + at least one sales/outreach lead if running CRM workflows.
- [ ] Agents **active** with execute permission (`operator`+); set `never_idle` only if you want autonomy to feed work.

## 3. Enable skill packs

- [ ] `GET /agents/{id}/tool-access` — inspect `enabled_skills`, categories, `plan_caps`, suggested vs all workflows.
- [ ] `GET /agents/{id}/skills` — check `enabled_count` vs plan `skills_per_agent`.
- [ ] UI **Enable recommended pack** (Agent manage → Skills) or `PUT /agents/{id}/skills` with domain + core ids; chat meta: `bulk_enable_skills` / `enable_skills_on` as lead/orchestrator.
- [ ] Prefer template spawn packs over hand-picking mega `sales_*` / `mkt_*` ids first; add mega skills when needed.
- [ ] Upgrade plan when capped (trial 120 → starter 200 → pro 500 + `premium_skills`).

## 4. Integrations (live actions)

- [ ] Settings → Connected apps: Gmail/Google, Slack, Shopify, etc. (`/integrations/{app_id}/connect`).
- [ ] **Allocate** each connection to the agents that should use it (`PUT …/connections/{id}/agents`).
- [ ] Wire Resend/SMTP + Twilio for real email/SMS; until then agents should draft, not pretend-send.
- [ ] Confirm prompt shows apps via agent skills list / chat context (“Apps: …”).

## 5. Autonomy & chains

- [ ] `PUT /ops/autonomy` `{ "autonomy_enabled": true }` (interval e.g. 300s).
- [ ] Use `execute_goal` / the **24** workflow presets for multi-step CRM/outreach so children queue and run on tick.
- [ ] Production: set **`CRON_SECRET`**; Vercel cron hits `/api/ops/autonomy/tick-all` daily (`0 6 * * *`). Manual: `POST /ops/autonomy/tick`.
- [ ] Confirm fail-smart: provider/billing terminal fails stay **failed** (labels `llm_unavailable` / `credits_exhausted` / …) — not infinite requeue.
- [ ] Watch Live ops / task board for stuck → escalated work.

## 6. CRM, meetings, media

- [ ] Seed or import customers/deals so sales skills have data; run preset **Sales targets → CRM → outreach** (`sales_targets_crm_outreach`).
- [ ] Open meeting rooms for multi-agent decisions; `extract_meeting_tasks` → queued work.
- [ ] Enable the five media skills only with credits + xAI (or accept placeholder):  
  `generate_image` (0.06), `edit_image` (0.08), `generate_ad_creative` (0.08), `generate_product_shot` (0.07), `generate_video` (0.25).

## 7. Smoke (5–10 minutes)

1. `GET /agents/{id}/tool-access` — skills + **24** `all_workflows` + plan caps.  
2. Chat orchestrator: create a task / goal with DONE WHEN → appears queued/running.  
3. Lead: `list_customers` or create one → CRM row.  
4. Workflow: `POST /agents/workflows/run` with a sales or support preset (or dashboard Run).  
5. Connected app: `use_app` or `gmail_*` / draft path succeeds or clear connect error.  
6. Autonomy tick drains queue; terminal LLM/credit fails not requeued.  
7. Premium path (if funded): one send or image bills credits, does not free-run.  
8. Header meter stays sparse (~45s poll when WS quiet) — no storm.

## 8. Go-live gate (copy/paste)

| Gate | Check |
|------|--------|
| Plan | Active trial (12 agents) or paid; not `none` |
| LLM | Platform or user key works (non-mock path for real work) |
| Team | Orchestrator + ≥1 domain lead; agents active |
| Tools | tool-access shows core CRM + workflows; recommended pack on |
| Apps | Required integrations connected **and** allocated |
| Autonomy | Enabled + cron secret in prod |
| Smoke | Goal/workflow + CRM + tick green |

Full deploy env list: [SQUAD_SHIP_NOTES.md](SQUAD_SHIP_NOTES.md#operator-go-live-checklist).

**Done when** agents act via skills (not only chat prose), apps are allocated, CRM/media/workflows are reachable, and autonomy keeps chains moving fail-smart.
