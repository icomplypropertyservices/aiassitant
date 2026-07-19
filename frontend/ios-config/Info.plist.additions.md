# iOS Info.plist keys (App Store / microphone)

When the `ios/` project exists (created on a Mac with `npx cap add ios`), add these
keys in Xcode → Target → Info, or merge into `ios/App/App/Info.plist`.

## Required for voice (microphone + speech)

```xml
<key>NSMicrophoneUsageDescription</key>
<string>AI Business Assistant uses the microphone so you can talk to your agents.</string>

<key>NSSpeechRecognitionUsageDescription</key>
<string>Speech recognition converts your voice into text for agent chat.</string>
```

## App transport / API

Production API is HTTPS (`https://aiassitant-nu.vercel.app`). Do **not** enable
arbitrary loads unless you must hit local HTTP during development.

```xml
<!-- Dev only if needed -->
<!--
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsLocalNetworking</key>
  <true/>
</dict>
-->
```

## Background modes / push

For push notifications, enable **Background Modes → Remote notifications** in Xcode
and configure APNs (Apple Developer → Keys → Apple Push Notifications service).

Also ensure the app requests notification permission (handled by Capacitor
`PushNotifications` + `LocalNotifications` at runtime).

```xml
<!-- Optional: app display name already set by Capacitor -->
```

## Encryption export compliance

In App Store Connect, for standard HTTPS + no custom crypto beyond OS/TLS:

- **Does your app use encryption?** → Yes (HTTPS)
- **Exempt under category 5 part 2?** → Yes (standard HTTPS)

Or set in Info.plist:

```xml
<key>ITSAppUsesNonExemptEncryption</key>
<false/>
```

## URL scheme (return from Stripe checkout)

```xml
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLName</key>
    <string>com.icomply.aibusinessassistant</string>
    <key>CFBundleURLSchemes</key>
    <array>
      <string>aiba</string>
    </array>
  </dict>
</array>
```

Also add **Associated Domains** (optional App Links):

```
applinks:aibusinessagent.xyz
```

## Production API host

API base for native builds: `https://aibusinessagent.xyz/api`  
(set in `frontend/.env.native` as `VITE_PROD_API_URL`)
