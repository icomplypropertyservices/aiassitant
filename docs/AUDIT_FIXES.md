# Audit fixes — assigned checklist

**Status policy:** Status is set by master after **code evidence** (grep/read). Values: `PASS` | `FAIL` | `PARTIAL` | `assigned` (not yet reviewed).

**Last master review:** 2026-07-17 (A20) — see [LAUNCH_100.md](./LAUNCH_100.md).

**Domain path layout (no subdomains)** — see also [DOMAINS.md](./DOMAINS.md)

| URL | Purpose |
|-----|---------|
| `https://aibusinessagent.xyz/` | Marketing / landing (`website/`) |
| `https://aibusinessagent.xyz/agents` | Product SPA (`frontend/`, Vite `base: /agents/`) |
| `https://aibusinessagent.xyz/api` | Product API (`api/index.py` + `backend/`) |
| `https://aibusinessagent.xyz/bay` | AgentBay marketplace SPA |
| `https://aibusinessagent.xyz/bay/api` | AgentBay API (proxy or co-deploy) |

```
aibusinessagent.xyz
├── /                 marketing site
├── /agents/*         AI Business Assistant UI
├── /api/*            Assistant API (Stripe, auth, chat, …)
├── /bay/*            AgentBay UI
└── /bay/api/*        AgentBay API
```

Env anchors for path layout:

- `FRONTEND_URL=https://aibusinessagent.xyz/agents`
- `CORS_ORIGINS=https://aibusinessagent.xyz,https://www.aibusinessagent.xyz`
- `AGENTBAY_URL` / `AGENTBAY_PUBLIC_URL=https://aibusinessagent.xyz/bay`
- Stripe webhook: `https://aibusinessagent.xyz/api/billing/webhook`

---

## Sorted checklist (P0 → P1 → P2)

