# Agent tools & flows

How product agents reach skills, workflows, CRM, media, meetings, and integrations — and how to unlock full tool access.

**Code:** `backend/app/agent_skills.py`, `skills_policy.py`, `agent_scaffold.py`, `skills/*`, `workflows.py`, `autonomy.py`, routers under `backend/app/routers/`.

**Related:** [GROWTH_TOOL_ACCESS.md](GROWTH_TOOL_ACCESS.md) · [SKILL_PACKS_OVERVIEW.md](SKILL_PACKS_OVERVIEW.md) · [AUTO_CHAIN.md](AUTO_CHAIN.md) · [SQUAD_SHIP_NOTES.md](SQUAD_SHIP_NOTES.md).

**Product multi-agent growth** uses hierarchy skills (`spawn_agent`, `hire_agent`, `spawn_team`, …), `POST /agents/ensure-orchestrator`, and workflow presets. There is **no** in-app Grok Build “manager spawn” UI — that is external operator tooling, not the SaaS product surface.

---

## Access model (one path)

```
Chat / task / skill API
  → model emits ```skill { "skill":"…", "args":{…} } ```
  → extract_skill_calls → execute_skill (agent_skills.py)
  → handler in skills/*.py (or use_app → integration_actions)
```

| Surface | Entry | Notes |
|--------|--------|--------|
| Chat | skill fences in reply | Prompt lists enabled skills + linked apps |
| Manual | `POST /agents/{id}/skills/run` | Same `execute_skill` |
| Tasks | `task_runner` + autonomy tick | Queued tasks run when agent `can_execute` |
| Named workflows | Skill **`run_workflow`** or `POST /agents/workflows/run` | Preset → `start_workflow` → task chain |
| Ad-hoc multi-step | `execute_goal` / `create_workflow` | → `task_chain.start_goal_chain` (prefer `run_workflow` for named recipes) |

**Gates on every skill:** enabled on agent (`AgentSkillState` + `_CORE_ALWAYS` merge) · hierarchy role (`role_matches_skill`) · plan cap (`plans.max_enabled_skills` / `skills_per_agent`) · permission (`can_execute` / lead flow exceptions) · integration connected if skill maps to an app (`skills_policy.required_app_for_skill`) · premium billing (`cost_credits` / `charge_premium`).

Core free skills (tasks, CRM CRUD, meetings, drafts, research, …) are always re-attached — see `_CORE_ALWAYS` in `skills_policy.py`.

**`LEAD_FLOW_SKILLS` (expanded, always on for leads):** workflows (`run_workflow`, `create_workflow`, `execute_goal`, patterns, review) · tasks (`list_tasks`, `complete_task`, `claim_task`, …) · full CRM funnel (customers, qualify/score leads, deals win/lose, pipelines) · meetings · **all 5 media** · `use_app` · `send_email` / `draft_email` · spawn/team. Cannot be stripped by normal UI enable-list saves.

---

## Tool-access API

Single payload for Agent Home / LLM tool surface (`routers/agents_tasks.py`):

| Method | Path | Role |
|--------|------|------|
| `GET` | `/agents/{id}/tool-access` | Lightweight: skills + workflows + plan caps |
| `GET` | `/agents/{id}/dashboard` | Same tool surface + tasks/activity |

`tool-access` returns:

- `enabled_skills`, `enabled_skills_count`, `enabled_by_category`, `core_skills_count`
- `workflows` (suggested for `template_type` / role), `all_workflows` (full catalog)
- `can_create_flows`, `lead_flow_skills` (when lead/orchestrator)
- `skill_pack`, `plan_caps`, identity fields

Skills CRUD remains `GET|PUT /agents/{id}/skills`. Meta skills `enable_skills_on`, `bulk_enable_skills` for orchestrator/lead.

---

## Skills catalog & packs

- **Catalog:** `SKILL_CATALOG` in `agent_skills.py` + mega packs from `skill_packs/*.json` + workspace `CreatedSkill` (`custom_*`). Pack files + `skills_for_template`: [SKILL_PACKS_OVERVIEW.md](SKILL_PACKS_OVERVIEW.md).
- **Handlers:** `skills/crm.py`, `comms.py`, `content.py`, `meetings.py`, `integrations.py`, `meta_agents.py`, `workspace.py`, `db_fields/*`, …
- **Defaults:** `ensure_agent_skills` on spawn/repair → role pack + `template_type` domain pack (`sales` / `marketing` / `support` / `coding` / `research` / `full`).
- **UI:** Agent manage → Skills → **Enable recommended pack** (`AgentSkillsPanel`) turns on CRM + workflow core without premium sends.
- **Categories:** core, crm, comms, media, automation, meta, … (`skills_policy.CATEGORY_*`).

Trial caps (source `plans.py`): **12 agents**, 120 skills/agent, 6 of 20 packs, 50k tokens, 14-day one-shot trial.

---

## Workflows (24) + skill `run_workflow`

Exactly **24** named presets in `workflows.py` (`WORKFLOW_PRESETS`) — sales, support, marketing, coding, ops, product. Each has `agent_types` + `category` for dashboard filtering.

