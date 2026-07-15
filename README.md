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

## Deploy complete app on Vercel (frontend + API)

This monorepo deploys **both** the React SPA and the FastAPI backend on Vercel:

- **Static:** `frontend/dist` (Vite)
- **Serverless:** `api/index.py` → FastAPI (`backend/app`)

Chat/agent live WebSockets are **not reliable** on Vercel serverless; the UI already **falls back to REST** so the product still works.

### 1. Create a Postgres database (required)

SQLite does not survive serverless. Use free [Neon](https://neon.tech), Supabase, or Vercel Postgres.

Copy the connection string, e.g.:

`postgresql+psycopg2://user:pass@host/db?sslmode=require`

### 2. Vercel project (GitHub)

1. Import **https://github.com/icomplypropertyservices/aiassitant**
2. Root directory: **repository root** (uses `vercel.json`)
3. Add **Environment Variables** (Production + Preview):

| Variable | Required | Example |
|----------|----------|---------|
| `APP_ENV` | yes | `production` |
| `JWT_SECRET` | yes | long random (`openssl rand -hex 32`) |
| `ENCRYPTION_KEY` | recommended | Fernet key or long secret |
| `DATABASE_URL` | yes | Postgres URL (see above) |
| `FRONTEND_URL` | yes | `https://your-app.vercel.app` |
| `CORS_ORIGINS` | yes | `https://your-app.vercel.app` |
| `VITE_API_URL` | **leave empty** for same-origin full stack | (empty) |
| `ANTHROPIC_API_KEY` / `XAI_API_KEY` | optional | platform LLM keys |
| `STRIPE_*` | optional | payments |

4. Deploy. First request runs DB `create_all` + seed (admin user).

**Demo login after deploy:** `admin@local` / `admin123` — change immediately.

### 3. How routing works

| Request | Handled by |
|---------|------------|
| `/`, `/login`, `/agents/…` | Static SPA |
| `/auth/*`, `/agents/*`, `/billing/*`, `/org/*`, `/keys/*`, … | Python `api/index.py` (FastAPI) |
| `/assets/*` | Static JS/CSS |

### 4. Limits on Vercel

| Topic | Notes |
|-------|--------|
| Function timeout | `maxDuration: 60` (Pro); Hobby may be lower — long LLM calls can time out |
| WebSockets | Prefer REST chat (auto-fallback) |
| Cold starts | First request after idle is slower |
| Background jobs | Agent tasks are **awaited** on serverless so they finish before freeze |

### 5. Local full stack (unchanged)

```bash
# terminal 1
cd backend && .venv\Scripts\activate && uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && npm run dev
```

### Architecture (Vercel complete)

```
Browser
   │  same origin
   ▼
Vercel ──► SPA (frontend/dist)
       └──► Serverless FastAPI (api/index.py → backend)
                  │
                  ▼
             Postgres (Neon) + LLM APIs
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