| ID | Finding | Owner worker | Expected fix | Verification step | Status | Evidence |
|----|---------|--------------|--------------|-------------------|--------|----------|
| P0-1 | Free PAYG / welcome wallet credits can mint in production | W1 | Block free `pay_as_you_go` activation in prod (402); never add welcome credits when `IS_PRODUCTION`; free top-up only in non-prod | Register → try `POST /billing/plan` `pay_as_you_go` on prod → 402; balance credits stay 0 without Stripe/crypto | **PASS** | `billing.py` PAYG 402 in prod; welcome credits gated `not IS_PRODUCTION`; top-up free path 503 in prod |
| P0-2 | Trial can be re-activated / token pool refilled indefinitely | W2 | One-shot trial: 14-day `subscription_expires_at`; re-POST does not reset pool; expired/prior trial → 402 “choose paid plan” | Activate trial once → re-POST trial → `already_active` or 402; after expiry → 402; paid plan clears trial expiry | **PASS** | `_trial_live` / `_had_or_has_trial`; re-POST returns `already_active` without pool reset; ended → 402 `TRIAL_ENDED_MSG` |
| P0-3 | `seed-starter-team` ignores plan agent caps | W3 | Cap creations to `plan_limits(...).agents`; need ≥3 free slots; admin bypass only for staff | On trial/starter, seed until cap → 400 or partial stop; agent count ≤ plan max | **PASS** | `agents.py` `seed-starter-team` uses `max_agents`, stops when full, returns plan limit fields |
| P0-4 | `seed-professional-40` ignores plan agent caps | W4 | Same plan cap as starter seed; stop creating when full; clear response fields (`plan_capped`, `max_agents`) | Call seed-40 on capped plan → no over-create; message mentions limit | **PASS** | `seed-professional-40` returns `plan_capped`, `max_agents` |
| P0-5 | Live Stripe path still allows free plan mint without payment rails | W1 | Production: paid plans require Stripe Checkout or crypto; no free `_activate_plan` for `requires_payment` | With Stripe unset + crypto off → paid plan 503/402; with Stripe → `checkout_url` returned | **PASS** | `needs_payment and IS_PRODUCTION` → 402 crypto msg or 503; Checkout when Stripe present |
| P0-6 | Platform LLM may use Super/CLI JWT by default (multi-tenant risk) | W18 | `XAI_USE_JWT_ONLY` default **false** in production (prefer `XAI_API_KEY`); true in local dev unless env override | Inspect `config.XAI_USE_JWT_ONLY` under `APP_ENV=production` without env → false; chat uses API key path | **PASS** | `config.py`: default `XAI_USE_JWT_ONLY = not IS_PRODUCTION`; `get_grok_token` prefers API key when not JWT-only |
| P1-1 | OpenAPI /docs exposed in production | W5 | Disable `docs_url`, `redoc_url`, `openapi_url` when `IS_PRODUCTION` | `GET /docs` and `/openapi.json` → 404 on prod | **PASS** | `main.py` sets all three to `None` when `IS_PRODUCTION` |
| P1-2 | Cron `/ops/autonomy/tick-all` under-authenticated | W6 | Require `X-Cron-Secret` or `Authorization: Bearer <CRON_SECRET>` matching `CRON_SECRET`, or admin JWT; prod without secret → 503 for non-admin | Hit tick-all without secret → 403/503; with correct secret → 200 | **PASS** | `ops.py` `autonomy_tick_all` enforces cron secret or admin; 503 if prod + no secret |
| P1-3 | Weak passwords allowed on register/profile | W7 | Min length 8 + at least one letter + one digit | Register with `password` / `abcdefg` → 400; valid password succeeds | **PASS** | `auth.py` `_validate_password` on register + patch `/me` |
| P1-4 | JWT lifetime too long (e.g. 7d) / no revoke notes | W8 | Session JWT ~48h; document that logout is client-side and password change does not revoke old tokens | Decode token `exp` ≈ 48h; password change still documented as non-revoking | **PASS** | `create_token` `timedelta(hours=48)`; password change bumps `token_version` and invalidates old JWTs (stronger than original note) |
| P1-5 | Auth rate limits too loose / undocumented serverless gap | W15 | Tighten login/register limits; document per-process (not global) limiter on Vercel | Burst login → 429; read `rate_limit.py` docstring for multi-instance caveat | **PASS** | `rate_limit.py` module doc + Redis optional; register 5/300s IP; login 20/60s + email 10/300s |
| P1-6 | Crypto invoices accept 0-confirmation / unconfirmed txs | W11 | Require minimum confirmations (e.g. ETH ≥2, BTC confirmed/conf≥1) before fulfill | Submit unconfirmed tx → reject; confirmed → credits/plan applied | **PASS** | `crypto_payments.py` ETH conf≥2; BTC confirmed or conf≥1 |
| P1-7 | No public Terms of Service | W10 | Ship `website/terms.html` (SaaS ToS, billing, AI disclaimer, AgentBay, Ireland contact) | Open `https://aibusinessagent.xyz/terms.html` (or local website) + footer Terms link | **PASS** | `website/terms.html` present with privacy cross-link |
| P1-8 | Legal footer incomplete / broken Privacy↔Terms links | W19 | Marketing footer Legal: Privacy, Terms, Support; path-aware `/agents` and `/bay` CTAs | Footer on all marketing pages links to `/privacy.html` and `/terms.html` | **PASS** | `website/js/main.js` Legal block + APP_URL/BAY_URL CTAs |
| P1-9 | Demo admin credentials documented as production login | W17 | Quarantine `admin@local` / `admin123` as **local dev only**; store/review docs require dedicated reviewer account | README + STORE_READY + APP_STORE_IOS: no prod demo login; seed disabled when `APP_ENV=production` | **PASS** | `main.py` `allow_demo = not IS_PRODUCTION`; README/STORE_READY/APP_STORE_IOS warn local-only |
| P2-1 | Missing security response headers | W9 | Vercel headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP as appropriate | `curl -I` production → expected headers present | **PASS** | Root `vercel.json` `headers` on `/(.*)` include all listed |
| P2-2 | Premium skill charges swallowed (`except: pass`) → free run | W12 | `_charge_premium` fail-closed: if `charge_event` and `charge_usage` both fail, re-raise; skill returns error | Force billing failure → skill `ok: false`; no unpaid send/media | **PASS** | `agent_skills._charge_premium` re-raises `RuntimeError` after both paths fail |
| P2-3 | Weak / empty `AGENTBAY_BRIDGE_SECRET` usable in prod | W13 | Clear or reject weak bridge secrets when production | Prod with empty/weak secret → bridge disabled or reject; strong secret works | **PASS** | `config.py` prod weak/empty → `AGENTBAY_BRIDGE_SECRET = ""` |
| P2-4 | User webhooks can target SSRF (localhost, metadata, private IPs) | W14 | `validate_webhook_url` blocks loopback, link-local, private ranges, cloud metadata; use on probes + actions | Connect Zapier/Discord webhook with `http://127.0.0.1/...` → error | **PASS** | `integration_actions.validate_webhook_url`; used in probes + actions |
| P2-5 | Plan copy exposes vendor names (Claude/Grok/Qwen/RunPod) | W16 | Customer-facing plan strings use managed/premium / included pool only | Grep `plans.py` for vendor brands → no matches in public features | **PASS** | `plans.py` provider-neutral; no Claude/Grok/Qwen/RunPod in features |

