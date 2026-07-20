# Stripe sandbox setup (test transactions)

## 1. Get test keys

1. Open [Stripe Dashboard → Test mode](https://dashboard.stripe.com/test/apikeys) (toggle **Test mode** ON).
2. Copy **Secret key** (`sk_test_…`).

## 2. Set on Vercel

```bash
cd ai-business-assistant
vercel env add STRIPE_SECRET_KEY production
# paste sk_test_…
vercel --prod
```

Optional later:
- `STRIPE_WEBHOOK_SECRET` for server-side webhooks
- `STRIPE_PRICE_*` if you prefer fixed Product prices (otherwise inline monthly prices from the app plans)

## 3. Test a payment

1. Sign in → **Billing** or **Subscribe**.
2. Click **Top up with card (test)** or **Subscribe with card (test)**.
3. Use Stripe test card:
   - Number: `4242 4242 4242 4242`
   - Expiry: any future date
   - CVC: any 3 digits
   - ZIP: any
4. After redirect, the app confirms the session and unlocks plan / credits.

## 4. Go live later

1. Switch Stripe to **Live mode**.
2. Replace `STRIPE_SECRET_KEY` with `sk_live_…`.
3. Add webhook endpoint: `https://YOUR_DOMAIN/api/billing/webhook`
4. Events:
   - `checkout.session.completed` — activate plan / top-up / storage (`_activate_plan` + token pool)
   - `customer.subscription.deleted` / `customer.subscription.updated` — cancel or re-open access
   - `invoice.paid` (or `invoice.payment_succeeded`) — renew: re-activate + refresh token pool on cycle
5. Set `STRIPE_WEBHOOK_SECRET=whsec_…`

Checkout sessions must include `metadata.user_id` + `metadata.plan` (and `subscription_data.metadata` for the same) so cancel/renew can resolve the app user.

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /billing/payment-options` | Stripe/crypto status + sandbox flag |
| `GET /billing/meter` (also `/balance`) | Token pool + `needs_subscription` + `upgrade_cta_path` (`/subscribe` or `/billing`) for UI CTAs |
| `POST /billing/topup` | Card top-up Checkout |
| `POST /billing/plan` | Card subscription Checkout |
| `POST /billing/checkout/confirm?session_id=` | Fulfill after redirect (sandbox-friendly) |
| `POST /billing/webhook` | Stripe webhooks: `checkout.session.completed`, `customer.subscription.deleted` / `.updated`, `invoice.paid` |
