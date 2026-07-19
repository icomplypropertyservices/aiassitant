# Android + iOS launch guide (owner checklist)

**App ID:** `com.icomply.aibusinessassistant`  
**Version:** 1.5.0 (`versionCode` 10500)  
**Live app:** https://aibusinessagent.xyz/agents  
**API:** https://aibusinessagent.xyz/api  
**Privacy:** https://aibusinessagent.xyz/privacy.html  
**Terms:** https://aibusinessagent.xyz/terms.html  
**Support:** https://aibusinessagent.xyz/support.html  

## How subscriptions work in the mobile apps

| Action | What happens |
|--------|----------------|
| Free trial | Starts **inside the app** (API) — no card |
| Starter / Pro / Business (month or year) | Opens **Stripe Checkout** in the **system browser** (secure sheet) |
| Credit top-up | Same Stripe Checkout flow |
| After payment | Return to the app → plan / credits refresh automatically |
| Manage card / cancel | “Manage subscription” → Stripe Customer Portal in browser |

Product IDs for optional pure Store IAP later are listed at  
`GET /api/billing/native/products` and in `frontend/src/nativeBilling.js`.

> **Apple note:** Multi-platform SaaS often uses external checkout. If App Review  
> requires pure In-App Purchase, create the Apple product IDs from that endpoint  
> and wire StoreKit (or RevenueCat). Android is more flexible with Stripe browser checkout.

---

## A. What you need (accounts)

1. **Apple Developer Program** ($99/year) — https://developer.apple.com/programs/  
2. **Google Play Console** ($25 one-time) — https://play.google.com/console  
3. **Mac with Xcode 15+** (only for iOS archive)  
4. **Android Studio** (Windows is fine for Android)  
5. Production site live with **Stripe live keys** on Vercel (`STRIPE_SECRET_KEY=sk_live_…`)

---

## B. Build the web shell into the apps

On your PC (this repo):

```bash
cd frontend
npm ci

# Production native bundle (API → aibusinessagent.xyz)
npm run build:mobile

# Or one platform:
npm run build:android
npm run build:ios          # still needs Mac for Xcode open
```

Sandbox / TestFlight testing against Stripe **test** mode:

```bash
npm run build:mobile:sandbox
```

---

## C. Android (Play Store) — step by step

### 1. One-time signing key

```bash
cd frontend/android
keytool -genkey -v -keystore aiba-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias aiba
```

Copy `key.properties.example` → `frontend/android/key.properties`:

```properties
storePassword=YOUR_STORE_PASSWORD
keyPassword=YOUR_KEY_PASSWORD
keyAlias=aiba
storeFile=../aiba-upload.jks
```

**Back up the `.jks` and passwords offline.** Losing them blocks updates.

### 2. Open Android Studio & build AAB

```bash
cd frontend
npm run build:android
npx cap open android
```

In Android Studio:

1. Wait for Gradle sync  
2. **Build → Generate Signed Bundle / APK → Android App Bundle**  
   (or `./gradlew bundleRelease` if `key.properties` is set)  
3. Output: `android/app/build/outputs/bundle/release/app-release.aab`

### 3. Play Console listing

1. Create app → package name **must be** `com.icomply.aibusinessassistant`  
2. Store listing: title, short description, full description  
3. Graphics:  
   - Icon 512×512  
   - Feature graphic 1024×500  
   - Phone screenshots (login, agents, chat, billing)  
4. Privacy policy URL: `https://aibusinessagent.xyz/privacy.html`  
5. Data safety form: email, name, messages, purchase history (Stripe)  
6. Content rating questionnaire  
7. **Pricing & distribution** → countries  
8. Upload AAB to **Internal testing** first → testers → then Production  

### 4. Test subscriptions on Android

1. Install internal test build  
2. Log in with a real account  
3. **Subscribe** → system browser → Stripe test card `4242…` (if `sk_test`) or real card (if live)  
4. Return to app → Billing shows active plan  

---

## D. iOS (App Store) — step by step

### 1. App Store Connect

1. Create app → Bundle ID `com.icomply.aibusinessassistant`  
2. SKU e.g. `aiba-ios-001`  
3. Privacy Policy URL + Support URL (above)  

### 2. Build on a Mac

```bash
cd frontend
npm ci
npm run build:ios
# First time only:
npx cap add ios
npx cap sync ios
npx cap open ios
```

In **Xcode**:

1. Signing & Capabilities → your Team  
2. Bundle ID = `com.icomply.aibusinessassistant`  
3. Add Info.plist keys from `frontend/ios-config/Info.plist.additions.md`:  
   - Microphone + Speech  
   - `ITSAppUsesNonExemptEncryption` = NO  
   - URL scheme `aiba`  
4. **Product → Archive → Distribute App → App Store Connect**  
5. Wait for processing → **TestFlight** → internal testers  

### 3. Screenshots (required)

- iPhone 6.7" (e.g. 1290×2796): Login, Dashboard, Agents, Chat, Billing  
- Optional iPad if you support tablets  

### 4. App Review notes (paste into Connect)

```
Demo account: [create a dedicated reviewer email/password]
Network: app requires https://aibusinessagent.xyz/api
Subscriptions: multi-platform SaaS — plans/top-ups use Stripe Checkout in the system browser;
account works on web + mobile. Free trial works fully in-app without payment.
Microphone: optional voice chat only.
```

---

## E. Before you submit (checklist)

- [ ] Vercel production is green; login works on phone browser  
- [ ] Stripe **live** keys + webhook on production  
- [ ] Privacy / Terms / Support pages open publicly  
- [ ] Reviewer account created (not your personal admin)  
- [ ] Android internal track install tested  
- [ ] iOS TestFlight install tested  
- [ ] Subscribe + top-up tested end-to-end  
- [ ] Token meter moves after chat/agent work  

---

## F. Commands cheat sheet

| Goal | Command |
|------|---------|
| Refresh both native shells | `cd frontend && npm run build:mobile` |
| Android Studio | `npm run android` |
| iOS Xcode (Mac) | `npm run ios` |
| Sandbox builds | `npm run build:mobile:sandbox` |
| List store product IDs | `curl https://aibusinessagent.xyz/api/billing/native/products` |

---

## G. Common issues

| Problem | Fix |
|---------|-----|
| API fails in app | Confirm `VITE_PROD_API_URL=https://aibusinessagent.xyz/api` in `.env.native` |
| Checkout opens then plan not updated | Return to app; pull Billing; ensure Stripe webhook or `/billing/checkout/confirm` |
| Play rejects “digital goods” | Keep Stripe multi-platform wording; or implement Play Billing with product IDs from `/billing/native/products` |
| Apple asks for IAP | Create auto-renewable subscriptions matching Apple IDs; contact if you need full StoreKit wiring |
| No Mac for iOS | Use a cloud Mac (MacStadium, Codemagic, GitHub macOS runner) with the same `npm run build:ios` steps |

---

## H. What was implemented in code (v1.5)

- In-app **Subscribe / Billing / Top-up** on native via Capacitor **Browser** + Stripe  
- Deep link scheme **`aiba://billing/...`** + Android App Links prefix  
- Resume listener refreshes plan after checkout  
- Backend tags checkouts with `platform` / `client=mobile`  
- `GET /billing/native/products` for App Store / Play SKUs  
- Android release signing via `key.properties`  
- Version **1.5.0** / versionCode **10500**
