# Full-site strict code quality review — 2026-07-19 (refresh)

**Scope:** AI Business Assistant monorepo — FastAPI `backend/`, React SPA `frontend/src` (`/agents`), AgentBay `agentbay_backend/` (`/bay`), marketing `website/`, Vercel `api/` + root deploy.  
**Standard:** Grok code-review skill (structure first; “works” is not enough).  
**Measured:** ~180 source files / ~75k lines (excluding `node_modules` / `dist`).  
**Verdict:** **Do not approve the codebase as structurally healthy.** Product surface is shippable and several earlier blockers improved (skill registry, CSS split, company_scope, ownership helper, cache invalidation). The site still fails the approval bar on **god-modules past 1k lines**, **incomplete adoption of canonical helpers**, and **almost no automated tests**.

---

## Executive summary

| Area | Health | Notes |
|------|--------|--------|
| Product surface | Working | Agents, CRM, meetings, billing, integrations, skills, AgentBay |
| Skills dispatch | **Improved** | `HANDLER_TABLE` + default deliverable; elif tree gone |
| Skills implementation | **Still poor** | `handlers_all.py` **3,953** lines; catalog still fat in `agent_skills.py` **3,031** |
| Backend routers | **Poor** | 5 routers ≥1k; `agents.py` **2,084** |
| Frontend pages | **Poor** | Settings/AgentDetail/Business still ≥1.1k; partial tab extracts only |
| CSS | **Improved** | `global.css` thin shell; debt moved to `parts/mobile.css` **1,231** |
| Boundaries | Mixed | Good: meetings stack, shopify_*, task_chain, company_scope, ownership.py |
| Security hygiene | Acceptable | API-key auth; integration simulated fallback appears removed |
| Tests | **Critical gap** | Essentially one live smoke script; no CI unit suite |

**Approval bar:** fails. Highest-conviction work: split `handlers_all.py` + `agents.py` + Settings/AgentDetail/Business pages; finish `require_owned` / service-layer adoption; add a minimal pytest + frontend smoke gate.

---

## 1. Structural blockers (presumptive)

### 1.1 Skill runtime still a dual god-module — **critical**

| File | Lines | Role |
|------|------:|------|
| `backend/app/skills/handlers_all.py` | **3,953** | All `_skill_*` implementations |
| `backend/app/agent_skills.py` | **3,031** | Catalog, enable state, prompts, `execute_skill`, HANDLER_TABLE |
| `backend/app/skills_policy.py` | ~807 | Roles, packs, integration gates |

**What improved (do not re-open as elif debt):**
- Dispatch is registry-based (`HANDLER_TABLE` → ~146 side-effect skills).
- Mega catalog (~1,136 IDs) falls through `_skill_catalog_deliverable` — **0 truly unwired**.
- Handlers extracted out of a single 6k+ file (good direction).

**What still fails the bar:**
- `handlers_all.py` is the new collision magnet. CRM, meetings, comms, social, meta-spawn, and integrations share one namespace and import graph.
- Skills still re-implement ownership / CRM shape instead of a single `crm_service` used by HTTP + skills (34 ownership-style checks in handlers alone).
- Catalog dictionaries + mega-pack injection still live beside runtime in `agent_skills.py`.

**Code-judo (delete the “one handlers file” concept):**

```text
skills/
  catalog.py           # SKILL_CATALOG + mega load only
  dispatch.py          # HANDLER_TABLE, execute_skill, enabled state
  bridge.py            # late binds (exists)
  crm.py
  meetings.py
  comms.py
  meta_agents.py       # spawn/clone/enable
  integrations.py      # _run_app + social/gmail wrappers
  deliverable.py       # catalog_deliverable
```

Do **not** polish `handlers_all.py` with more helpers. **Split by domain** and make HTTP routers call the same domain functions skills call.

---

### 1.2 Backend routers past / near 1k lines

| File | Lines | Problem |
|------|------:|---------|
| `routers/agents.py` | **2,084** | CRUD + spawn + hierarchy + chat hooks + skills HTTP + wallets + FK cleanup |
| `routers/meetings.py` | **1,596** | Large; domain helpers exist but HTTP still fat |
| `routers/billing.py` | **1,391** | Plans, Stripe, top-up, meter |
| `routers/auth.py` | **1,268** | Register/login/2FA/API key/SSO |
| `routers/business.py` | **1,096** | CRM still dense after products extract |
| `integration_actions.py` | **1,011** | Multi-app action blob |
| `routers/integrations.py` | ~906 | OAuth + connect surface |

