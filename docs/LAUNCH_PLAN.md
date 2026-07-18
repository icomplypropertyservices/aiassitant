# Plans for launch — AI Assistant

**Pre-order (now → 26 July 2026):** 10% off paid plans + early access. Public launch **27 July 2026**.
- Grok: **API only**
- Claude: **Coming soon**
- VPS: **Coming soon** (small models only when live)
- Payments: **Stripe + crypto** (ETH / SOL / BTC / XRP) ready for pre-order checkout

**Product status (today):** live on Vercel · production API · Stripe **sandbox** · crypto · marketing site · mobile shells ready.

**Target host (paths — no subdomains)**

| URL | Role |
|-----|------|
| `aibusinessagent.xyz/` | Marketing / landing (`website/`) |
| `aibusinessagent.xyz/agents` | Product app SPA |
| `aibusinessagent.xyz/api` | Product API |
| `aibusinessagent.xyz/bay` | AgentBay marketplace |

Until DNS is wired, app may still be at `https://aiassitant-nu.vercel.app` (then use `/agents` after path deploy).

---

## 1. Public subscription plans (what customers buy)

| Plan | Price | Included tokens / mo | Agents | Companies | Projects | Payment |
|------|------:|---------------------:|-------:|----------:|---------:|---------|
| **Free trial** | $0 | 50,000 | 3 | 1 | 2 | None |
| **Starter** | **$39**/mo | 2,000,000 | 5 | 1 | 10 | Card or crypto |
| **Pro** ⭐ | **$99**/mo | 10,000,000 | 20 | 3 | 50 | Card or crypto |
| **Business** | **$249**/mo | 40,000,000 | 100 | 15 | 200 | Card or crypto |

**Billing model**

- Plan includes a monthly **token pool** (best for VPS/Qwen).
- **Premium Grok / Claude** always use the **credit wallet**.
- After the pool is used, further usage draws **credits**.
- Payments: **Stripe card** (sandbox now) + **crypto ETH / SOL / XRP**.

**Launch recommendation**

| Audience | Lead with |
|----------|-----------|
| Soft launch / invitees | Free trial → Pro |
| Freelancers / trades | Starter |
| Agencies | Business |

Source of truth in code: `backend/app/plans.py` · shown on login, subscribe, billing, and `website/pricing.html`.

---

## 2. Launch phases

### Phase A — Soft launch (now → DNS live)

**Goal:** real users on production; no live card money yet.

- [x] App deployed (production)
- [x] Auth, workspace, agents, chat (xAI)
- [x] Plans + token meter
- [x] Stripe **test** keys (`sk_test_…`) — Checkout works
- [x] Crypto UI (placeholder receive addresses)
- [x] Marketing site folder (`website/`)
- [x] iOS + Android Capacitor projects
- [ ] Attach domain **aibusinessagent.xyz** to the monorepo Vercel project
- [ ] Set app env:
  - `FRONTEND_URL=https://aibusinessagent.xyz/agents`
  - `CORS_ORIGINS=https://aibusinessagent.xyz,https://www.aibusinessagent.xyz`
  - `AGENTBAY_URL=https://aibusinessagent.xyz/bay`
- [ ] Replace crypto placeholders with real wallets (if offering crypto at soft launch)
- [ ] Create 1–2 **reviewer / demo** accounts (not personal admin)

**Soft-launch messaging:** “Early access — payments in test mode until go-live.”

---

### Phase B — Public web launch

**Goal:** take real money; market the root domain.

1. **Stripe live**
   - Switch Vercel `STRIPE_SECRET_KEY` → `sk_live_…`
   - Add webhook: `https://aibusinessagent.xyz/api/billing/webhook`
   - Event: `checkout.session.completed`
   - Set `STRIPE_WEBHOOK_SECRET`
2. **Email**
   - Resend (or similar): `RESEND_API_KEY`, verified domain on `aibusinessagent.xyz`
3. **Legal / store pages**
   - Privacy + support already on site; keep in sync with app
4. **Smoke test**
   - Register → trial → paid plan (real $1 top-up or Starter) → chat → cancel test
5. **Announce**
   - Landing CTAs → `aibusinessagent.xyz/agents/login`
   - Optional: waitlist / “Start free trial”

