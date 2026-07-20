# Skill packs overview

How domain skill packs enter the catalog and how agents get a default enable set. Runtime access / gates: [AGENT_TOOLS_AND_FLOWS.md](AGENT_TOOLS_AND_FLOWS.md). Growth checklist: [GROWTH_TOOL_ACCESS.md](GROWTH_TOOL_ACCESS.md). Code: `backend/app/skill_packs/`, `skills_policy.py`, `agent_scaffold.py`, `agent_skills.py`.

**Product spawn** = hierarchy skills + template packs (`spawn_agent`, ensure-orchestrator, seed team). **Not** an in-app Grok Build manager.

---

## Mega packs on disk (`backend/app/skill_packs/`)

Loaded by `skill_packs.load_mega_skills()` — sorted `NN_*.json` (fallback: `MEGA_CATALOG.json`). ~20 × 50 = **1000** entries; default handler `catalog_deliverable`.

| File | Domain (typical `pack` / category) |
|------|-------------------------------------|
| `01_sales.json` | Sales |
| `02_marketing.json` | Marketing |
| `03_customer_success.json` | Customer success |
| `04_support.json` | Support |
| `05_finance.json` | Finance |
| `06_legal.json` | Legal |
| `07_hr.json` | HR |
| `08_operations.json` | Operations |
| `09_product.json` | Product |
| `10_engineering.json` | Engineering |
| `11_data.json` | Data |
| `12_content.json` | Content |
| `13_social.json` | Social |
| `14_project.json` | Project / PM |
| `15_procurement.json` | Procurement |
| `16_logistics.json` | Logistics |
| `17_real_estate.json` | Real estate |
| `18_healthcare.json` | Healthcare |
| `19_education.json` | Education |
| `20_executive.json` | Executive |

Also: `__init__.py` (loader), `MEGA_CATALOG.json` (optional dump), `README.md`, `SKILL_LIST_1000.md`.

Skill ids use prefixes (`sales_`, `mkt_`, `cs_`, `sup_`, `fin_`, `leg_`, `hr_`, `ops_`, `prd_`, `eng_`, `dat_`, `cnt_`, `soc_`, `pm_`, `prc_`, `log_`, `re_`, `hc_`, `edu_`, `exec_`). Merged into `SKILL_CATALOG` at import (`agent_skills.py`).

---

## Template packs vs mega JSON

**Two layers:**

1. **Spawn/enable packs** (`skills_policy.SKILL_PACKS`): `sales`, `marketing`, `support`, `coding`, `research`, `orchestrator`, `lead`, `full` — built by `skills_for_pack` / `skills_for_template` from **core + non-mega** catalog skills (keyword / explicit lists).
2. **Mega JSON packs** — always **browsable / opt-in**; `is_mega_catalog_skill` keeps them **out of template defaults** so spawns stay lean. Enable via UI `PUT /agents/{id}/skills` or lead meta skills when plan caps allow.

---

## `skills_for_template` / roles

```
agent.template_type  →  skill_pack_for_template()  →  skills_for_pack(pack, role=…)
```

| Role | Behavior |
|------|----------|
| **member / specialist** | Free toolkit (`default_enabled_for_role`) + domain non-mega layer; no premium (except limited media on marketing); no live send/post by default; no `_META_DANGEROUS` |
| **lead** | Same + premium allowed; lead flow skills always kept (`LEAD_FLOW_SKILLS` in `agent_skills.py`) |
| **orchestrator** / pack `full`/`orchestrator` | Near-full catalog for role (auto field flood still skipped) |

`_TEMPLATE_TO_PACK` maps types e.g. `sales`/`sdr`/`outreach` → **sales**; `marketing`/`content`/`social` → **marketing**; `support`/`cs` → **support**; `coding`/`engineer` → **coding**; `research`/`analyst` → **research**; `orchestrator` / `lead` → hierarchy packs. Aliases: `eng` → coding, `comms` → sales.

Always unioned with **`_CORE_ALWAYS`** (tasks, CRM customers/deals/pipelines/products/diary, meetings hooks, drafts, workflows, patterns, …). Called from `default_enabled_skills_for_role` / `ensure_agent_skills` on spawn and repair.

### CRM + lead surface (market-leading defaults)

- **CRM** skills live in category `crm` (`skills_policy`) and in `_CORE_ALWAYS` so agents never lose list/create/move deal tooling.
- **`LEAD_FLOW_SKILLS`** keeps goals, spawn, patterns, review, meetings, CRM create paths, and media hooks on leads even when the UI enable list is thinned.
- UI **Enable recommended pack** (`AgentSkillsPanel`) enables a curated CRM + workflow core subset in one click (no premium send skills).

### Media domain layer

Five premium media skills (`generate_image`, `edit_image`, `generate_ad_creative`, `generate_product_shot`, `generate_video`) sit in `_MEDIA_FOR_DOMAIN` / marketing keywords. Marketing and lead templates may enable them even when plan `premium_skills` is false; every run still bills `cost_credits`.

### Workflows (not skill packs, same enable surface)

Named multi-step presets live in `workflows.py` (**24** `WORKFLOW_PRESETS`). Surfaced on `GET /agents/{id}/tool-access` and Agent Home; started via `POST /agents/workflows/run` or skills `create_workflow` / `execute_goal`. See [AGENT_TOOLS_AND_FLOWS.md](AGENT_TOOLS_AND_FLOWS.md#workflows-24).

---

## Plan caps

`plans.py` (assert with `scripts/assert_trial_plan.py`):

| Plan field | Trial | Notes |
|------------|------:|-------|
| `agents` | **12** | `TRIAL_AGENTS` |
| `skills_per_agent` | 120 | Simultaneous enables |
| `skill_packs` | 6 | Of 20 mega domains |
| `premium_skills` | false | Media still chargeable per use |
| Tokens / companies / projects | 50k / 2 / 3 | One-shot 14-day trial |

Catalog remains searchable; only the **enabled** set runs. Inspect live enable set + caps via **`GET /agents/{id}/tool-access`**.

---

## Operator tips

1. Spawn with correct `template_type` so domain packs attach automatically.  
2. Use recommended pack CTA before hand-enabling mega JSON skills.  
3. Upgrade plan when hitting 120 skills or 6 packs on trial.  
4. Confirm `tool-access` after repair/scaffold so CRM + workflows show as expected.