**agents.py code-judo:**  
`agents_crud.py` + `agents_spawn.py` + `agents_hierarchy.py` + `agents_skills_http.py` under one APIRouter include. Stop growing the 2k file.

---

### 1.3 Frontend file-size explosions

| File | Lines | Problem |
|------|------:|---------|
| `pages/Settings.jsx` | **~1,690–1,754** | Profile + keys + apps + vault — only `settings/helpers.js` extracted |
| `styles/parts/mobile.css` | **~1,231** | Mobile rules still a monolith after global split |
| `pages/AgentDetail.jsx` | **~1,170–1,204** | Config + skills + integrations; panel extract incomplete |
| `pages/Business.jsx` | **~1,124–1,161** | Only `business/BusinessProductsTab.jsx` extracted |
| `pages/MeetingRoom.jsx` | ~946–988 | Dense room UI |
| `pages/Agents.jsx` | ~921–957 | List + spawn + core team |
| `components/AppLayout.jsx` | ~696–720 | Acceptable if frozen |

**Code-judo:**
- Settings: real tab routes/components (`SettingsApps`, `SettingsKeys`, `SettingsProfile`) driven by `?tab=` — not more helpers in the same file.
- Business: `BusinessOverview` / `BusinessCustomers` / `BusinessPipeline` siblings (products already started).
- AgentDetail: lazy tab components + shared `useAgent(id)`.
- CSS: split `mobile.css` into nav / lists / sheets; keep tokens in one place.

---

## 2. Spaghetti / branching / magic

### 2.1 Skill enable defaults are “almost everything”

`DEFAULT_ENABLED` / member role pack still lands **~1,211** free IDs (mega catalog role-matching). Plan caps trim at persist time, but prompts and UI still reason about a huge surface.

**Prefer:** explicit core pack + template domain pack only; mega IDs opt-in / search, not default-on.

### 2.2 Frontend GET cache (`api.js`)

- ~8s GET cache for list-ish prefixes.
- Mutation invalidation **improved** (`/business`, `/org`, `/integrations`, `/billing`, `/tasks`, `/ops` now busted).

Remaining smell: prefix soup + magic TTL instead of a real query client. Acceptable short-term; do not grow more special cases — if stale bugs return, move to TanStack Query or drop cache.

### 2.3 Production WebSocket stub

`connectAuthedWs` returns a dead object in PROD unless `force`. Documented for Vercel, but call sites can assume live realtime.

**Prefer:** one `Realtime` adapter: `noop | poll | ws` so pages never branch on env.

### 2.4 Dual auth naming (API key vs token)

`getApiKey` / `getToken` dual localStorage keys is legacy glue. Works; keep deprecating `token` rather than adding a third alias.

---

## 3. Boundary & duplication

### 3.1 Ownership: helper exists, not canonical yet

| Signal | Count |
|--------|------:|
| Manual `user_id` / `owner_user_id != user.id` patterns | **~80** |
| `require_owned` mentions | **~69** (many still import-only / partial) |
| Worst file | `handlers_all.py` (**34** ownership checks) |

`ownership.require_owned` and `company_scope.resolve_company_id` are the right homes. **Thin wrappers in routers are fine; re-implementing ownership inside every skill is not.**

**Code-judo:** skills call `crm_service.get_customer(db, user, id)` which uses `require_owned` once. HTTP routers call the same.

### 3.2 Company resolution — mostly fixed

`company_scope.py` is used by business, products, shopify_sync. Keep it; delete any remaining copy-paste if it reappears.

### 3.3 Tags — half-canonical

`tags_util` exists; thin Shopify space-join adapter is OK. Kill router-local `_normalize_tags` wrappers when found.

### 3.4 Dual product concepts (document, don’t invent a fourth)

| Surface | Meaning |
|---------|---------|
| Business `Product` | Tenant catalogue |
| AgentBay listing | Marketplace sellable |
| Comms practice product | Pitch object |

One short `docs/PRODUCTS.md` prevents skill/LLM drift.

### 3.5 Dual backends (Assistant + AgentBay)