---

## Ops / follow-ups (not owned by W1–W19 code workers)

These are deploy and product backlog items tracked for master. **Ops status stays open until every Done criterion is proven on production** — repo config, Preview-only env, or “documented” is not enough. Do **not** mark Done from assumption.

Env / path docs: [PRODUCTION_APIS.md](./PRODUCTION_APIS.md) · [DOMAINS.md](./DOMAINS.md).

| ID | Item | Priority | Notes | **Done criteria** (all required) | Ops status |
|----|------|----------|-------|----------------------------------|------------|
| N1 | Deploy monorepo with path layout + audit code | P0 ops | Vercel root + `vercel.json` | (1) Production deploy from monorepo root succeeds. (2) `https://aibusinessagent.xyz/` = marketing. (3) `/agents` = SPA. (4) `/api/*` = FastAPI. (5) Current audit branch is what Production runs. | **open** (repo config exists; live attach not verified here) |
| N2 | Set `CRON_SECRET` and confirm daily autonomy tick | P1 | Cron path `/api/ops/autonomy/tick-all` | (1) `CRON_SECRET` in **Vercel Production** (non-empty, strong). (2) tick-all without secret → 403/503. (3) With `X-Cron-Secret` or `Authorization: Bearer <CRON_SECRET>` → 200. (4) Vercel Cron history shows a successful scheduled (or manual prod) run. | **open** (endpoint auth in code; secret is env) |
| N3 | Strong `AGENTBAY_BRIDGE_SECRET` if using `/bay` | P1 | | **If `/bay` live:** Production secret ≥32 random chars; valid secret works; empty/weak rejected. **If bay not shipped:** master notes N/A — do not mark Done while public bay has no strong secret. | **open** |
| N4 | Set `XAI_API_KEY`; remove personal Super JWT from prod env | P0 ops | Aligns with W18 | (1) Business `XAI_API_KEY` in Production (or proven Anthropic/RunPod-only path). (2) Multi-tenant chat does not depend on personal Super JWT. (3) Prod chat returns real model output. (4) `XAI_USE_JWT_ONLY` not forced true in prod. | **open** |
| N5 | Attach `aibusinessagent.xyz` + `FRONTEND_URL` / `CORS_ORIGINS` | P0 ops | Path layout | (1) Domain + www→apex on Production. (2) `FRONTEND_URL=https://aibusinessagent.xyz/agents` (must include **`/agents`**). (3) `CORS_ORIGINS` includes apex (+ www if used). (4) Smoke `/`, `/agents`, `/api/health` 200 on custom domain. (5) Stripe return URLs under `/agents`. | **open** |
| N6 | Redis/Upstash global rate limits | P1 | Extends W15 — code supports Redis | (1) `REDIS_URL` or `UPSTASH_REDIS_URL` in Production. (2) No permanent connect-fail fallback in steady state. (3) Burst auth → 429 across instances. (4) Documented in PRODUCTION_APIS. | **open** (code supports Redis; prod URL not verified) |
| N7 | Password reset + email verification | P1 | Resend + `FRONTEND_URL` | (1) Deployed routes: forgot/reset/verify (e.g. `/auth/forgot-password`, `/auth/reset-password`, verify). (2) `RESEND_API_KEY` + verified `RESEND_FROM` on domain. (3) Real inbox receives mail; link base = `FRONTEND_URL` (`…/agents/…`). (4) Reset/verify succeeds once; token not reusable. (5) Missing Resend fails closed (no fake “sent” in prod). | **open** (code may exist in repo; **prod Resend + smoke not verified** — do not mark Done until inbox test on Production) |
| N8 | Account delete / export API | P1 | Store / GDPR | (1) Authenticated data export works on Production. (2) Account delete (or documented schedule-delete) works. (3) Store review can cite live URL/API. | **open** (treat missing product as not done; verify before any PASS) |
| N9 | JWT revoke on password change | P2 | Extends W8 | (1) Password change bumps server-side token version / denylist. (2) Prior JWT → 401 after change on Production. (3) Support docs mention behavior. | **open** (code may implement `token_version`; **not Done until prod smoke proves old JWT rejected**) |
| N10 | WS auth token not in query string | P2 | Prefer first-message auth | (1) Primary client path uses header/subprotocol/first-message auth, not JWT in query. (2) Prod preferred path exercised. (3) Legacy `?token=` only if explicitly deprecated and not required for app. | **open** (preferred path may exist in code; confirm prod client does not rely on query token) |
| N11 | Stripe Price IDs + Customer Portal | P2 | Webhook on apex | (1) Live webhook URL `https://aibusinessagent.xyz/api/billing/webhook` healthy in Stripe. (2) `STRIPE_WEBHOOK_SECRET` matches. (3) Portal reachable from Billing if claimed shipped. (4) Price IDs set if using fixed Prices. | **open** (helpers may exist; Price IDs / live webhook not verified → not Done) |
| N12 | Marketing HTML vendor names (features/index) | P3 | Cosmetic; W16 = `plans.py` only | (1) `website/features.html` + `index.html` match brand rules on vendor names. (2) Spot-check after deploy. | **open** |

