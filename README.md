# AI Business Assistant

Full-stack SaaS: FastAPI backend + React (Ant Design) frontend, real-time WebSockets throughout.
Integrations activate when you add API keys and fall back to safe dev mode when keys are missing.

## Quick start (2 terminals)

**Backend** (Python 3.10+):
```bash
cd backend
cp .env.example .env        # then fill in your keys
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (Node 18+):
```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Admin login: **admin@local / admin123**

---

## Deploy frontend on Vercel

The **React SPA** deploys to Vercel. The **FastAPI backend does not** run on Vercel (long-lived WebSockets + Python app server). Host the API on Railway, Render, Fly.io, a VPS, etc., then point the SPA at it.

### 1. Host the API first

Example (any host with HTTPS):

```bash
cd backend
# set production env — see backend/.env.example
export APP_ENV=production
export JWT_SECRET="$(openssl rand -hex 32)"
export FRONTEND_URL="https://your-app.vercel.app"
export CORS_ORIGINS="https://your-app.vercel.app"
# DATABASE_URL, Stripe, LLM keys, etc.
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ensure:

| Backend env | Value |
|-------------|--------|
| `APP_ENV` | `production` |
| `FRONTEND_URL` | Your Vercel URL (and custom domain if any) |
| `CORS_ORIGINS` | Same origin(s), comma-separated (not `*`) |
| `JWT_SECRET` | Long random secret |

WebSockets must be supported on the API host (`/ws/chat`, `/agents/.../ws/chat`, `/agents/ws`, `/billing/ws/tokens`).

### 2. Deploy to Vercel

**Option A — GitHub (recommended)**  
1. Push this repo (already on GitHub).  
2. [vercel.com](https://vercel.com) → **Add New Project** → import `aiassitant` (or this repo).  
3. Framework: Vite (auto via root `vercel.json`).  
4. Set environment variable:

| Name | Example |
|------|---------|
| `VITE_API_URL` | `https://api.yourdomain.com` |

**No trailing slash.** This is baked in at **build** time — redeploy after changing it.

5. Deploy. Root config:

- Install: `cd frontend && npm install`  
- Build: `cd frontend && npm run build`  
- Output: `frontend/dist`  
- SPA rewrites: all non-asset routes → `index.html`

**Option B — CLI**

```bash
npm i -g vercel
cd /path/to/ai-business-assistant
vercel env add VITE_API_URL   # production value
vercel --prod
```

### 3. Local frontend against remote API

```bash
cd frontend
echo "VITE_API_URL=https://api.yourdomain.com" > .env
npm run dev
```

See also `frontend/.env.example`.

### Architecture

```
Browser (Vercel SPA)
   │  HTTPS REST + WSS
   ▼
FastAPI (Railway / Render / Fly / VPS)
   │
   ▼
Postgres / Ollama / Stripe / LLM APIs
```

---

## Production APIs & keys you need

You do **not** need every service on day one. Minimum for a real product: **JWT + domain + one LLM path**.

### Required (always)

| What | Variable | Where to get it | Notes |
|------|----------|-----------------|-------|
| App JWT signing | `JWT_SECRET` | Generate yourself (`openssl rand -hex 32`) | **Required** when `APP_ENV=production`. ≥32 chars. |
| Public frontend URL | `FRONTEND_URL` | Your domain | Used for Stripe success/cancel redirects |
| CORS allowlist | `CORS_ORIGINS` | Your domain(s) | e.g. `https://app.yourdomain.com` (avoid `*` in prod) |
| Database | `DATABASE_URL` | You host it | SQLite OK for demos; **Postgres recommended** in production |

### LLM (pick at least one path)

