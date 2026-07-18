# RunPod → AI Business Assistant (connect checklist)

Clients only see **Fast / Quality / Reasoning / Large**.  
You spin one GPU pod, paste two URLs into Vercel, redeploy.

---

## Step 1 — Create this instance (exact)

| Setting | Choose |
|--------|--------|
| **Product** | **Pods** (GPU Cloud) — not Serverless for first setup |
| **Cloud** | Secure Cloud preferred (more stable) |
| **GPU** | **1× RTX 4090 24GB** (best start) **or** **1× A40 48GB** (more headroom for 14B/32B) |
| **Template** | RunPod **PyTorch** or **Ubuntu + Docker** (Docker needed for Open WebUI) |
| **Container disk** | **≥ 80 GB** (models need space; 100–200 GB better) |
| **Volume** | Optional network volume 100–200 GB so restarts keep models |
| **Expose HTTP ports** | **`11434`** (Ollama) and **`8080`** (Open WebUI) |
| **Start** | Deploy → wait until **Running** |

**Do not** pick CPU-only or tiny disk.  
**Skip** H100/A100 for day one (expensive) unless you need 70B+.

---

## Step 2 — Install stack on the pod

Open the pod **Web terminal** (or Jupyter terminal) and paste:

```bash
curl -fsSL https://ollama.com/install.sh | sh
export OLLAMA_HOST=0.0.0.0:11434
nohup ollama serve >/tmp/ollama.log 2>&1 &
sleep 3

ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull deepseek-r1:8b

# Open WebUI (if Docker available)
docker run -d --name open-webui -p 8080:8080 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  --restart unless-stopped \
  ghcr.io/open-webui/open-webui:main
```

Or upload / copy `backend/scripts/runpod_bootstrap.sh` and run:

```bash
bash runpod_bootstrap.sh
```

**Sanity check on the pod:**

```bash
curl -s http://127.0.0.1:11434/api/tags
ollama list
```

---

## Step 3 — Copy proxy URLs

On the pod page → **Connect** → **HTTP services**:

| Port | Env var | Example |
|------|---------|---------|
| 11434 | `RUNPOD_OLLAMA_URL` | `https://xxxxx-11434.proxy.runpod.net` |
| 8080 | `RUNPOD_WEBUI_URL` | `https://xxxxx-8080.proxy.runpod.net` |

Optional (if you add API auth later): `RUNPOD_API_KEY`.

**Test from your PC** (browser or curl):

```bash
curl -s https://YOUR_POD_ID-11434.proxy.runpod.net/api/tags
```

You should see JSON with a `models` list. If timeout / 404, HTTP proxy for 11434 is not enabled or Ollama is not bound to `0.0.0.0`.

---

## Step 4 — Connect the site (easiest: Admin UI)

After the app is deployed (or running locally), sign in as **admin**:

1. **Staff Admin → Connection**
2. Paste `RUNPOD_OLLAMA_URL` and optional WebUI URL
3. **Save connection** (stored in the database — no Vercel redeploy required)
4. **Fleet terminal** → `list` → `pull qwen2.5:7b` → `test qwen2.5:7b`
5. **Models & routing** → change Fast/Quality tags, remove models, pull custom tags
6. **Copy support bundle for Grok** → paste into this chat so Grok can help with the next steps

### Optional: env vars on Vercel (bootstrap / backup)

```
RUNPOD_OLLAMA_URL=https://YOUR_POD_ID-11434.proxy.runpod.net
RUNPOD_WEBUI_URL=https://YOUR_POD_ID-8080.proxy.runpod.net
RUNPOD_MODEL_FAST=qwen2.5:7b
RUNPOD_MODEL_QUALITY=qwen2.5:14b
RUNPOD_MODEL_REASONING=deepseek-r1:8b
RUNPOD_MODEL_LARGE=qwen2.5:14b
RUNPOD_MODEL_SMALL=qwen2.5:3b
RUNPOD_MODEL_MEDIUM=qwen2.5:7b
```

Admin UI overrides these when saved.

---

## Step 5 — Verify in the app

1. Sign in as **admin** on `https://app.aiassistant.xyz`
2. Open **Admin → LLM Fleet**
3. Banner should say **Managed LLM fleet is reachable**
4. Models table lists Ollama tags
5. Chat as a normal user with model **Fast** or **Quality**

API check (with admin JWT):

```
GET /api/admin/fleet/status
```

`probe.ok` should be `true`.

---

## Mapping (already built into the app)

| Customer sees | Default Ollama tag |
|---------------|--------------------|
| Fast | `qwen2.5:7b` |
| Quality | `qwen2.5:14b` |
| Reasoning | `deepseek-r1:8b` (or 14b on more VRAM) |
| Large | `qwen2.5:14b` / `32b` when GPU allows |
| Small | `qwen2.5:3b` |
| Medium | `qwen2.5:7b` |

Change live in Admin → Save routing (no redeploy).

---

## Grok (xAI) — second path

`XAI_API_KEY` is already on Vercel. After RunPod works for day-to-day agents, we wire Grok as premium / fallback. **Do RunPod first.**

---

## Common failures

| Symptom | Fix |
|---------|-----|
| Fleet offline | Wrong URL, missing redeploy, or port 11434 not exposed |
| `curl` tags empty | Models not pulled yet |
| Slow first reply | Cold model load into VRAM — first call after idle is slow |
| 401 on proxy | You enabled auth — set `RUNPOD_API_KEY` |
| Pod stopped | Start the pod again; network volume keeps models |

---

## What to send back here

Paste (redact secrets if any):

1. GPU you picked (4090 / A40 / other)
2. `RUNPOD_OLLAMA_URL` (full proxy URL)
3. `RUNPOD_WEBUI_URL` if you installed WebUI

Then we set Vercel env + redeploy from this machine.