Separate FastAPI apps with bridge secret is intentional. Risk is duplicated auth/SSO patterns. Prefer shared small auth package only if drift reappears — do not merge products.

---

## 4. What is in relatively good shape

| Module / area | Why it passes a higher bar |
|---------------|----------------------------|
| Skill **dispatch** (`HANDLER_TABLE`) | Registry beats elif; default deliverable covers mega pack |
| `task_chain.py` | Clear goal → steps → rollup |
| Meetings stack | `meeting_runner` / `serialize` / `extract` + router |
| `shopify_actions` + `shopify_sync` | Domain-extracted |
| `business_products` router | Separates catalogue from pipeline |
| `company_scope` / `ownership` | Canonical helpers exist |
| `tags_util` | Shared normalize |
| CSS parts split | `global.css` no longer 4k dump |
| AgentBay routers | Mostly under 700 lines |
| Integration “simulated success” | Appears removed (fail closed) |

---

## 5. Site architecture map

```text
aibusinessagent.xyz
├── /                 marketing website/
├── /agents/*         React SPA (Vite base /agents/ in prod)
├── /api/*            FastAPI backend (api/index.py + backend/)
├── /bay/*            AgentBay UI
└── /bay/api/*        AgentBay API
```

Monorepo is coherent at the path level. Complexity is inside backend god-modules and SPA god-pages, not the deploy topology.

---

## 6. Tests & operability

| Gap | Severity |
|-----|----------|
| No meaningful unit/integration test suite in-repo | **High** |
| Smoke lives under `scripts/` (manual / live) | Medium |
| Skill audit + local smoke exist (`audit_skills.py`, `skill_smoke_local.py`) | Good tooling, not CI |

**Minimum bar to raise health:**
1. `pytest` for `execute_skill` happy paths + ownership 404s (no network).
2. One frontend smoke (login shell / health) in CI.
3. Keep live skill suite for staging only.

---

## 7. Prioritized code-judo backlog

| Priority | Move | Deletes |
|----------|------|---------|
| P0 | Split `handlers_all.py` by domain | Conflict magnet + 4k file |
| P0 | Split `routers/agents.py` into subrouters | 2k multi-domain router |
| P0 | Skills → shared CRM/service functions + `require_owned` | 34+ skill ownership forks |
| P1 | Settings / AgentDetail / Business tab components | 1.1k–1.7k pages |
| P1 | Explicit skill default packs (not 1.2k default-on) | Prompt bloat + plan cap thrash |
| P1 | Minimal pytest + CI smoke | “Works on my machine” culture |
| P2 | Realtime adapter for WS/poll/noop | Env special cases in pages |
| P2 | Further CSS part splits (`mobile.css`) | Unreviewable stylesheets |
| P2 | `docs/PRODUCTS.md` triangle | Model confusion |

---

## 8. Approval bar (skill)

| Criterion | Status |
|-----------|--------|
| No clear structural regression from recent skill work | **Pass** (registry + bridge imports) |
| Dramatic simplification of skill **implementation** layer | **Fail** (`handlers_all` 3.9k) |
| Files unjustifiably &gt;1k | **Fail** (14 files ≥1k) |
| Spaghetti special-case growth | **Mitigated** on dispatch / integrations |
| Canonical helper adoption | **Partial** (helpers exist; skills/routers still fork) |
| Test confidence | **Fail** |

**Recommendation:** Ship behavior fixes and deploys as needed. Do **not** call the site “clean.” Treat P0 splits as the next maintainability program — non-optional if the team keeps adding features weekly.

---

## 9. Snapshot metrics (this review)

```text
Source files (app/src/website/api, no node_modules): ~180
Total lines: ~75k
Files ≥1000 lines: 14
Files ≥700 lines: 29

Largest:
  handlers_all.py     3953
  agent_skills.py     3031
  agents.py           2084
  Settings.jsx        ~1750
  meetings.py         1596
  billing.py          1391
  mobile.css          1231
  auth.py             1268
  AgentDetail.jsx     ~1200
  Business.jsx        ~1160
  business.py         1096
  integration_actions 1011

Skills: catalog 1282 | HANDLER_TABLE 146 | unwired 0
Ownership neq patterns: ~80 | require_owned mentions: ~69
Automated tests found: ~1 (live skills smoke)
```
