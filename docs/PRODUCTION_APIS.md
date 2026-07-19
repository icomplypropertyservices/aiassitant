# Production APIs & environment checklist

Set these in **Vercel → Project → Settings → Environment Variables** (Production + Preview as needed).

Canonical host and path layout: **[DOMAINS.md](./DOMAINS.md)** — `https://aibusinessagent.xyz` (no app/bay subdomains).

---

## aibusinessagent.xyz path layout

| URL | Purpose | Source |
|-----|---------|--------|
| `https://aibusinessagent.xyz/` | Marketing / landing | `website/` |
| `https://aibusinessagent.xyz/agents` | Product SPA | `frontend/` (`VITE_BASE=/agents/`) |
| `https://aibusinessagent.xyz/api` | Product API | `api/index.py` + `backend/` |
| `https://aibusinessagent.xyz/bay` | AgentBay marketplace SPA | `bay-dist/` or AgentBay build |
| `https://aibusinessagent.xyz/bay/api` | AgentBay API | proxy or co-deploy |

```
aibusinessagent.xyz
├── /                 marketing site
├── /agents/*         AI Business Assistant UI
├── /api/*            Assistant API (Stripe, auth, chat, …)
├── /bay/*            AgentBay UI
└── /bay/api/*        AgentBay API
```

**Env anchors tied to this layout (must match production):**

| Variable | Production value |
|----------|------------------|
| `FRONTEND_URL` | `https://aibusinessagent.xyz/agents` |
| `CORS_ORIGINS` | `https://aibusinessagent.xyz,https://www.aibusinessagent.xyz` |
| `API_PUBLIC_URL` | `https://aibusinessagent.xyz/api` (optional; OAuth redirect base) |
| `AGENTBAY_URL` / `AGENTBAY_PUBLIC_URL` | `https://aibusinessagent.xyz/bay` |
| Stripe webhook endpoint | `https://aibusinessagent.xyz/api/billing/webhook` |
| Vercel Cron path | `/api/ops/autonomy/tick-all` (see `vercel.json`) |

`FRONTEND_URL` is used for Stripe success/cancel redirects and password-reset links. **Do not** set it to the apex alone (`https://aibusinessagent.xyz`) — the product lives under **`/agents`**.

---

## Required (app will not run safely without these)

