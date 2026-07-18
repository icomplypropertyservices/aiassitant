# Production: RunPod + app checklist

## Live production app

- **API / SPA:** https://aiassitant-nu.vercel.app  
- **Health:** `GET /api/health` → `{"ok":true,"environment":"production"}`

## Vercel Production env (set)

| Variable | Purpose |
|----------|---------|
| `RUNPOD_OLLAMA_URL` | `https://1c51fgbx9y1jnl-11434.proxy.runpod.net` |
| `RUNPOD_MODEL_*` | Qwen tags for Fast/Quality/etc. |
| `GROK_SESSION_TOKEN` | Super JWT (not API key) |
| `XAI_USE_JWT_ONLY` | `true` |
| `XAI_MODEL_GROK4` | `grok-4.5` (Server Monitor) |
| `DATABASE_URL` | Neon Postgres |
| `JWT_SECRET` / `APP_ENV` | production |

## After every pod start (required)

RunPod may stop Ollama when the container restarts. In **Web terminal** or SSH:

```bash
export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_KEEP_ALIVE=24h
command -v ollama || curl -fsSL https://ollama.com/install.sh | sh
nohup env OLLAMA_HOST=0.0.0.0:11434 ollama serve >/tmp/ollama.log 2>&1 &
sleep 5
curl -s http://127.0.0.1:11434/api/tags
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
```

Or: `bash pod_keep_ollama.sh` from `backend/scripts/`.

**HTTP port 11434** must stay exposed. Test from your PC:

```powershell
curl.exe -sS "https://1c51fgbx9y1jnl-11434.proxy.runpod.net/api/tags"
```

Expect JSON with `"models":[...]`, not “Waiting for service”.

## Admin after Ollama is green

1. Sign in as **admin** on production  
2. **Staff Admin → Connection** — paste Ollama URL if not using env only → Save  
3. **Admin Ops Team** → Create staff ops team  
4. **Fleet terminal** → `list` → `test qwen2.5:7b`  
5. Open **Server Monitor** chat (Grok JWT)  

## Prefer pod stay running

- Use **On-demand** pod and leave it **Running** during business hours  
- Optional: network volume for models so restarts don’t re-download  

## JWT refresh

When Super JWT expires, re-login with `grok` CLI and re-set `GROK_SESSION_TOKEN` on Vercel, then redeploy or wait for next cold start to pick env (env alone is enough on next request after update).