| Entry | Role |
|-------|------|
| Skill **`run_workflow`** | Catalog core skill; handler `_skill_run_workflow` (`skills/meta_agents.py`) → `start_workflow`. Args: `workflow_id` (or `list=true` to discover), optional `count` / `niche` / `extra` / `params` / company·project / `priority`. In **`LEAD_FLOW_SKILLS`**. Prefer for named recipes; use `execute_goal` only for ad-hoc free-text. |
| `GET /agents/workflows` | Full preset catalog (`list_workflow_presets`) |
| `POST /agents/workflows/run` | HTTP start preset → same `start_workflow` → `task_chain` |
| tool-access / dashboard | `workflows` = `workflows_for_template(...)`; `all_workflows` = full list |

UI (`AgentHome`): template-filtered presets by default; toggle can show all. Leads/orchestrators get the full catalog. `run_workflow` / `create_workflow` / `execute_goal` / chat auto-chain share the same engine; autonomy drains child tasks. Detail: [AUTO_CHAIN.md](AUTO_CHAIN.md).

**Preset ids (24):**  
`sales_targets_crm_outreach`, `crm_outreach_only`, `sales_pipeline_review`, `sales_proposal_pack`, `sales_meeting_followup`, `support_ticket_triage`, `support_vip_recovery`, `support_kb_macros`, `support_churn_save`, `marketing_campaign_launch`, `marketing_content_sprint`, `marketing_seo_pack`, `marketing_social_week`, `coding_feature_ship`, `coding_bug_triage`, `coding_api_scaffold`, `coding_tech_debt`, `ops_sop_standardize`, `ops_weekly_review`, `ops_onboarding_runbook`, `ops_incident_response`, `product_catalog_build`, `product_offer_campaign`, `product_catalog_audit`.

---

## CRM lead skills

| Layer | Path |
|-------|------|
| Skills | `list_customers`, `create_customer`, `create_deal`, `move_deal`, `win_deal` / `lose_deal`, `log_customer_activity`, `qualify_lead` / `score_lead` / lead lists + status, products, pipelines, diary, … |
| Lead always-on | Expanded **`LEAD_FLOW_SKILLS`** includes full CRM funnel + `run_workflow` + all media (see above) |
| Service | `crm_service.py` |
| HTTP | `/business/customers`, `/deals`, `/pipelines`, `/diary`, products under `/business` |

Agents act through skills; UI/API uses the same models. CRM ids in `_CORE_ALWAYS` cannot be stripped by normal enable-list saves. Sales templates + lead packs layer outreach and multi-agent review on top.

---

## Media (Imagine skills) + stop-thrash fields

Handlers in `skills/content.py` → `routers/media.py` (xAI Grok Imagine). Generate skills bill via `charge_premium` even on placeholder/fallback; **`check_video` is free** (status poll). Media ids are in **`LEAD_FLOW_SKILLS`** / `_MEDIA_FOR_DOMAIN`.

| Skill | `cost_credits` | Notes |
|-------|---------------:|-------|
| `generate_image` | 0.06 | Prompt → image; `style=quality` higher Imagine model |
| `edit_image` | 0.08 | Needs `image_url` + edit prompt |
| `generate_ad_creative` | 0.08 | Product/headline/audience/channel → ad visual (quality defaults) |
| `generate_product_shot` | 0.07 | Studio/catalog product photography (PDP quality defaults) |
| `generate_video` | 0.25 | Async; may return **`status: pending`**, **`request_id`**, poster URL |
| `check_video` | 0 | Poll **`request_id`** until ready/failed — **no generate charge** |

**Pending video flow:** `generate_video` → if `status=pending`, call **`check_video`** with `request_id` (skill) or **`GET /media/video/{request_id}`**. Result includes `next_skill: check_video`. Never re-submit `generate_video` for the same brief while pending.

**Category:** all tagged **`media`** → tool-access UI “Media (premium)”.

**Stop-thrash result fields** (`_media_error_fields`):

| Field | When / meaning |
|-------|----------------|
| `ok` | **false** on terminal xAI credits/permission (no fake asset URL) |
| `retryable` | **false** for `error_code` in `xai_credits`, `xai_permission` — agents must not re-call |
| `error_code` | `xai_credits` · `xai_permission` · `validation` · `media_internal` · … |
| `agent_guidance` / `message` | Human-readable STOP guidance (also on internal helper crashes) |
| `error` | Provider/helper error string when present |
| `next_skill` | `check_video` when video is still pending |

Missing API key may degrade to SVG poster/placeholder (no crash); still bill premium when a generate skill ran.

**Marketing pack:** `_PACK_KEYWORDS["marketing"]` and `_MEDIA_FOR_DOMAIN` include these ids. HTTP: `POST /media/image`, `/media/image/edit`, `/media/video`, **`GET /media/video/{request_id}`**. Needs wallet credits + `XAI_API_KEY` (or user key) for live output.

---

## Meetings

