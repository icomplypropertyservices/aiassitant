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
4. Event: `checkout.session.completed`
5. Set `STRIPE_WEBHOOK_SECRET=whsec_…`

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /billing/payment-options` | Stripe/crypto status + sandbox flag |
| `POST /billing/topup` | Card top-up Checkout |
| `POST /billing/plan` | Card subscription Checkout |
| `POST /billing/checkout/confirm?session_id=` | Fulfill after redirect (sandbox-friendly) |
| `POST /billing/webhook` | Stripe webhook fulfillment |
