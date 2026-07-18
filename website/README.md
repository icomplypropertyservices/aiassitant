# Marketing website — aibusinessagent.xyz

Static marketing site served at the **domain root**.

| Path | What |
|------|------|
| `https://aibusinessagent.xyz/` | This site (`website/`) |
| `https://aibusinessagent.xyz/demo.html` | Interactive product demo (no login) |
| `https://aibusinessagent.xyz/agents` | Product app |
| `https://aibusinessagent.xyz/bay` | AgentBay marketplace |

## Local

```bash
cd website
npm start   # http://localhost:5174
```

## Production

Shipped by the monorepo root `vercel.json` build: copies `website/` into `public/` at deploy time.  
Do **not** attach a separate marketing-only Vercel project unless you intentionally split hosts.

## CTAs

`js/main.js` rewrites:

- `data-app-href="/login"` → `/agents/login`
- `data-bay-href="/"` → `/bay/`

Nav links to **Open app** and **AgentBay** are same-origin paths (no subdomains).
