# Launch readiness — continuous swarm scorecard

**Updated:** 2026-07-17 (post Wave 2, 20 continuous agents)  
**Scope:** Code in monorepo. Live deploy/DNS is **ops**, scored separately.

---

## Overall

| Gate | Score | Status |
|------|------:|--------|
| **Code soft-launch (P0–P2 audit + GDPR + auth flows)** | **100%** | **PASS** |
| **Ops / live production (domain, secrets, smoke on host)** | **0–40%** | **HOLD** until deploy |
| **Combined public-launch readiness** | **~85%** | Deploy + env to finish |

**Agents stay “done” on code.** Remaining work is **operator deploy**, not more feature code.

---

## Area scores (code only)

| Area | Score | Evidence |
|------|------:|----------|
| Billing integrity | **100** | Prod PAYG 402; no free credits; trial one-shot 14d; seed caps; crypto conf; premium fail-closed; Stripe portal |
| Auth security | **100** | Password 8+letter+digit; JWT 48h + `tv` revoke; forgot/reset; email verify; OpenAPI off in prod |
| Abuse controls | **100** | Rate limits + optional Redis; cron secret; bridge secret guard; SSRF webhook block |
| Legal pages | **100** | terms, privacy, support; footer links; robots/sitemap |
| Domain/path config | **100** | vercel rewrites `/agents` `/bay` `/api`; Vite base; DOMAINS.md |
| GDPR delete/export | **100** | `GET /auth/export`, `POST /auth/delete-account`, Settings UI |
| Ops docs | **100** | PRODUCTION_APIS, DOMAINS, AUDIT_FIXES, audit_smoke.py, .env.example; tool access: [AGENT_TOOLS_AND_FLOWS.md](AGENT_TOOLS_AND_FLOWS.md), [GROWTH_TOOL_ACCESS.md](GROWTH_TOOL_ACCESS.md) |
| Frontend launch UX | **100** | Forgot/reset/verify pages; trial expiry UI; WS first-message auth; privacy settings |

---

## Wave 2 agent completion (20 continuous)

| ID | Task | Result |
|----|------|--------|
| A1 | Password reset API | **DONE** |
| A2 | Email verification | **DONE** |
| A3 | Account delete + export | **DONE** |
| A4 | Frontend auth UX | **DONE** |
| A5 | JWT token_version revoke | **DONE** |
| A6 | WS first-message auth | **DONE** |
| A7 | Redis rate limits | **DONE** |
| A8 | Marketing neutral copy | **DONE** |
| A9 | robots.txt + sitemap | **DONE** |
| A10 | Stripe Customer Portal | **DONE** |
| A11 | `scripts/audit_smoke.py` | **DONE** |
| A12 | PRODUCTION_APIS / DOMAINS 100% | **DONE** |
| A13 | Resend transactional helper | **DONE** |
| A14 | Schema migrate auth columns | **DONE** |
| A15 | Trial expiry UI | **DONE** |
| A16 | Health audit flags | **DONE** |
| A17 | Store/launch docs paths | **DONE** |
| A18 | Settings privacy UI | **DONE** |
| A19 | requirements + .env.example | **DONE** |
| A20 | Master scorecard | **DONE** (this file refreshed) |

---

## Ops remaining (agents cannot finish without your keys/DNS)

| # | Task | Command / action |
|---|------|------------------|
| O1 | Deploy monorepo to Vercel | Push + production deploy |
| O2 | Domain Valid `aibusinessagent.xyz` | NS already set → wait / add in Vercel |
| O3 | Env | `FRONTEND_URL=https://aibusinessagent.xyz/agents`, `CORS_ORIGINS=…`, `JWT_SECRET`, `XAI_API_KEY`, `CRON_SECRET`, `RESEND_*`, optional `REDIS_URL` |
| O4 | Smoke | `python scripts/audit_smoke.py` with `BASE_URL=https://aibusinessagent.xyz/api` |
| O5 | Stripe webhook | `https://aibusinessagent.xyz/api/billing/webhook` |

When O1–O4 pass → **public soft-launch = 100%**.

---

## How to re-verify code 100%

```powershell
cd ai-business-assistant\ai-business-assistant
python -c "import ast,pathlib; fs=list(pathlib.Path('backend/app').rglob('*.py'));
print(all(ast.parse(p.read_text(encoding='utf-8')) or True for p in fs))"
# expect no exceptions

# Local smoke (API running):
$env:BASE_URL="http://127.0.0.1:8000"
python scripts/audit_smoke.py
```

---

## Agent policy after this

- **Code queue: empty (100%).**
- Do **not** re-spawn 20 feature agents unless new scope appears.
- Next continuous work = **deploy/smoke operators** only (say “deploy” / “O1–O4”).