---

### Phase C — App Store + Play Store

**Goal:** mobile listed; billing stays multi-platform safe.

| Step | iOS | Android |
|------|-----|---------|
| Build | `npm run build:ios` (Mac) | `npm run build:android` |
| Test | TestFlight | Play internal testing |
| Payments | Web billing (already routed off-native) | same |
| Listing URLs | `…/privacy.html` + `…/support.html` (+ terms) | same |
| Bundle ID | `com.icomply.aibusinessassistant` | same |

Details: `docs/STORE_READY.md`, `docs/APP_STORE_IOS.md`.

**Guideline note:** digital goods on iOS — keep Subscribe/Top-up opening the **website** for multi-platform SaaS (already implemented for native).

---

## 3. Go-live checklist (copy this)

### Domains (path layout — no subdomains)
- [ ] `aibusinessagent.xyz` (+ www → apex) → monorepo Vercel project
- [ ] `https://aibusinessagent.xyz/` — marketing (`website/`)
- [ ] `https://aibusinessagent.xyz/agents` — product SPA
- [ ] `https://aibusinessagent.xyz/api` — product API (`/api/health` OK)
- [ ] `https://aibusinessagent.xyz/bay` — AgentBay marketplace
- [ ] SSL auto (Vercel)

### Legal / store URLs (public)
- [ ] Privacy: `https://aibusinessagent.xyz/privacy.html`
- [ ] Terms: `https://aibusinessagent.xyz/terms.html`
- [ ] Support: `https://aibusinessagent.xyz/support.html`
- [ ] Store listings + app review notes use these URLs only (not `*.vercel.app`)

### Env (app project)
- [ ] `APP_ENV=production` (demo `admin@local` seed **disabled**)
- [ ] `JWT_SECRET` / `ENCRYPTION_KEY` / `DATABASE_URL`
- [ ] `FRONTEND_URL=https://aibusinessagent.xyz/agents`
- [ ] `CORS_ORIGINS=https://aibusinessagent.xyz,https://www.aibusinessagent.xyz`
- [ ] `AGENTBAY_URL=https://aibusinessagent.xyz/bay` (if used)
- [ ] `XAI_API_KEY` (and/or Anthropic)
- [ ] `STRIPE_SECRET_KEY` live + webhook `https://aibusinessagent.xyz/api/billing/webhook`
- [ ] Optional: `CRYPTO_*_ADDRESS` real wallets

### Product QA
- [ ] Sign up / login (real account — not `admin@local`)
- [ ] Trial activation
- [ ] Card checkout (live)
- [ ] Crypto invoice (optional)
- [ ] Chat reply (xAI)
- [ ] Create company / project / agent
- [ ] Token meter updates
- [ ] Smoke: `/agents` + `/api/health` + legal pages load

### Launch day
- [ ] Status check `https://aibusinessagent.xyz/api/health`
- [ ] No production demo-admin / `admin@local` credentials in docs or review notes
- [ ] Support email monitored
- [ ] Stripe dashboard open for first payments

---

## 4. What “launch” does **not** require on day 1

- Perfect crypto (can ship card-only first)
- App Store approval (web can launch first)
- All integrations (Shopify etc. can be “connect later”)
- VPS/Ollama (xAI alone is enough for cloud launch)

---

## 5. Suggested public plan copy (one-liners)

| Plan | One-liner |
|------|-----------|
| Trial | Try AI Assistant free — 50k tokens to prove the workflow. |
| Starter | Serious volume for freelancers and trades at $39/mo. |
| Pro | The default team plan — 10M tokens and multi-company. |
| Business | Agency scale — 40M tokens and 100 agents. |

---

## 6. Immediate next actions (recommended order)

1. Attach **aibusinessagent.xyz** to the monorepo project; confirm `/`, `/agents`, `/api/health`  
2. Set `FRONTEND_URL` + `CORS_ORIGINS` for path layout; redeploy  
3. Soft-launch to 5–10 users on trial (Stripe still test if you want)  
4. Ship AgentBay under `/bay` (build + optional API proxy)  
5. Submit TestFlight / Play internal builds  

When you want execution on a step (e.g. “deploy website project” or “switch Stripe live”), say which step and we’ll do it.