| Variable | Get it from | Purpose |
|----------|-------------|---------|
| `APP_ENV` | set to `production` | Enables prod locks (no demo admin, no free Stripe, strict JWT) |
| `JWT_SECRET` | `openssl rand -hex 32` | Signs login sessions (≥32 random chars) |
| `DATABASE_URL` | [Neon](https://neon.tech) / Supabase / Vercel Postgres | Postgres URL, e.g. `postgresql+psycopg2://user:pass@host/db?sslmode=require` |
| `FRONTEND_URL` | path deploy | **`https://aibusinessagent.xyz/agents`** (not apex, not bare `*.vercel.app` once custom domain is live) |
| `CORS_ORIGINS` | same host(s) | `https://aibusinessagent.xyz,https://www.aibusinessagent.xyz` |

**Recommended**

| Variable | Purpose |
|----------|---------|
| `ENCRYPTION_KEY` | Fernet key for user API keys / integration secrets (or long secret ≥16 chars). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

---

## Launch-critical env (ops must set before soft launch)

These are called out because they are easy to miss and block safe multi-tenant / scheduled operation.

### `FRONTEND_URL` → `/agents`

```env
FRONTEND_URL=https://aibusinessagent.xyz/agents
```

- Stripe Checkout `success_url` / `cancel_url` are built from this.
- Password-reset and email-verify deep links should land on the SPA under `/agents/...`.
- Pair with `CORS_ORIGINS` including apex (and `www` if used).

### `XAI_API_KEY` (platform Grok)

| Variable | Purpose | Where |
|----------|---------|--------|
| `XAI_API_KEY` | Business xAI API key for multi-tenant LLM | https://console.x.ai/ |
| `XAI_BASE_URL` | Optional override | default xAI API |
| `XAI_MODEL_FAST` / `XAI_MODEL_QUALITY` | Optional model ids | console docs |
| `XAI_USE_JWT_ONLY` | **Leave unset/false in production** | Prefer API key; personal Super/CLI JWT must not be the only prod path |

In production, prefer **`XAI_API_KEY`** over any personal Super JWT in env. Users may still paste their own keys in **Settings → API keys** (encrypted).

Also acceptable for platform LLM: `ANTHROPIC_API_KEY` (and/or managed RunPod/Ollama — see below).

### `CRON_SECRET` (autonomy tick)

| Variable | Purpose |
|----------|---------|
| `CRON_SECRET` | Shared secret for scheduled ops endpoints |

- Vercel Cron (root `vercel.json`): daily `0 6 * * *` → **`GET /api/ops/autonomy/tick-all`** (Vercel always uses GET).
- Endpoint also accepts **POST** (admin tools / curl). Handler: `backend/app/routers/ops.py` → `autonomy_tick_all`.
- Tick drains **queued** agent tasks (and on a full cycle: stuck/failed + idle feeds). Cooldown still drains the queue.
- Auth accepted (required; never open):
  - Header `X-Cron-Secret: <CRON_SECRET>`
  - or `Authorization: Bearer <CRON_SECRET>` (Vercel injects this when `CRON_SECRET` is set in the project env)
  - or admin API key
- In production, if `CRON_SECRET` is **empty**, non-admin callers get **503**.
- Generate: `openssl rand -hex 32` — set the same value in Vercel Production env.

### `REDIS_URL` (global rate limits)

Auth and sensitive endpoints use `backend/app/rate_limit.py`. Without Redis, counters are **per process** only (each Vercel instance has its own map).

| Variable | Purpose | Where |
|----------|---------|--------|
| `REDIS_URL` | Redis connection URL (preferred name) | Any Redis 6+ (Upstash, Redis Cloud, self-hosted) |
| `UPSTASH_REDIS_URL` | Alternate env name (same effect) | https://upstash.com → Redis URL (`rediss://…`) |

- If either is set: Redis `INCR` + `EXPIRE` (keys `rl:<key>`).
- On missing URL / import error / connect failure → **in-memory fallback** (not cluster-wide).
- Package: `redis>=5` in `backend/requirements.txt`.
- Example: `REDIS_URL=rediss://default:PASSWORD@HOST:6379`

---

## LLM (pick at least one for real AI — otherwise mock/Ollama)

| Provider | Variables | Where to get keys |
|----------|-----------|-------------------|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| **xAI (Grok)** | `XAI_API_KEY` (optional `XAI_BASE_URL`, `XAI_MODEL_FAST`, `XAI_MODEL_QUALITY`) | https://console.x.ai/ |
| **Ollama (self-hosted)** | `OLLAMA_URL`, `OLLAMA_MODEL_*` | https://ollama.com on your VPS |
| **RunPod fleet** | `RUNPOD_API_KEY`, `RUNPOD_OLLAMA_URL`, … | see [PRODUCTION_RUNPOD.md](./PRODUCTION_RUNPOD.md) |

Users can also paste their own keys in **Settings → API keys** (encrypted).

---

## Payments (required to charge customers)

### Card (Stripe) — sandbox then live

| Variable | Purpose | Where |
|----------|---------|--------|
| `STRIPE_SECRET_KEY` | Checkout | **Test:** https://dashboard.stripe.com/test/apikeys (`sk_test_…`) · **Live:** `sk_live_…` |
| `STRIPE_WEBHOOK_SECRET` | Confirm payments server-side | Stripe → Developers → Webhooks → signing secret (`whsec_…`) |
| `STRIPE_PRICE_STARTER` | Optional Price ID | Product → Price (if empty, app may use inline monthly price) |
| `STRIPE_PRICE_PRO` | Optional Price ID | same |
| `STRIPE_PRICE_BUSINESS` | Optional Price ID | same |

### Stripe webhook URL (production)

Register **exactly** this endpoint in the Stripe Dashboard (Live mode for go-live):

```text
https://aibusinessagent.xyz/api/billing/webhook
```

| Setting | Value |
|---------|--------|
| URL | `https://aibusinessagent.xyz/api/billing/webhook` |
| Events (recommended live) | `checkout.session.completed` (add portal/subscription events if you enable Customer Portal later) |
| Secret → env | `STRIPE_WEBHOOK_SECRET=whsec_…` |

**Sandbox testing**
1. Put `STRIPE_SECRET_KEY=sk_test_…` in Vercel Production (or Preview) env.
2. Redeploy.
3. Billing → “Top up with card (test)” or Subscribe with card.
4. Pay with `4242 4242 4242 4242`, any future expiry/CVC.
5. Redirect includes `session_id` → app calls `/billing/checkout/confirm` (webhook optional in sandbox; **required for reliable live fulfillment** if users close the browser).

Until custom domain DNS is live, temporary webhook host may be `https://<project>.vercel.app/api/billing/webhook` — switch to apex path above when `aibusinessagent.xyz` is attached.

### Crypto (ETH / SOL / XRP — self-custody)

| Variable | Purpose |
|----------|---------|
| `CRYPTO_ETH_ADDRESS` | Ethereum mainnet receive address |
| `CRYPTO_SOL_ADDRESS` | Solana mainnet receive address |
| `CRYPTO_BTC_ADDRESS` | Bitcoin mainnet receive address (bc1… / 1… / 3…) |
| `CRYPTO_XRP_ADDRESS` | XRP Ledger receive address (optional) |
| `CRYPTO_ETH_RPC` | Optional ETH JSON-RPC (default publicnode) |
| `CRYPTO_SOL_RPC` | Optional Solana RPC |
| `CRYPTO_XRP_RPC` | Optional XRPL HTTP endpoint |
| `CRYPTO_BTC_API` | Optional Blockstream-compatible API (default blockstream.info/api) |
| `CRYPTO_INVOICE_TTL_MIN` | Invoice lifetime minutes (default 60) |

**Flow:** user creates invoice → sends exact amount (XRP requires destination tag) → pastes tx hash → API verifies on-chain → plan / credits unlocked.

**Never put private keys in env.** Only public receive addresses.

Without Stripe **and** without crypto addresses in production: paid plans / top-ups return **503**.

---

## Email — Resend (agent notify + password reset)

| Variable | Purpose | Where |
|----------|---------|--------|
| `RESEND_API_KEY` | Send transactional email | https://resend.com → API Keys |
| `RESEND_FROM` | Verified From address | e.g. `assistant@aibusinessagent.xyz` or `AI Business Assistant <noreply@aibusinessagent.xyz>` |

### Domain setup (Resend)

1. Resend → Domains → add `aibusinessagent.xyz` (or subdomain `mail.aibusinessagent.xyz`).
2. Publish the DNS records Resend shows (SPF, DKIM, etc.).
3. Wait until domain status is **Verified**.
4. Set `RESEND_FROM` to an address on that domain.
5. Redeploy after env change.

### What uses Resend today

| Feature | Behavior |
|---------|----------|
| Agent skill / channel `notify_email` | Text send via Resend (optional BYOK); without key → drafted “not sent” |
| Transactional auth mail | `channels.send_transactional_email` — platform `RESEND_API_KEY` + `RESEND_FROM` only |
| Password reset | `POST /api/auth/forgot-password`, `POST /api/auth/reset-password` |
| Email verification | Register issues token; `POST /api/auth/verify-email`, `POST /api/auth/resend-verification` |

### Password reset email (launch requirement)

API behavior (backend):

1. `POST /api/auth/forgot-password` `{ "email": "..." }` — creates one-time `EmailToken` (`reset`), sends mail via Resend (no email enumeration).
2. Link target: `{FRONTEND_URL}/reset-password?token=...`  
   → production: `https://aibusinessagent.xyz/agents/reset-password?token=...`
3. `POST /api/auth/reset-password` `{ "token", "password" }` — sets password, bumps `token_version` (invalidates old JWTs), returns new JWT.
4. Verify flow: `{FRONTEND_URL}/verify-email?token=...` + `POST /api/auth/verify-email`.

**Ops checklist for reset / verify email (N7 Done criteria)**

- [ ] `RESEND_API_KEY` set in Vercel Production  
- [ ] Domain verified; `RESEND_FROM` uses that domain (not `assistant@yourdomain.com`)  
- [ ] `FRONTEND_URL=https://aibusinessagent.xyz/agents`  
- [ ] SPA routes for reset/verify exist under `/agents` (or user can complete via API + documented UI)  
- [ ] Smoke: forgot-password → inbox mail → open link → new password → login works; token one-shot  
- [ ] Without Resend in prod: no silent success pretending mail was sent  

Code in repo is **not** ops Done until Production inbox smoke passes.

---

## Outbound channels (optional beyond Resend)

| Provider | Variables | Where |
|----------|-----------|--------|
| **Twilio (SMS/voice)** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | https://console.twilio.com |

---

## Connected apps / OAuth (optional — users can use API keys in Settings)

Only needed for **one-click OAuth** (otherwise connect with tokens in the UI):

| App | Env vars | Docs |
|-----|----------|------|
| Shopify | `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` | https://shopify.dev |
| Google (Workspace/Gmail/Sheets/Business/YouTube) | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `API_PUBLIC_URL` or `OAUTH_REDIRECT_URI` | https://console.cloud.google.com — see **Google OAuth** below |
| Slack | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` | https://api.slack.com/apps |
| HubSpot | `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET` | https://developers.hubspot.com |
| Notion | `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET` | https://developers.notion.com |
| Dropbox | `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` | https://www.dropbox.com/developers |

### Google OAuth (required for 1-click Connect)

| Variable | Example |
|----------|---------|
| `GOOGLE_OAUTH_CLIENT_ID` | `….apps.googleusercontent.com` |
| `GOOGLE_OAUTH_CLIENT_SECRET` | `GOCSPX-…` |
| `API_PUBLIC_URL` | `https://aibusinessagent.xyz/api` |
| `OAUTH_REDIRECT_URI` (optional override) | `https://aibusinessagent.xyz/api/integrations/oauth/callback` |

**Google Cloud Console checklist**

1. Create **OAuth client type = Web application** (not Desktop / iOS).
2. **Authorized redirect URIs** — add **exactly**:
   ```text
   https://aibusinessagent.xyz/api/integrations/oauth/callback
   ```
   Do **not** use `/agents/api/...` — that path is wrong and causes Google **“request is invalid”**.
3. **Authorized JavaScript origins** — e.g. `https://aibusinessagent.xyz`
4. OAuth consent screen: External or Internal; if **Testing**, add every tester email.
5. Enable APIs as needed: Gmail, Sheets, Calendar, Drive, YouTube Data, Business Profile.

After deploy, Settings → Connected apps shows the live `redirect_uri` to copy. Token exchange reuses the same URI stored in OAuth `state`.

---

## Storage for training files (recommended in production)

Local disk on Vercel is ephemeral. Prefer:

| Backend | How |
|---------|-----|
| **Google Cloud Storage** | Connect in Settings (bucket + service account JSON or OAuth token) |
| **Dropbox** | Connect access token in Settings |

Optional platform env: `GCS_BUCKET`, `UPLOAD_ROOT` (local/VPS only).

---

## AgentBay bridge (if `/bay` is live)

| Variable | Purpose |
|----------|---------|
| `AGENTBAY_BRIDGE_SECRET` | Shared secret between product API and AgentBay; must be strong in production (empty/weak → bridge disabled or reject) |
| `AGENTBAY_URL` / `AGENTBAY_PUBLIC_URL` | `https://aibusinessagent.xyz/bay` |

---

## Native / iOS (if shipping App Store)

| Variable | Purpose |
|----------|---------|
| `VITE_PROD_API_URL` or `VITE_API_URL` | Absolute API: `https://aibusinessagent.xyz/api` |
| `VITE_NATIVE=1` | Capacitor build flag |

---

## 100% launch env matrix

Use this as the single “env complete” checklist. Check every row for Production in Vercel (and Preview if you test there).

### Core (P0)

| Variable | Example / rule | Set? |
|----------|----------------|------|
| `APP_ENV` | `production` | ☐ |
| `JWT_SECRET` | ≥32 random chars | ☐ |
| `DATABASE_URL` | Postgres + `sslmode=require` | ☐ |
| `FRONTEND_URL` | `https://aibusinessagent.xyz/agents` | ☐ |
| `CORS_ORIGINS` | apex + www | ☐ |
| `ENCRYPTION_KEY` | Fernet or long secret | ☐ |

### LLM (P0 — at least one platform path)

| Variable | Example / rule | Set? |
|----------|----------------|------|
| `XAI_API_KEY` | business key; no personal Super JWT as sole path | ☐ |
| and/or `ANTHROPIC_API_KEY` | Claude | ☐ |
| and/or RunPod/Ollama vars | managed fleet | ☐ |

### Payments (P0 — Stripe and/or crypto)

| Variable | Example / rule | Set? |
|----------|----------------|------|
| `STRIPE_SECRET_KEY` | `sk_live_…` for real money | ☐ |
| `STRIPE_WEBHOOK_SECRET` | from endpoint on apex `/api/billing/webhook` | ☐ |
| `STRIPE_PRICE_*` | optional Price IDs | ☐ |
| and/or `CRYPTO_*_ADDRESS` | public receive only | ☐ |

### Ops / security (P0–P1)

| Variable | Example / rule | Set? |
|----------|----------------|------|
| `CRON_SECRET` | `openssl rand -hex 32`; cron hits tick-all | ☐ |
| `REDIS_URL` or `UPSTASH_REDIS_URL` | global rate limits | ☐ |
| `RESEND_API_KEY` + `RESEND_FROM` | verified domain | ☐ |
| `AGENTBAY_BRIDGE_SECRET` | if using `/bay` | ☐ |
| `API_PUBLIC_URL` | `https://aibusinessagent.xyz/api` if OAuth | ☐ |

---

## Minimum “go live” set (copy-paste)

```text
APP_ENV=production
JWT_SECRET=<openssl rand -hex 32>
DATABASE_URL=postgresql+psycopg2://...
FRONTEND_URL=https://aibusinessagent.xyz/agents
CORS_ORIGINS=https://aibusinessagent.xyz,https://www.aibusinessagent.xyz
ENCRYPTION_KEY=<fernet key>
XAI_API_KEY=...                    # and/or ANTHROPIC_API_KEY
CRON_SECRET=<openssl rand -hex 32>
REDIS_URL=rediss://default:...@... # or UPSTASH_REDIS_URL
RESEND_API_KEY=re_...
RESEND_FROM=assistant@aibusinessagent.xyz
STRIPE_SECRET_KEY=sk_live_...      # or sk_test_ for sandbox-only soft launch
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=...           # optional
STRIPE_PRICE_PRO=...
STRIPE_PRICE_BUSINESS=...
CRYPTO_ETH_ADDRESS=0x...           # optional if using Stripe only
CRYPTO_SOL_ADDRESS=...
CRYPTO_BTC_ADDRESS=...
CRYPTO_XRP_ADDRESS=r...
API_PUBLIC_URL=https://aibusinessagent.xyz/api
AGENTBAY_PUBLIC_URL=https://aibusinessagent.xyz/bay
AGENTBAY_BRIDGE_SECRET=<strong random>   # if /bay enabled
```

Then: create a **real admin user** via register + promote in DB (or one-time bootstrap script). Do **not** rely on `admin@local` in production (demo seed is disabled when `APP_ENV=production`).

---

## Post-deploy smoke checklist

Run after every production deploy that changes env or routing. Prefer the custom domain; note if still on `*.vercel.app`.

### 1. Routing & health

| # | Check | Pass criteria |
|---|--------|----------------|
| 1 | Marketing | `GET https://aibusinessagent.xyz/` → 200, landing HTML |
| 2 | Product SPA | `GET https://aibusinessagent.xyz/agents` (or `/agents/`) → 200, app shell |
| 3 | SPA deep link | `GET https://aibusinessagent.xyz/agents/login` → 200 (rewrite to index, not API 404) |
| 4 | API health | `GET https://aibusinessagent.xyz/api/health` → 200 JSON (or project health path if renamed) |
| 5 | www | `https://www.aibusinessagent.xyz` → redirect or same content as apex |
| 6 | Docs locked | `GET /api/docs` and `/api/openapi.json` → **404** when `APP_ENV=production` |

### 2. Auth & CORS

| # | Check | Pass criteria |
|---|--------|----------------|
| 7 | Register | New user with strong password (≥8, letter+digit) succeeds |
| 8 | Weak password | `password` / `abcdefg` → 400 |
| 9 | Login | Returns JWT; SPA stores session under `/agents` |
| 10 | CORS | Browser call from apex to `/api` works; random origin blocked |
| 11 | Rate limit | Burst login/register → 429 when Redis or in-memory limit hits |

### 3. Billing

| # | Check | Pass criteria |
|---|--------|----------------|
| 12 | Stripe Checkout | Start checkout → lands on Stripe → success returns to **`FRONTEND_URL`** (`…/agents/…`) |
| 13 | Webhook | Stripe Dashboard → webhook endpoint **healthy**; test `checkout.session.completed` or real test payment credits plan |
| 14 | No free paid mint | Without Stripe/crypto, paid plan activate → 402/503 (not free credits in prod) |

### 4. LLM & ops

| # | Check | Pass criteria |
|---|--------|----------------|
| 15 | Chat/LLM | Agent chat returns real model text (not permanent mock) with `XAI_API_KEY` and/or Anthropic/RunPod |
| 16 | Cron secret | `GET` or `POST /api/ops/autonomy/tick-all` without secret → 403/503; with `X-Cron-Secret` or `Authorization: Bearer <CRON_SECRET>` → 200 |
| 17 | Cron schedule | Vercel → Cron Jobs shows daily **GET** job for `/api/ops/autonomy/tick-all`; recent run OK after secret set |
| 18 | Health flags | If health/status exposes them: `cron_secret_configured`, email/resend, etc. match env |

### 5. Email (Resend)

| # | Check | Pass criteria |
|---|--------|----------------|
| 19 | From domain | Resend domain verified for `aibusinessagent.xyz` |
| 20 | Agent email | Skill/channel that sends mail delivers to a test inbox (or explicit “not configured” if key unset — never silent success without send) |
| 21 | Password reset | When N7 live: request reset → email → link under `/agents` → new password works |

### 6. Optional path products

| # | Check | Pass criteria |
|---|--------|----------------|
| 22 | AgentBay UI | `GET /bay` → 200 if `bay-dist` deployed |
| 23 | Security headers | `curl -I https://aibusinessagent.xyz/agents` includes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, etc. |
| 24 | Legal | `/privacy.html`, `/terms.html`, `/support.html` load; footer links work |

**Soft-launch gate:** core env matrix complete + smoke **1–18** pass + legal pages live. Password-reset smoke (**21**) required when N7 is marked done.
