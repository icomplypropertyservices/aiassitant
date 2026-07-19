# Domains — path layout (no subdomains)

**Canonical host:** [https://aibusinessagent.xyz](https://aibusinessagent.xyz)  
**WWW:** [https://www.aibusinessagent.xyz](https://www.aibusinessagent.xyz) → **301 redirect to apex only** (not a second site).

Group hub map (Riddle = `riddlewallet.com`, iComply, this AI cage):  
`C:\Users\E-Store\icomply-group\DOMAINS.md`

Full production env list: **[PRODUCTION_APIS.md](./PRODUCTION_APIS.md)**. Audit ops items: **[AUDIT_FIXES.md](./AUDIT_FIXES.md)**.

---

## aibusinessagent.xyz path layout

| URL | Purpose | Built from |
|-----|---------|------------|
| **https://aibusinessagent.xyz/** | Marketing / landing | `website/` |
| **https://aibusinessagent.xyz/demo.html** | Interactive product demo | `website/demo.html` |
| **https://aibusinessagent.xyz/features.html** | Features | `website/` |
| **https://aibusinessagent.xyz/pricing.html** | Pricing | `website/` |
| **https://aibusinessagent.xyz/agents** | Product app (SPA) | `frontend/` (`base: /agents/`) |
| **https://aibusinessagent.xyz/api/** | Product API (FastAPI) | `api/index.py` + `backend/` |
| **https://aibusinessagent.xyz/bay** | AgentBay marketplace (SPA) | `agent-marketplace/frontend` (`base: /bay/`) or `bay-dist/` |
| **https://aibusinessagent.xyz/bay/api/** | AgentBay API | AgentBay backend (separate project or proxy) |
| **https://aibusinessagent.xyz/privacy.html** · **terms** · **support** | Legal / store | `website/` |
| **https://www.aibusinessagent.xyz** | **Redirect → apex** | DNS / Vercel only |

No `app.` or `bay.` subdomains — one domain, path prefixes only.

```
aibusinessagent.xyz
├── /                 marketing site
├── /agents/*         AI Business Assistant UI
├── /api/*            Assistant API (Stripe, auth, chat, cron, …)
├── /bay/*            AgentBay UI
└── /bay/api/*        AgentBay API
```

| Public path | Notes |
|-------------|--------|
| `/agents` | Product home after login CTAs |
| `/agents/login` | SPA route (rewrite → `index.html`) |
| `/api/health` | Deploy smoke |
| `/api/billing/webhook` | **Stripe webhook URL** (live) |
| `/api/ops/autonomy/tick-all` | Vercel Cron target (needs `CRON_SECRET`) |
| `/privacy.html`, `/terms.html`, `/support.html` | Legal / store |

---

## Why paths instead of subdomains

- One SSL cert, one DNS record, simpler brand.
- Marketing CTAs are same-origin (`/agents/login`).
- Cookies / CORS simpler for the main product (`CORS_ORIGINS` = apex + www).

---

## Setup checklist

### 1. Vercel project (monorepo root)

Attach domain:

```text
aibusinessagent.xyz          ← primary (apex)
www.aibusinessagent.xyz      → 301 redirect to apex (Vercel Domains UI)
```

**Important:** In Vercel → Project → Settings → Domains, set **aibusinessagent.xyz** as primary
and enable “Redirect www to aibusinessagent.xyz”. Do **not** redirect apex → www
(that breaks “apex path layout” docs and some native clients).

Root directory: repository root (uses root `vercel.json`).

Build already (`scripts/vercel-build.sh`):

1. Builds React app with `VITE_BASE=/agents/`
2. Copies SPA → `public/agents/`  → loads at `/agents/*`
3. Copies `website/` → `public/`  → landing at `/`
4. Copies `bay-dist/` → `public/bay/` if present → `/bay/*`

Click-through (same host, path-only):

| From | To app | To AgentBay |
|------|--------|-------------|
| Landing `/` | `/agents/login` | `/bay/browse` |
| App menu | (in-app) | `/bay/browse` + Website `/` |
| Login | — | Website `/` · AgentBay `/bay/browse` |

Cron (root `vercel.json`):

```text
schedule: 0 6 * * *
path:     /api/ops/autonomy/tick-all
method:   GET (Vercel Cron always GETs; API also allows POST)
```

Requires env **`CRON_SECRET`** (see below). When set, Vercel sends `Authorization: Bearer <CRON_SECRET>` on the scheduled GET; the API also accepts `X-Cron-Secret`. Auth is never skipped.

### 2. Environment variables (app project) — launch set

#### Path / origin (required)

```env
APP_ENV=production
FRONTEND_URL=https://aibusinessagent.xyz/agents
CORS_ORIGINS=https://aibusinessagent.xyz,https://www.aibusinessagent.xyz
API_PUBLIC_URL=https://aibusinessagent.xyz/api
AGENTBAY_URL=https://aibusinessagent.xyz/bay
AGENTBAY_PUBLIC_URL=https://aibusinessagent.xyz/bay
```

| Variable | Why |
|----------|-----|
| **`FRONTEND_URL`** | Must include **`/agents`**. Stripe success/cancel and auth email links use this base. |
| **`CORS_ORIGINS`** | Browser calls from marketing apex and product SPA. |
| **`API_PUBLIC_URL`** | OAuth callback base when integrations OAuth is enabled. |

#### Secrets & data (required)

```env
JWT_SECRET=<openssl rand -hex 32>
DATABASE_URL=postgresql+psycopg2://user:pass@host/db?sslmode=require
ENCRYPTION_KEY=<fernet key>
```

#### LLM (required for real AI — at least one)

```env
XAI_API_KEY=xai-...
# and/or
ANTHROPIC_API_KEY=sk-ant-...
```

- Prefer **`XAI_API_KEY`** in production (multi-tenant safe). Do not rely on a personal Super/CLI JWT alone (`XAI_USE_JWT_ONLY` should be false/unset in prod).

#### Cron (required for scheduled autonomy)

```env
CRON_SECRET=<openssl rand -hex 32>
```

- Protects `GET|POST /api/ops/autonomy/tick-all` (Vercel Cron uses GET).
- Production without secret: non-admin → **503**.

#### Rate limits (recommended / launch for multi-instance)

```env
REDIS_URL=rediss://default:PASSWORD@HOST:6379
# or
UPSTASH_REDIS_URL=rediss://...
```

Without Redis, limits are per Vercel isolate only.

#### Email — Resend (agent mail + password reset)

```env
RESEND_API_KEY=re_...
RESEND_FROM=assistant@aibusinessagent.xyz
```

1. Verify domain `aibusinessagent.xyz` (or mail subdomain) in Resend DNS.
2. `RESEND_FROM` must use the verified domain.
3. Password-reset emails (when N7 is live) use Resend + links under  
   `https://aibusinessagent.xyz/agents/...` via `FRONTEND_URL`.
4. Agent `notify_email` uses the same key; without it, mail is drafted not sent.

#### Stripe

```env
STRIPE_SECRET_KEY=sk_live_...   # or sk_test_ for sandbox
STRIPE_WEBHOOK_SECRET=whsec_...
# optional:
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_BUSINESS=price_...
```

#### Stripe webhook URL

In Stripe Dashboard → Developers → Webhooks → Add endpoint:

```text
https://aibusinessagent.xyz/api/billing/webhook
```

| Item | Value |
|------|--------|
| Endpoint URL | `https://aibusinessagent.xyz/api/billing/webhook` |
| Events | at least `checkout.session.completed` |
| Signing secret | paste into Vercel as `STRIPE_WEBHOOK_SECRET` |

Do **not** point the live webhook at a stale `*.vercel.app` host after the custom domain is primary.

#### AgentBay (if enabled)

```env
AGENTBAY_BRIDGE_SECRET=<strong random ≥32 chars>
```

#### Crypto (optional if Stripe-only)

```env
CRYPTO_ETH_ADDRESS=0x...
CRYPTO_SOL_ADDRESS=...
CRYPTO_BTC_ADDRESS=...
CRYPTO_XRP_ADDRESS=r...
```

Full matrix and optional OAuth/Twilio/RunPod: **[PRODUCTION_APIS.md](./PRODUCTION_APIS.md)**.

### 3. DNS

At your registrar for `aibusinessagent.xyz`, add the records Vercel shows (usually A/CNAME for apex + www).

### 4. AgentBay (`/bay`) — same Vercel project

```powershell
cd C:\Users\E-Store\agent-marketplace
.\scripts\sync-to-monorepo.ps1
# Then redeploy AI Business Assistant monorepo
```

| Path | Handler |
|------|---------|
| `/bay/*` | Static SPA (`bay-dist` → `public/bay`) |
| `/bay/api/*` | Rewrite → `/api/__bay__/*` → AgentBay routers |

Env (Vercel project):

```env
PUBLIC_APP_URL=https://aibusinessagent.xyz/bay
PUBLIC_API_URL=https://aibusinessagent.xyz/bay/api
BRIDGE_SECRET=...
AGENTBAY_URL=https://aibusinessagent.xyz/bay
AGENTBAY_BRIDGE_SECRET=...   # same as BRIDGE_SECRET
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Stripe webhook: `https://aibusinessagent.xyz/bay/api/webhooks/stripe`

### 5. Mobile / native

Native shells keep `base: /` + HashRouter. Point API at domain root:

```env
VITE_PROD_API_URL=https://aibusinessagent.xyz/api
```

Rebuild: `npm run build:mobile` (or `:sandbox`).

Privacy / Support (store listings):

- https://aibusinessagent.xyz/privacy.html  
- https://aibusinessagent.xyz/support.html  
- https://aibusinessagent.xyz/terms.html  

### 6. Local dev (unchanged ergonomics)

| Piece | Command | URL |
|-------|---------|-----|
| Marketing | `cd website && npm start` | http://localhost:5174 |
| App UI | `cd frontend && npm run dev` | http://localhost:5173 (base `/`) |
| App API | `uvicorn app.main:app --port 8000` | http://localhost:8000 |
| AgentBay | `cd agent-marketplace/frontend && npm run dev` | http://localhost:5173 |

Path prefixes apply in **production** builds only (or set `VITE_BASE` explicitly). Locally, `FRONTEND_URL=http://localhost:5173` is fine (no `/agents` prefix).

---

## Post-deploy smoke checklist (domain-focused)

After DNS + env + redeploy:

| # | Action | Pass |
|---|--------|------|
| 1 | Open `/` | Marketing 200 |
| 2 | Open `/agents` | Product SPA 200 |
| 3 | `GET /api/health` | 200 |
| 4 | Login / register on `/agents` | JWT session works |
| 5 | Stripe test or live checkout | Return URL under `/agents` (`FRONTEND_URL`) |
| 6 | Stripe webhook | Endpoint URL = `https://aibusinessagent.xyz/api/billing/webhook`; Dashboard shows success |
| 7 | Cron | tick-all without secret fails; with `CRON_SECRET` succeeds; Vercel Cron history green |
| 8 | Resend | Domain verified; test agent email (and reset mail when N7 ships) |
| 9 | Redis | Optional: burst auth → consistent 429 across instances when `REDIS_URL` set |
| 10 | Headers / legal | Security headers present; privacy/terms/support load |

Expanded smoke table: **[PRODUCTION_APIS.md § Post-deploy smoke checklist](./PRODUCTION_APIS.md)**.

---

## Until custom DNS is live

App may still be on the old Vercel host (`*.vercel.app`). Temporary values:

```env
FRONTEND_URL=https://YOUR-PROJECT.vercel.app/agents
CORS_ORIGINS=https://YOUR-PROJECT.vercel.app
```

Stripe webhook (temporary):

```text
https://YOUR-PROJECT.vercel.app/api/billing/webhook
```

After attaching **aibusinessagent.xyz**:

1. Set `FRONTEND_URL=https://aibusinessagent.xyz/agents` and apex `CORS_ORIGINS`.
2. Move Stripe webhook to `https://aibusinessagent.xyz/api/billing/webhook`.
3. Redeploy and run the smoke checklist on the custom domain.
