# RunPod Fleet Plan — AI Business Assistant

Clients only ever see: **Fast / Quality / Reasoning / Large Context**.  
Admin controls the real fleet (Ollama Qwen + DeepSeek + Open WebUI).

---

## Recommended hardware (buy / rent on RunPod)

### Tier A — Always-on “workhorse” (start here)

| Role | GPU | VRAM | Why |
|------|-----|------|-----|
| **Primary Ollama + Open WebUI** | **1× RTX 4090** or **1× A40** | 24–48 GB | Runs most Qwen 3B–32B + DeepSeek R1 8B–32B (quantized). Best $/token for day-to-day agents. |

**RunPod product:** Secure Cloud or Community Cloud **GPU Pod** (not serverless first).  
**Template:** Ubuntu + Docker → install Ollama + Open WebUI.  
**Disk:** 200–500 GB (models add up).  
**Network volume (optional):** attach so you can restart pods without re-downloading models.

**Pull on this pod (Ollama):**
```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull qwen2.5:32b
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:8b
ollama pull deepseek-r1:14b
ollama pull deepseek-r1:32b
```

---

### Tier B — Large / reasoning (scale-up pod)

| Role | GPU | VRAM | Why |
|------|-----|------|-----|
| **72B / heavy DeepSeek** | **1× A100 80GB** or **1× H100 80GB** | 80 GB | Qwen2.5:72B, DeepSeek-R1:70B, long-context quality tier. |

Only run when load needs it (or keep as second always-on if budget allows).

```bash
ollama pull qwen2.5:72b
ollama pull qwen3-coder:30b
ollama pull deepseek-r1:70b
```

---

### Tier C — Horizontal scale (customer load)

When many customers hit chat/agents at once:

| Option | Use when |
|--------|----------|
| **Clone Tier A pods** (same template + network volume) | Steady multi-tenant load |
| **RunPod Serverless** (vLLM or Ollama workers) | Spiky traffic, pay per second |
| **Load balancer / multi-base-URL** in admin | Route `fast` → pod1, `quality` → pod2 |

**Scale rule of thumb:**
- 1× 4090 ≈ comfortable for ~5–15 concurrent light chats (7B–14B)
- Heavy 32B/70B → fewer concurrent jobs; queue + second GPU

---

## What to create in your RunPod account (checklist)

1. **GPU Pod (Tier A)**  
   - GPU: RTX 4090 24GB **or** A40 48GB  
   - Image: RunPod PyTorch / Ubuntu  
   - Expose ports: `11434` (Ollama), `8080` (Open WebUI)  
   - Enable **HTTP services** / public proxy for those ports  

2. **Install stack on the pod**
   ```bash
   # Ollama
   curl -fsSL https://ollama.com/install.sh | sh
   ollama serve   # or systemd

   # Open WebUI (Docker)
   docker run -d -p 8080:8080 \
     -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
     -v open-webui:/app/backend/data \
     --name open-webui \
     --add-host=host.docker.internal:host-gateway \
     ghcr.io/open-webui/open-webui:main
   ```

3. **Copy URLs into backend env** (see `.env.example`)
   - `RUNPOD_OLLAMA_URL` = `https://xxxxx-11434.proxy.runpod.net` (or your TCP proxy)
   - `RUNPOD_WEBUI_URL` = `https://xxxxx-8080.proxy.runpod.net`
   - Optional API key if you put a reverse proxy auth in front

4. **Admin → LLM Fleet** in the app  
   - Monitor models / tokens  
   - Top up customer wallets  
   - Remap Fast/Quality → which Ollama tag is live  
   - Open WebUI embedded for ops

5. **Later:** spin Tier B for 72B and add second base URL in admin model map.

---

## Neutral client models → Ollama mapping (default)

| Client sees | Default Ollama model | GPU tier |
|-------------|----------------------|----------|
| Fast | `qwen2.5:7b` | A |
| Quality | `qwen2.5:14b` or `32b` | A |
| Reasoning | `deepseek-r1:14b` or `32b` | A/B |
| Large | `qwen2.5:32b` or `72b` | A/B |
| Small | `qwen2.5:3b` | A |
| Medium | `qwen2.5:7b` / coder | A |

Admin can change mapping on demand without customers noticing.

---

## Budget sketch (ballpark, RunPod hourly)

| Pod | Rough GPU | Typical range* |
|-----|-----------|----------------|
| Tier A 4090 | 24GB | often lowest $/hr for 7–32B |
| Tier A A40 | 48GB | more headroom for 32B concurrent |
| Tier B A100/H100 80GB | 80GB | higher $/hr — only for 70B+ |

\*Check current RunPod pricing in console — rates change.

---

## Security notes

- Do **not** expose raw Ollama without auth if the URL is public.  
- Prefer RunPod proxy + auth header, or IP allowlist.  
- Customers never see RunPod / Ollama / model tags — only Managed Fast/Quality/etc.
