# Ecosystem status

**Scanned:** 2026-07-19 ~11:35 UTC (local wall ~13:35 +02:00)  
**Workspace:** `C:\Users\E-Store\ai-business-assistant\ai-business-assistant`  
**Production host:** `https://www.aibusinessagent.xyz` (apex `aibusinessagent.xyz` → 308 to www)

---

## 1. Deploy status (known)

| Item | Value |
|------|--------|
| Vercel project | `aiassitant` (`prj_NeljlH8f25HtVeLS3Vr2WqlqpAUa`) |
| Team | `team_XOjv4OXZXLw5DqcoXunnleUd` (`icomplypropertyservices-projects`) |
| Latest production deploy | `dpl_7pmmCigy6sFGNBgM6GZ2rxiov5pE` |
| Deploy state | **READY** (target: production) |
| Deploy URL | `aiassitant-n5a5q4gnm-icomplypropertyservices-projects.vercel.app` |
| Git commit (deploy) | `b95243a` — *Add agent CLI/API, crypto wallets, git repos, local machines, orchestrator 3-company bootstrap.* |
| Branch | `main` |
| Domains | `aibusinessagent.xyz`, `www.aibusinessagent.xyz`, `aiassitant-nu.vercel.app`, project alias |
| Framework | FastAPI (`vercel.json`) + static SPA (`frontend/dist` → `/agents`) + bay (`bay-dist` → `/bay`) |
| Note | Several recent deploys show `gitDirty: 1` (CLI/local deploy with uncommitted tree). Local workspace **also dirty** vs `origin/main` at `b95243a`. |

### Live probe (production)

| Endpoint | Result |
|----------|--------|
| `GET /api/health` (www) | **200** — see payload below |
| `GET /` (marketing) | **200** (slow/cold; 60s timeout can fail, ~90s OK) |
| `GET /agents`, `/agents/login` | **200** SPA shell |
| `GET /demo.html`, `/pricing.html` | **200** |
| `GET /bay` | **200** SPA |
| `GET /bay/api/health` | **200** but **`ready: false`** |
| `POST /api/auth/login` `admin@local` | **401** (prod correctly rejects demo admin) |
| `POST /api/auth/register` | **200** → `aba_…` session key |
| Runtime logs (24h) | 2× **500**, 1× **200** sample (errors present, low volume) |

**`/api/health` payload (live):**

```json
{
  "ok": true,
  "service": "ai-business-assistant",
  "version": "1.5.0",
  "environment": "production",
  "serverless": true,
  "billing_free_grants": false,
  "docs_enabled": false,
  "cron_secret_configured": false,
  "path_frontend_hint": "https://aibusinessagent.xyz/agents",
  "cli_api": true,
  "features": [
    "agent_wallets",
    "git_repos",
    "local_machines",
    "orchestrator_bootstrap",
    "meeting_rooms"
  ]
}
```

**AgentBay health (live):**

```json
{
  "ok": true,
  "app": "AgentBay Marketplace",
  "path": "/bay/api",
  "demo": false,
  "ready": false,
  "issues": ["BRIDGE_SECRET missing or weak — agent bridge disabled"],
  "stripe": true
}
```

---

## 2. Files present (workspace inventory)

Rough counts exclude `node_modules`, `.venv`, `__pycache__`, `.git`.

### Top-level layout

| Path | Role | ~Files |
|------|------|-------:|
| `api/` | Vercel serverless entry (`index.py` → FastAPI) | 1 |
| `backend/` | Main product API (`app/`, routers, CLI, RunPod scripts) | ~90 |
| `agentbay_backend/` | AgentBay marketplace API (mounted under bay routes) | ~21 |
| `frontend/` | React SPA + Capacitor iOS/Android shells + `dist/` | ~214 (+ huge `node_modules`) |
| `bay-dist/` | Built AgentBay static assets | 4 |
| `website/` | Marketing HTML (landing, demo, pricing, legal) | 23 |
| `docs/` | Launch / ops / store docs | 11 |
| `scripts/` | Smoke, bootstrap, env, audit tooling | 16–19 |
| Root | `vercel.json`, `package.json`, `requirements.txt`, `pyproject.toml`, env samples, local `app.db` | — |

### By extension (workspace source-ish)

| Ext | Count | Ext | Count |
|-----|------:|-----|------:|
| `.py` | 107 | `.jsx` | 40 |
| `.md` | 25 | `.html` | 21 |
| `.js` | 44 | `.png` | 56 |
| `.json` | 17 | mobile/xml/gradle/etc. | various |

### Backend surface

