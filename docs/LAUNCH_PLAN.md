# Plans for launch — AI Assistant

**Product status (today):** live on Vercel · production API · Stripe **sandbox** · crypto placeholders · marketing site in `website/` · mobile shells ready.

**Target hosts**

| Host | Role |
|------|------|
| `aiassistant.xyz` | Marketing / landing (`website/`) |
| `app.aiassistant.xyz` | Product app + API |

Until DNS is wired, app remains at `https://aiassitant-nu.vercel.app`.

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
- [ ] Deploy `website/` to Vercel → domain **aiassistant.xyz**
- [ ] Point **app.aiassistant.xyz** at the app project
- [ ] Set app env:
  - `FRONTEND_URL=https://app.aiassistant.xyz`
  - `CORS_ORIGINS=https://app.aiassistant.xyz,https://aiassistant.xyz`
- [ ] Replace crypto placeholders with real wallets (if offering crypto at soft launch)
- [ ] Create 1–2 **reviewer / demo** accounts (not personal admin)

**Soft-launch messaging:** “Early access — payments in test mode until go-live.”

---

### Phase B — Public web launch

**Goal:** take real money; market the root domain.

1. **Stripe live**
   - Switch Vercel `STRIPE_SECRET_KEY` → `sk_live_…`
   - Add webhook: `https://app.aiassistant.xyz/api/billing/webhook`
   - Event: `checkout.session.completed`
   - Set `STRIPE_WEBHOOK_SECRET`
2. **Email**
   - Resend (or similar): `RESEND_API_KEY`, verified domain on `aiassistant.xyz`
3. **Legal / store pages**
   - Privacy + support already on site; keep in sync with app
4. **Smoke test**
   - Register → trial → paid plan (real $1 top-up or Starter) → chat → cancel test
5. **Announce**
   - Landing CTAs → `app.aiassistant.xyz/login`
   - Optional: waitlist / “Start free trial”

---

### Phase C — App Store + Play Store

**Goal:** mobile listed; billing stays multi-platform safe.

| Step | iOS | Android |
|------|-----|---------|
| Build | `npm run build:ios` (Mac) | `npm run build:android` |
| Test | TestFlight | Play internal testing |
| Payments | Web billing (already routed off-native) | same |
| Listing URLs | privacy + support | same |
| Bundle ID | `com.icomply.aibusinessassistant` | same |

Details: `docs/STORE_READY.md`, `docs/APP_STORE_IOS.md`.

**Guideline note:** digital goods on iOS — keep Subscribe/Top-up opening the **website** for multi-platform SaaS (already implemented for native).

---

## 3. Go-live checklist (copy this)

### Domains
- [ ] `aiassistant.xyz` → marketing Vercel project (`website/`)
- [ ] `app.aiassistant.xyz` → app Vercel project
- [ ] SSL auto on both

### Env (app project)
- [ ] `APP_ENV=production`
- [ ] `JWT_SECRET` / `ENCRYPTION_KEY` / `DATABASE_URL`
- [ ] `FRONTEND_URL` + `CORS_ORIGINS` (custom domains)
- [ ] `XAI_API_KEY` (and/or Anthropic)
- [ ] `STRIPE_SECRET_KEY` live + webhook secret
- [ ] Optional: `CRYPTO_*_ADDRESS` real wallets

### Product QA
- [ ] Sign up / login
- [ ] Trial activation
- [ ] Card checkout (live)
- [ ] Crypto invoice (optional)
- [ ] Chat reply (xAI)
- [ ] Create company / project / agent
- [ ] Token meter updates

### Launch day
- [ ] Status check `/api/health`
- [ ] Disable or hide demo-only copy on login if any
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

1. Deploy **website/** to Vercel and attach **aiassistant.xyz**  
2. Attach **app.aiassistant.xyz** to the app project + update CORS/FRONTEND_URL  
3. Soft-launch to 5–10 users on trial (Stripe still test if you want)  
4. Flip Stripe to **live** when ready for real revenue  
5. Submit TestFlight / Play internal builds  

When you want execution on a step (e.g. “deploy website project” or “switch Stripe live”), say which step and we’ll do it.
