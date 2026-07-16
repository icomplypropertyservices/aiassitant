# Production APIs & environment checklist

Set these in **Vercel → Project → Settings → Environment Variables** (Production + Preview as needed).

## Required (app will not run safely without these)

| Variable | Get it from | Purpose |
|----------|-------------|---------|
| `APP_ENV` | set to `production` | Enables prod locks (no demo admin, no free Stripe, strict JWT) |
| `JWT_SECRET` | `openssl rand -hex 32` | Signs login sessions (≥32 random chars) |
| `DATABASE_URL` | [Neon](https://neon.tech) / Supabase / Vercel Postgres | Postgres URL, e.g. `postgresql+psycopg2://user:pass@host/db?sslmode=require` |
| `FRONTEND_URL` | your Vercel URL | Redirects after Stripe checkout, e.g. `https://your-app.vercel.app` |
| `CORS_ORIGINS` | same origin(s) | e.g. `https://your-app.vercel.app` (comma-separated if multi) |

**Recommended**

| Variable | Purpose |
|----------|---------|
| `ENCRYPTION_KEY` | Fernet key for user API keys / integration secrets (or long secret ≥16 chars). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

---

## LLM (pick at least one for real AI — otherwise mock/Ollama)

| Provider | Variables | Where to get keys |
|----------|-----------|-------------------|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| **xAI (Grok)** | `XAI_API_KEY` (optional `XAI_BASE_URL`, `XAI_MODEL_FAST`, `XAI_MODEL_QUALITY`) | https://console.x.ai/ |
| **Ollama (self-hosted)** | `OLLAMA_URL`, `OLLAMA_MODEL_*` | https://ollama.com on your VPS |

Users can also paste their own keys in **Settings → API keys** (encrypted).

---

## Payments (required to charge customers)

### Card (Stripe) — sandbox then live

| Variable | Purpose | Where |
|----------|---------|--------|
| `STRIPE_SECRET_KEY` | Checkout | **Test mode:** https://dashboard.stripe.com/test/apikeys (`sk_test_…`) |
| `STRIPE_WEBHOOK_SECRET` | Confirm payments (optional in sandbox) | Stripe → Developers → Webhooks → `POST https://your-app.vercel.app/api/billing/webhook` |
| `STRIPE_PRICE_STARTER` | Optional Price ID | Product → Price (if empty, app uses inline monthly price) |
| `STRIPE_PRICE_PRO` | Optional Price ID | same |
| `STRIPE_PRICE_BUSINESS` | Optional Price ID | same |

**Sandbox testing**
1. Put `STRIPE_SECRET_KEY=sk_test_…` in Vercel Production env.
2. Redeploy.
3. Billing → “Top up with card (test)” or Subscribe with card.
4. Pay with `4242 4242 4242 4242`, any future expiry/CVC.
5. Redirect includes `session_id` → app calls `/billing/checkout/confirm` (no webhook required).

**Webhook events (recommended for live):** `checkout.session.completed`

### Crypto (ETH / SOL / XRP — self-custody)

| Variable | Purpose |
|----------|---------|
| `CRYPTO_ETH_ADDRESS` | Ethereum mainnet receive address |
| `CRYPTO_SOL_ADDRESS` | Solana mainnet receive address |
| `CRYPTO_XRP_ADDRESS` | XRP Ledger receive address |
| `CRYPTO_ETH_RPC` | Optional ETH JSON-RPC (default publicnode) |
| `CRYPTO_SOL_RPC` | Optional Solana RPC |
| `CRYPTO_XRP_RPC` | Optional XRPL HTTP endpoint |
| `CRYPTO_INVOICE_TTL_MIN` | Invoice lifetime minutes (default 60) |

**Flow:** user creates invoice → sends exact amount (XRP requires destination tag) → pastes tx hash → API verifies on-chain → plan / credits unlocked.

**Never put private keys in env.** Only public receive addresses.

Without Stripe **and** without crypto addresses in production: paid plans / top-ups return **503**.

---

## Outbound channels (optional)

| Provider | Variables | Where |
|----------|-----------|--------|
| **Resend (email)** | `RESEND_API_KEY`, `RESEND_FROM` | https://resend.com |
| **Twilio (SMS/voice)** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | https://console.twilio.com |

---

## Connected apps / OAuth (optional — users can use API keys in Settings)

Only needed for **one-click OAuth** (otherwise connect with tokens in the UI):

| App | Env vars | Docs |
|-----|----------|------|
| Shopify | `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` | https://shopify.dev |
| Google (Gmail/Sheets/Business) | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | https://console.cloud.google.com |
| Slack | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` | https://api.slack.com/apps |
| HubSpot | `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET` | https://developers.hubspot.com |
| Notion | `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET` | https://developers.notion.com |
| Dropbox | `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` | https://www.dropbox.com/developers |

OAuth redirect (if used):

| Variable | Example |
|----------|---------|
| `OAUTH_REDIRECT_URI` or `API_PUBLIC_URL` | `https://your-app.vercel.app/api/integrations/oauth/callback` |

---

## Storage for training files (recommended in production)

Local disk on Vercel is ephemeral. Prefer:

| Backend | How |
|---------|-----|
| **Google Cloud Storage** | Connect in Settings (bucket + service account JSON or OAuth token) |
| **Dropbox** | Connect access token in Settings |

Optional platform env: `GCS_BUCKET`, `UPLOAD_ROOT` (local/VPS only).

---

## Native / iOS (if shipping App Store)

| Variable | Purpose |
|----------|---------|
| `VITE_PROD_API_URL` or `VITE_API_URL` | Absolute API, e.g. `https://your-app.vercel.app/api` |
| `VITE_NATIVE=1` | Capacitor build flag |

---

## Minimum “go live” set

```text
APP_ENV=production
JWT_SECRET=<openssl rand -hex 32>
DATABASE_URL=postgresql+psycopg2://...
FRONTEND_URL=https://your-app.vercel.app
CORS_ORIGINS=https://your-app.vercel.app
ENCRYPTION_KEY=<fernet key>
ANTHROPIC_API_KEY=...   # and/or XAI_API_KEY
STRIPE_SECRET_KEY=...          # optional if using crypto only
STRIPE_WEBHOOK_SECRET=...
STRIPE_PRICE_STARTER=...
STRIPE_PRICE_PRO=...
STRIPE_PRICE_BUSINESS=...
CRYPTO_ETH_ADDRESS=0x...       # optional if using Stripe only
CRYPTO_SOL_ADDRESS=...
CRYPTO_XRP_ADDRESS=r...
```

Then: create a **real admin user** via register + promote in DB (or one-time bootstrap script). Do **not** rely on `admin@local` in production (demo seed is disabled when `APP_ENV=production`).