| Provider | Variables | Signup | Used for |
|----------|-----------|--------|----------|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) | Premium: `claude-sonnet`, `claude-haiku` |
| **xAI (Grok)** | `XAI_API_KEY`, optional `XAI_BASE_URL`, `XAI_MODEL_FAST`, `XAI_MODEL_QUALITY` | [console.x.ai](https://console.x.ai/) | Premium: `grok-fast`, `grok` |
| **Ollama (self-hosted)** | `OLLAMA_URL`, `OLLAMA_MODEL_FAST`, `OLLAMA_MODEL_QUALITY` | [ollama.com](https://ollama.com) on your VPS | `vps-fast`, `vps-quality` |

Fallback chain: **selected provider (Claude or Grok) → Ollama → built-in mock** (mock is fine for demos only).

### Payments (when you charge customers)

| Provider | Variables | Signup | Used for |
|----------|-----------|--------|----------|
| **Stripe** | `STRIPE_SECRET_KEY` | [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) | Checkout for credit top-ups |
| Stripe webhook | `STRIPE_WEBHOOK_SECRET` | Stripe → Developers → Webhooks | Confirm payments; endpoint `POST /billing/webhook` |
| Plan prices | `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO` | Stripe Products → Price IDs | Subscription checkout for Starter / Pro |

**Webhook events to enable:** `checkout.session.completed`  
**Webhook URL:** `https://api.yourdomain.com/billing/webhook`

Without Stripe: top-ups/plans apply instantly in **dev mode** (not for real money).

### Outbound channels (agent deliverables)

| Provider | Variables | Signup | Used for |
|----------|-----------|--------|----------|
| **Resend** | `RESEND_API_KEY`, `RESEND_FROM` | [resend.com](https://resend.com) | Email results from agents (`notify_email`) |
| **Twilio** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | [console.twilio.com](https://console.twilio.com) | SMS + voice (`notify_sms` / calls) |

Verify your sending domain in Resend and use an E.164 number on Twilio (e.g. `+447...`).

### Optional / later

| Need | Suggestion |
|------|------------|
| Postgres | Managed: Neon, Supabase, RDS, DigitalOcean |
| Object storage (files/attachments) | S3 / R2 — not wired yet |
| Google Business (reviews agent) | Google Business Profile API — not wired yet |
| Embeddable chat widget | Placeholder in Settings; separate frontend build later |
| Error tracking | Sentry |
| Email login magic links | Resend + custom flow |

---

## Environment variables (backend/.env)

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` or `production` |
| `JWT_SECRET` | JWT signing key (required in production) |
| `FRONTEND_URL` | Frontend origin for redirects |
| `CORS_ORIGINS` | Comma-separated origins |
| `DATABASE_URL` | SQLAlchemy URL (SQLite or Postgres) |
| `ANTHROPIC_API_KEY` | Claude API |
| `XAI_API_KEY` / `XAI_MODEL_*` | Grok via xAI API |
| `OLLAMA_URL` / `OLLAMA_MODEL_*` | Self-hosted models |
| `STRIPE_*` | Payments |
| `RESEND_*` | Email |
| `TWILIO_*` | SMS / voice |

Check live config in the app: **Settings → Integration status** (or `GET /system/status` with a JWT).

---

## How each integration behaves

- **LLM** (`app/llm.py`): Claude → Anthropic; Grok → xAI; VPS models → Ollama; then mock.
- **Stripe** (`app/routers/billing.py`): Checkout when key present; else instant dev credit/plan.
- **Agents** (`app/routers/agents.py` + `channels.py`): Task runs on agent model, bills tokens, optional email/SMS delivery.
- **Credits**: Insufficient balance returns HTTP **402** (and WS chat error) until top-up.
- **Plan agent caps**: starter 2, pro 10, pay-as-you-go 50 (soft product limits).

## Deploying on your VPS

1. Backend: `APP_ENV=production` + strong `JWT_SECRET`, then  
   `uvicorn app.main:app --host 0.0.0.0 --port 8000` behind nginx (proxy `/` and WebSocket upgrade for `/ws/`, `/agents/ws`, `/billing/ws/tokens`).
2. Frontend: `VITE_API_URL=https://api.yourdomain.com npm run build`, serve `dist/`.
3. Prefer Postgres: set `DATABASE_URL=postgresql+psycopg2://...` and `pip install psycopg2-binary`.
4. Stripe webhook → `https://api.yourdomain.com/billing/webhook`.

## What’s new in v1.1

- Integration status API + Settings UI
- Production-safe JWT / `APP_ENV` guard
- `DATABASE_URL` (SQLite or Postgres)
- Credit checks before chat/tasks
- Task **result** storage + failed status
- REST chat fallback (`POST /conversations/messages`)
- Profile update (`PATCH /auth/me`)
- Plan-based agent limits
