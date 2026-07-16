# iOS App Store readiness — AI Business Assistant

This app is a **Capacitor** shell around the existing React SPA. The API stays on
**Vercel**: https://aiassitant-nu.vercel.app

| Item | Value |
|------|--------|
| Bundle ID | `com.icomply.aibusinessassistant` |
| Display name | AI Business Assistant |
| Web / API | `https://aiassitant-nu.vercel.app` |
| Native API base | `https://aiassitant-nu.vercel.app/api` |
| Min tooling | macOS + Xcode 15+ + Apple Developer Program ($99/yr) |

> **Windows note:** You can build the web bundle and Capacitor config on Windows.
> **Creating / archiving the iOS app requires a Mac** (or a cloud Mac CI).

---

## 1. One-time Apple setup

1. Enroll in [Apple Developer Program](https://developer.apple.com/programs/).
2. In [App Store Connect](https://appstoreconnect.apple.com/) create an app:
   - Name: **AI Business Assistant** (must be unique)
   - Bundle ID: `com.icomply.aibusinessassistant`
   - SKU: e.g. `aiba-ios-001`
   - Primary language: English (UK) or English (US)
3. Create a distribution certificate + App Store provisioning profile (Xcode can manage this automatically when signed in).

---

## 2. Build the iOS project (on a Mac)

```bash
cd frontend

# Install deps
npm ci

# Production native web build (points API at Vercel)
npm run build:ios

# First time only — generate ios/ project
npx cap add ios

# After every web change
npm run build:ios
npx cap open ios
```

In **Xcode**:

1. Select team under **Signing & Capabilities**.
2. Confirm Bundle Identifier = `com.icomply.aibusinessassistant`.
3. Add privacy strings (see `frontend/ios-config/Info.plist.additions.md`):
   - Microphone
   - Speech recognition
4. Set **ITSAppUsesNonExemptEncryption** = NO (standard HTTPS).
5. Product → Archive → Distribute App → App Store Connect.

---

## 3. App Store Connect listing checklist

### Screenshots (required)

| Device | Sizes (portrait) |
|--------|------------------|
| iPhone 6.7" | 1290×2796 or 1320×2868 |
| iPhone 6.5" | 1284×2778 (if still required for your account) |
| iPad 13" (if you support iPad) | 2048×2732 |

Capture: Login, Dashboard, Agents, Chat (with voice if possible), Billing meter.

### Metadata

- **Subtitle** (30 chars): e.g. `Agents · Tasks · AI Chat`
- **Promotional text** (optional, editable without review)
- **Description** — what the app does, who it’s for
- **Keywords** — comma separated, no competitor names
- **Support URL** — your site or help desk
- **Marketing URL** (optional)
- **Privacy Policy URL** — **required**  
  Host something public, e.g.  
  `https://aiassitant-nu.vercel.app/privacy`  
  (static page included in repo — deploy with the web app)

### Age rating

Answer the questionnaire honestly. Typical for this app: **4+** or **12+** if
you collect account data; no unrestricted web browsing.

### App Review notes

Provide:

- Demo account: `admin@local` / `admin123` (or a dedicated reviewer account)
- Note that AI replies need network access to your Vercel backend
- Mic permission is only for optional voice chat

---

## 4. Privacy (App Privacy “nutrition labels”)

Declare in App Store Connect what you collect:

| Data | Likely | Notes |
|------|--------|--------|
| Email | Yes | Account |
| Name | Yes | Profile |
| User content | Yes | Chat / tasks / agent configs |
| Usage data | Optional | Billing token meter |
| Payment info | Via Stripe | If IAP or external purchase — see §5 |

Link privacy policy. Document encryption keys stored for user-provided API keys
(encrypted at rest server-side).

---

## 5. Payments (important)

Apple’s guidelines on digital goods:

- **If users buy app features / tokens only inside iOS** → usually **In-App Purchase**.
- **If the app is a “reader” / multi-platform business tool** with accounts created on the web, external purchase (Stripe on web) may be acceptable for multi-platform SaaS — review **Guideline 3.1** carefully with counsel.
- Current product uses **Stripe web checkout**. For App Review safety you can:
  1. Hide “Subscribe / top-up” buttons on iOS and deep-link to the website, **or**
  2. Implement StoreKit IAP for plans/credits.

Flag this before submission so review does not reject for payments.

---

## 6. Technical readiness (already done in repo)

- [x] Capacitor 8 + iOS package
- [x] Native API base → production Vercel `/api`
- [x] HashRouter in native shell
- [x] Safe-area / notch CSS
- [x] Status bar + splash + keyboard plugins
- [x] Mic / speech privacy string templates
- [x] App icons under `frontend/public/icons/`
- [x] PWA manifest (bonus for “Add to Home Screen”)
- [x] Privacy policy static page for hosting

### Still on you / Mac

- [ ] Apple Developer enrollment
- [ ] `npx cap add ios` + Xcode signing
- [ ] Screenshots + listing copy
- [ ] Privacy Policy live URL
- [ ] Decide IAP vs web billing for iOS
- [ ] TestFlight internal build
- [ ] Submit for review

---

## 7. Daily dev loop

```bash
# Web only
npm run dev

# After UI changes, refresh iOS shell
npm run build:ios
npx cap open ios   # then Run on simulator / device
```

Change production API URL in `frontend/.env.native` if the Vercel domain changes.

---

## 8. Android

Android platform is in `frontend/android`. Full Play Store guide:

→ **[STORE_READY.md](./STORE_READY.md)**

```bash
npm run build:android:sandbox   # Test / internal
npm run build:android           # Store-oriented web bundle
npx cap open android            # Android Studio
```