- **Core:** `backend/app/main.py` (health 1.5.0), models, LLM, billing, autonomy, wallets, git workspace, local machines, orchestrator bootstrap, meetings.
- **Routers (21):** auth, agents, chat, billing, dashboard, admin, org, keys, integrations, training, humans, ops, business, media, permissions, devices, marketplace, cli_api, meetings, templates, …
- **AgentBay:** `agentbay_backend/agentbay/` — auth, catalog, chat, listings, media, orders, stripe, SSO, WS.

### Frontend SPA pages (`frontend/src/pages/`)

Admin, AgentChat, AgentDetail, Agents, Analytics, Billing, Business, Chat, CompanyProfile, CustomerDetail, Dashboard, Hierarchy, Humans, Login, MeetingRoom, Meetings, Ops, Permissions, Profile, ResetPassword, Settings, Subscribe, TasksBoard, Templates, Training, VerifyEmail, Workspace (+ `settings/`).

### Marketing (`website/`)

`index.html`, `demo.html`, `features.html`, `pricing.html`, `about.html`, `privacy.html`, `terms.html`, `support.html`, `robots.txt`, `sitemap.xml`, `css/`, `js/demo.js` (client-only mock walkthrough).

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `bootstrap_demo_ecosystem.py` | Full demo: register/login → orchestrator → tasks → meeting |
| `create_test_account.py` | Throwaway prod account + orchestrator + templates |
| `audit_smoke.py` | Launch/security smoke |
| `smoke_meetings.py` | Meetings smoke |
| `test_skills_live.py` / `debug_bots_20.py` | Live skill/bot probes |
| `push_vercel_env.ps1` / `_merge_prod_env.py` | Env ops |
| `vercel-build.sh` | Vercel monorepo build |
| `_try_login.py` / `_probe_auth.py` | Auth path probes |
| `.demo_token` | Local token cache (do not commit secrets) |
| **`ECOSYSTEM_STATUS.md`** | This file |

### Docs (`docs/`)

`LAUNCH_100.md`, `LAUNCH_PLAN.md`, `AUDIT_FIXES.md`, `PRODUCTION_APIS.md`, `PRODUCTION_RUNPOD.md`, `DOMAINS.md`, `STORE_READY.md`, `APP_STORE_IOS.md`, `STRIPE_SANDBOX.md`, `CLI_AND_WORKSPACE.md`, `MEETINGS.md`.

### Local git (workspace)

- **HEAD:** `b95243a` (matches latest production commit SHA)
- **Tracking:** `main...origin/main`
- **Dirty:** many modified files under `backend/`, `agentbay_backend/`, `api/`, `frontend`, etc. (local work not necessarily redeployed)

---

## 3. Demo / login flow

### A. Marketing interactive demo (no auth)

1. Open `https://www.aibusinessagent.xyz/demo.html`
2. Client-side guided UI (`website/js/demo.js`) — **no API keys, no login**
3. 5 steps: Dashboard → Workspace → Agents → Chat → Billing → CTA to product

### B. Real product login (production SPA)

1. Open `https://www.aibusinessagent.xyz/agents/login` (or `/agents` → login)
2. **Login tab:** `POST /api/auth/login` `{ email, password }`
3. **Register tab:** `POST /api/auth/register` `{ email, password, name, company_name }`
4. Password rules: ≥8 chars, at least one letter + one digit
5. Response: `{ api_key|token: "aba_…", user: { … needs_subscription, plan, … } }`
6. Client stores session via `setAuth(sessionKey, user)`
7. If `user.needs_subscription` → navigate **`/subscribe`**; else dashboard `/`

### C. Post-register subscription gate (verified live)

New users start as:

- `plan: "none"`
- `needs_subscription: true`
- `email_verified: false`

Until a plan is active:

| Call | Result |
|------|--------|
| `GET /api/org/companies` | **402** `"Choose a subscription plan to continue"` |
| `POST /api/agents/ensure-orchestrator` | **402** |

**Trial path (works on prod):**

```http
POST /api/billing/plan
Authorization: Bearer aba_…
{ "plan": "trial" }
```

→ **200** trial ~14 days, 50k tokens; then companies + orchestrator succeed.

UI: Subscribe page posts `/billing/plan` (same as Billing). Pre-order messaging targets launch **27 July 2026**.

### D. Demo ecosystem bootstrap (scripts)

```powershell
cd C:\Users\E-Store\ai-business-assistant\ai-business-assistant

# Throwaway account on production
python scripts/create_test_account.py
# Default password: TestAgent1
# Email: test+<ts>@aibusinessagent.xyz

# Full ecosystem (orchestrator, tasks, meeting)
python scripts/bootstrap_demo_ecosystem.py
# Defaults: host www.aibusinessagent.xyz, password DemoAgent1
# Or: set ABA_EMAIL / ABA_PASSWORD / ABA_TOKEN
```

