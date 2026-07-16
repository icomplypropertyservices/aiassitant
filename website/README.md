# Marketing website — aiassistant.xyz

Static landing site for **AI Assistant**.  
The product app is separate: **https://app.aiassistant.xyz**

| Host | Content | Folder |
|------|---------|--------|
| `aiassistant.xyz` / `www` | This marketing site | `website/` |
| `app.aiassistant.xyz` | Product SPA + API | monorepo root (`frontend` + `api`) |

## Local preview

```bash
cd website
npm start
# http://localhost:5174
```

## Deploy to Vercel (recommended: separate project)

1. In Vercel → **Add New Project** → import the same GitHub repo.
2. **Root Directory:** `website`
3. Framework preset: **Other** (static).
4. Build command: leave empty (or `echo static`).
5. Output directory: `.` (project root of `website`).
6. Domains:
   - Production: `aiassistant.xyz` and `www.aiassistant.xyz`
7. Do **not** attach `app.aiassistant.xyz` here — that stays on the app project.

CLI alternative (from this folder):

```bash
cd website
npx vercel --prod
# then add domain in dashboard
```

## App project domains

On the **existing** app Vercel project (`aiassitant`):

1. Add domain: `app.aiassistant.xyz`
2. Set env:
   - `FRONTEND_URL=https://app.aiassistant.xyz`
   - `CORS_ORIGINS=https://app.aiassistant.xyz,https://aiassistant.xyz`
3. Update native builds: `VITE_PROD_API_URL=https://app.aiassistant.xyz/api`

DNS (at your registrar for `aiassistant.xyz`):

| Type | Name | Value |
|------|------|--------|
| A / CNAME | `@` | per Vercel marketing project |
| CNAME | `www` | per Vercel |
| CNAME | `app` | `cname.vercel-dns.com` (app project) |

## Pages

- `/` — landing
- `/features.html` — features
- `/pricing.html` — plans
- `/about.html` — about
- `/support.html` — support / contact
- `/privacy.html` — privacy policy

CTAs point to `https://app.aiassistant.xyz/login`.
