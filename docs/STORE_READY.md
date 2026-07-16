# App Store + Play Store readiness

| | iOS | Android |
|--|-----|---------|
| **Shell** | Capacitor 8 | Capacitor 8 |
| **App ID** | `com.icomply.aibusinessassistant` | `com.icomply.aibusinessassistant` |
| **Version** | 1.4.0 | 1.4.0 (`versionCode` 10400) |
| **API** | `https://aiassitant-nu.vercel.app/api` | same |
| **Privacy** | https://aiassitant-nu.vercel.app/privacy | same |
| **Support** | https://aiassitant-nu.vercel.app/support | same |

Payments: **web Stripe (sandbox `sk_test`) + crypto**. Mobile billing buttons open the website where required by store rules (`IS_NATIVE` paths already do this).

---

## Sandbox builds (TestFlight / internal testing)

Same production API; Stripe on the server is **test mode** — no real card charges.

```bash
cd frontend
npm ci

# Both platforms, sandbox-flagged web bundle
npm run build:mobile:sandbox

# Or one platform
npm run build:ios:sandbox      # then open on Mac: npx cap open ios
npm run build:android:sandbox  # then: npx cap open android
```

**Android sandbox APK/AAB** (requires Android SDK / Android Studio):

```bash
cd frontend/android
# Debug APK
./gradlew assembleDebug
# Release AAB (needs signing config — see Play Store § below)
./gradlew bundleRelease
```

On Windows PowerShell: `.\gradlew.bat assembleDebug`

**iOS sandbox** (Mac + Xcode):

```bash
npm run build:ios:sandbox
npx cap open ios
# Scheme → Any iPhone simulator or device
# Product → Archive for TestFlight (signing team required)
```

**Test card (when Stripe is sk_test on server):**  
`4242 4242 4242 4242` · any future expiry · any CVC

**Demo account for review / QA:**  
`firealarmsdublin@gmail.com` / (see secure notes — or create a dedicated reviewer user)

---

## Store / production native builds

```bash
cd frontend
npm run build:mobile        # both platforms
# or
npm run build:ios
npm run build:android
```

Before **real** money: set Vercel `STRIPE_SECRET_KEY=sk_live_…` and webhook secret.

---

## Play Store checklist

1. [Google Play Console](https://play.google.com/console) — create app  
2. Package name: `com.icomply.aibusinessassistant`  
3. Signing: Play App Signing + upload keystore  
4. Store listing: short + full description, icon 512×512, feature graphic 1024×500  
5. Screenshots: phone (and tablet if supported)  
6. Privacy policy URL: `https://aiassitant-nu.vercel.app/privacy`  
7. Content rating questionnaire  
8. Target audience / data safety form (email, name, messages, payments via Stripe)  
9. **Payments:** declare that digital subscriptions are managed outside the app / on the website for multi-platform SaaS (or implement Play Billing)  
10. Upload **AAB** from `bundleRelease`  
11. Internal testing track → closed → production  

### Signing (first time)

```bash
# Create upload keystore (keep offline / password manager)
keytool -genkey -v -keystore aiba-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias aiba
```

Add to `android/key.properties` (gitignored) and wire `signingConfigs` in `app/build.gradle` before release.

---

## App Store checklist

See also [APP_STORE_IOS.md](./APP_STORE_IOS.md).

1. Apple Developer Program + App Store Connect app  
2. Bundle ID: `com.icomply.aibusinessassistant`  
3. Xcode signing (Automatic recommended)  
4. Archive → Upload → TestFlight  
5. Screenshots (6.7" required)  
6. Privacy Policy + Support URLs (above)  
7. App Privacy labels (email, name, user content, usage)  
8. **Guideline 3.1:** multi-platform SaaS — purchases on website; app already routes iOS billing to web  
9. Review notes: demo login, needs network, mic for optional voice  
10. Submit for review  

---

## What is already in the repo

- [x] Capacitor iOS project (`frontend/ios`)  
- [x] Capacitor Android project (`frontend/android`)  
- [x] Native API env (`.env.native` / `.env.native.sandbox`)  
- [x] HashRouter on native  
- [x] Safe-area / splash / status bar / keyboard  
- [x] Mic privacy strings (iOS Info.plist)  
- [x] INTERNET + RECORD_AUDIO (Android)  
- [x] Privacy + Support static pages  
- [x] Stripe sandbox on production API  
- [x] Crypto pay optional  

### Still on you

- [ ] Apple / Google developer accounts  
- [ ] Signing certificates / keystore  
- [ ] Screenshots & store copy  
- [ ] Live Stripe when leaving sandbox  
- [ ] TestFlight + Play internal test groups  

---

## Commands cheat sheet

| Goal | Command |
|------|---------|
| Sandbox both | `npm run build:mobile:sandbox` (from monorepo root) |
| Store both | `npm run build:mobile` |
| Open Android Studio | `npm run android` or `android:sandbox` |
| Open Xcode (Mac) | `npm run ios` or `ios:sandbox` |
