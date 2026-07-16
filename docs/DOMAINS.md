# Domains: marketing vs app

| URL | Purpose | Deploy from |
|-----|---------|-------------|
| **https://aiassistant.xyz** | Marketing / landing site | `website/` (separate Vercel project) |
| **https://www.aiassistant.xyz** | Redirect or alias to marketing | same |
| **https://app.aiassistant.xyz** | Product app + API | monorepo root (current `aiassitant` project) |

## Why two projects

- Marketing is static HTML — fast CDN, independent deploys.
- App is FastAPI + React SPA — needs Python env vars, Neon, Stripe, etc.
- Clear split: ads land on the root domain; login opens the app subdomain.

## Setup checklist

### 1. Marketing project

```text
Root Directory: website
Output: .
Domains: aiassistant.xyz, www.aiassistant.xyz
```

### 2. App project (existing)

```text
Domain: app.aiassistant.xyz
FRONTEND_URL=https://app.aiassistant.xyz
CORS_ORIGINS=https://app.aiassistant.xyz,https://aiassistant.xyz
```

Optional keep old `*.vercel.app` in CORS while migrating.

### 3. DNS

Point records as shown in the Vercel domain UI for each project.

### 4. Mobile / native

```env
VITE_PROD_API_URL=https://app.aiassistant.xyz/api
```

Rebuild: `npm run build:mobile` (or `:sandbox`).

### 5. Stripe webhook

When live:

```text
https://app.aiassistant.xyz/api/billing/webhook
```

## Until custom DNS is live

App remains at: https://aiassitant-nu.vercel.app  
Marketing can be previewed with `cd website && npm start` or a Vercel preview URL.