**How to flip Ops status:** only master/ops sets **open → done** after Done criteria are checked against **production**. Partial → stay **open**. Never set **done** only because the row is documented or code exists on a branch.

---

## Worker index (W1–W20)

| Worker | Owns |
|--------|------|
| W1 | P0-1, P0-5 — free credits / free paid activation in production |
| W2 | P0-2 — trial one-shot + 14d expiry |
| W3 | P0-3 — seed-starter plan caps |
| W4 | P0-4 — seed-40 plan caps |
| W5 | P1-1 — hide OpenAPI in production |
| W6 | P1-2 — cron tick-all auth |
| W7 | P1-3 — password strength |
| W8 | P1-4 — JWT TTL |
| W9 | P2-1 — security headers |
| W10 | P1-7 — Terms of Service page |
| W11 | P1-6 — crypto confirmation thresholds |
| W12 | P2-2 — premium charge fail-closed |
| W13 | P2-3 — AgentBay bridge secret |
| W14 | P2-4 — webhook SSRF |
| W15 | P1-5 — rate limit harden + docs |
| W16 | P2-5 — provider-neutral plan copy |
| W17 | P1-9 — strip demo admin from prod-facing docs |
| W18 | P0-6 — XAI API key prod default |
| W19 | P1-8 — legal footer / Privacy↔Terms |
| W20 | This checklist document |

---

## How master should update this file

1. After verifying each worker’s code change, set **Status** to `PASS` or `FAIL` (or `PARTIAL` with note). Never leave ambiguous once reviewed.
2. Prefer file path / short note in **Evidence**.
3. Keep **N\*** ops rows separate from code **Status**.
4. Soft-launch gate: all **P0** code `PASS` + **N1–N5** done + smoke test on `aibusinessagent.xyz/agents` and `/api/health`.
5. Public/EU launch: also **N7–N8** (GDPR + reset/verify).