Multi-agent rooms: skills `open_meeting`, `invite_to_meeting`, `post_to_meeting`, `run_meeting_round`, `extract_meeting_tasks`, `close_meeting` → `skills/meetings.py` + `meeting_runner.py`. HTTP: `/meetings/*` (see [MEETINGS.md](MEETINGS.md)). Diary `schedule_meeting` is CRM diary, not a room.

---

## Integrations

1. Connect in Settings → Connected apps (`/integrations/{app_id}/connect`, OAuth).
2. Allocate to agents: `PUT /integrations/connections/{id}/agents` → `AgentIntegration`.
3. Agent uses named skills (`gmail_send`, `slack_*`, `shopify_*`, …) or generic `use_app` (`app_id` + `action` + `payload`).
4. Orchestrator may fall back to any workspace connection; members need allocation.
5. Prompt injects non-secret list via `integrations_context_for_agent`. Catalog: `integrations_catalog.INTEGRATION_APPS`.

---

## Billing CTAs (meter)

`GET /billing/meter` → `usage_billing.meter_snapshot` (also mirrored on some auth payloads):

| Field | Use |
|-------|-----|
| `upgrade_cta_path` | Primary nav target for upgrade/top-up |
| `primary_cta` / `secondary_cta` | `{ label, path, action }` — e.g. buy credits vs subscribe |
| `cta_buy_credits_path` | Always `/billing` |
| `cta_subscribe_path` | Always `/subscribe` |
| `needs_subscription` / `trial_ended` / `hard_block` | Drive which CTA wins |

UI: `TokenMeter` + `AppHeader` prefer server `primary_cta` / `upgrade_cta_path` (no plan → `/subscribe`; low fuel → `/billing` top-up). Product multi-agent growth remains hierarchy + skills — **no** in-app Grok Build manager spawn.

---

## Enable full tool access (market-leading)

1. **Plan** with agent + skill headroom (`plans.py`: trial **12 agents** / 120 skills; Starter/Pro raise caps + `premium_skills`). Confirm meter CTAs if pool is empty.
2. **Orchestrator** (full pack) + **leads** with domain `template_type` so `skills_for_template` + expanded **LEAD_FLOW** attach.
3. **`PUT /agents/{id}/skills`** or UI **Enable recommended pack** / `bulk_enable_skills` — core + lead flow always stay on; respect plan cap.
4. **Connect apps** + link agents; wire SMTP/Resend/Twilio for live send (premium comms).
5. **Credits:** platform `XAI_API_KEY` (and/or Anthropic) + user token pool / agent wallet so premium media & sends don’t fail-closed.
6. **Autonomy on:** `PUT /ops/autonomy` `{ "autonomy_enabled": true }` so queued chains keep running fail-smart.
7. **Permission:** agents `active` + execute permission (`operator`+); `never_idle` only if you want proactive feed.
8. Prefer **`run_workflow`** for the 24 presets; reserve `execute_goal` for free-text multi-step.

---

## Ops: autonomy fail-smart, CRON_SECRET, xAI credits

| Piece | What |
|-------|------|
| Engine | `autonomy.py` — ensure orchestrator → escalate stuck/failed → never_idle feed → drain queue |
| Fail-smart | `_is_terminal_provider_task` — **never requeues** spending limit / permission denied / credits exhausted / LLM unavailable |
| User tick | `GET\|POST /ops/autonomy/tick` (auth user) |
| Global cron | `GET\|POST /ops/autonomy/tick-all` — Vercel `vercel.json` schedule `0 6 * * *` → `/api/ops/autonomy/tick-all` |
| Auth | `X-Cron-Secret: <CRON_SECRET>` or `Authorization: Bearer <CRON_SECRET>` (or admin). Prod with empty secret → **503** for non-admin |
| Env | Strong `CRON_SECRET` in Vercel Production (`openssl rand -hex 32`) |
| xAI | `XAI_API_KEY` for Grok chat + Imagine media; user keys in Settings → API keys. Without credits/keys, premium skills error and free paths degrade (drafts/placeholders). |

### Frontend poll

Shell meter: sparse poll in `frontend/src/components/layout/useShellSession.js` — **45s** interval, 3s debounce, 12s min gap (WS-first; REST when quiet). Avoids old ~25s poll storms.

---

## Go-live (short)

Full checklist: [SQUAD_SHIP_NOTES.md](SQUAD_SHIP_NOTES.md#operator-go-live-checklist) · growth steps: [GROWTH_TOOL_ACCESS.md](GROWTH_TOOL_ACCESS.md).

1. Deploy env + LLM keys + `CRON_SECRET`.  
2. Activate plan (trial 12 agents or paid) + fund credits; confirm meter `primary_cta` / `upgrade_cta_path`.  
3. Orchestrator + domain agents; LEAD_FLOW + packs / recommended CTA.  
4. Connect + allocate apps; autonomy on.  
5. Smoke: `tool-access`, **`run_workflow`** (or HTTP workflows/run), CRM skill, media stop-thrash fields if failing, autonomy tick.

Related: [PRODUCTION_APIS.md](PRODUCTION_APIS.md) · [DOMAINS.md](DOMAINS.md).
