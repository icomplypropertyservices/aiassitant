# App icons

Replace these placeholders before App Store submission:

| File | Size | Use |
|------|------|-----|
| `icon-1024.png` | 1024×1024 | App Store Connect (no transparency, no rounded corners) |
| `apple-touch-icon.png` | 180×180 | iOS home screen / web |
| `icon-192.png` | 192×192 | PWA |
| `icon-512.png` | 512×512 | PWA / Android |

After generating icons, on a Mac:

```bash
# optional: @capacitor/assets
npx @capacitor/assets generate --ios
npm run build:ios
```