**Note:** Bootstrap must activate trial (`POST /billing/plan` `{plan:trial}`) or use an already-subscribed account; bare register alone cannot call org/agents (402).

### E. Local-only demo admin (NOT production)

| Env | Credentials |
|-----|-------------|
| Local (`APP_ENV` ≠ production) | `admin@local` / `admin123` (seeded) |
| Production | **Not seeded**; login returns **401** (verified) |

Never document `admin@local` as a production login.

### F. Forgot password / verify email

SPA routes: forgot on Login, `ResetPassword.jsx`, `VerifyEmail.jsx`.  
Backend: `/api/auth/forgot-password`, reset, verify (Resend-dependent). **Prod inbox delivery not re-verified in this scan.**

---

## 4. Remaining gaps

### P0 / launch blockers

| # | Gap | Evidence |
|---|-----|----------|
| G1 | **`CRON_SECRET` not set** | Health: `cron_secret_configured: false`. Daily autonomy cron `/api/ops/autonomy/tick-all` cannot be safely authenticated. |
| G2 | **AgentBay not ready** | `/bay/api/health` → `ready:false`, `BRIDGE_SECRET missing or weak`. Marketplace bridge disabled. |
| G3 | **Workspace ≠ clean prod tree** | Local dirty working tree; deploys flagged `gitDirty`. Risk of “works on laptop, not on Vercel” drift. |

### P1 / ops soft-launch

| # | Gap | Notes |
|---|-----|--------|
| G4 | Resend email (reset/verify) | Code present; **inbox smoke not confirmed** this scan (`email_verified: false` on new users). |
| G5 | Redis / global rate limits | Optional; multi-instance Vercel limiter may be in-memory only. |
| G6 | Stripe live webhook + Price IDs | Bay reports `stripe: true`; full webhook/portal live path not re-proven here. |
| G7 | Runtime 500s | 2 errors in last 24h sample — worth inspecting Vercel runtime logs. |
| G8 | Marketing cold start | Apex/www `/` can exceed 60s on cold; SPA/API healthier. |
| G9 | `LAUNCH_100.md` stale | Still scores ops “0–40% HOLD”; production is **deployed and healthy** — docs should be updated after G1–G2. |

### P2 / product polish

| # | Gap | Notes |
|---|-----|--------|
| G10 | New-user friction | Register → **must** hit Subscribe/trial before any org/agent work (by design; bootstrap scripts should auto-start trial). |
| G11 | `GET /api/dashboard/summary` | **404** for new session (route missing or renamed). |
| G12 | Dedicated reviewer account | Store/review docs require a non-personal demo account — create deliberately, do not use `admin@local`. |
| G13 | WS on Vercel | WebSockets unreliable on serverless; REST fallback required (documented). |
| G14 | Mobile store packages | Capacitor shells present; store submission checklist still ops (`docs/STORE_READY.md`). |

### What is healthy (do not re-break)

- Production deploy **READY** on custom domains  
- Auth register/login + password strength  
- Demo admin **disabled** in production  
- Trial via `POST /billing/plan` `{ "plan": "trial" }`  
- Orchestrator ensure after trial  
- Templates list  
- SPA path layout `/agents`, marketing pages, `/bay` static  
- Billing free grants **off** in production (`billing_free_grants: false`)  
- OpenAPI/docs **off** in production (`docs_enabled: false`)  
- `FRONTEND_URL` hint points at `/agents`  

---

## 5. Suggested next actions (ops only)

1. Set strong **`CRON_SECRET`** on Vercel Production; confirm cron hit with secret → 200.  
2. Set strong **`AGENTBAY_BRIDGE_SECRET`** (≥32 chars); recheck `/bay/api/health` → `ready: true`.  
3. Commit or explicitly discard local dirty changes; redeploy clean `main` if needed.  
4. Smoke: register → trial → ensure-orchestrator → one chat (`scripts/bootstrap_demo_ecosystem.py` after trial step).  
5. Inbox test: forgot-password with Resend.  
6. Refresh `docs/LAUNCH_100.md` ops score once G1–G2 pass.  

---

## 6. Quick commands

```powershell
# Health
Invoke-RestMethod https://www.aibusinessagent.xyz/api/health

# Bay
Invoke-RestMethod https://www.aibusinessagent.xyz/bay/api/health

# Smoke (with API base)
$env:BASE_URL = "https://www.aibusinessagent.xyz/api"
python scripts/audit_smoke.py

# Demo account + ecosystem
python scripts/create_test_account.py
python scripts/bootstrap_demo_ecosystem.py
```

---

*Generated by workspace + production health scan after wait window. Secrets intentionally omitted.*
