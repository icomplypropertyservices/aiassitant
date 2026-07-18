# RunPod Setup for AI Business Assistant (Clean & Hidden)

Clients only see neutral names: **Fast, Quality, Reasoning, Large Context**.

Everything below is internal.

---

## 1. Create a RunPod Serverless Endpoint (Recommended)

1. Go to https://www.runpod.io/console/serverless
2. Click **+ New Endpoint**
3. Recommended templates (pick one):
   - **OpenAI Compatible** (easiest)
   - **vLLM** (best performance)
   - Or any template that exposes `/v1/chat/completions`

4. Choose a model, for example:
   - `meta-llama/Meta-Llama-3.1-8B-Instruct` (fast + cheap)
   - `meta-llama/Meta-Llama-3.1-70B-Instruct` (better quality)
   - `Qwen/Qwen2.5-14B-Instruct` (very good price/performance)

5. After it deploys, copy the **OpenAI Base URL**.
   It will look like:
   ```
   https://api.runpod.ai/v2/your-endpoint-id-here/openai/v1
   ```

6. Get your RunPod API key from:
   https://www.runpod.io/console/user/settings → API Keys

---

## 2. Set the Environment Variables

In `backend/.env` (or your deployment environment variables):

```env
# === RunPod (this is now the main backend) ===
RUNPOD_API_KEY=rp_xxxxxxxxxxxxxxxxxxxxxxxx
RUNPOD_BASE_URL=https://api.runpod.ai/v2/your-endpoint-id-here/openai/v1

# The model that is actually loaded on your RunPod worker
RUNPOD_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct

# Optional: different models per tier (recommended)
RUNPOD_MODEL_FAST=meta-llama/Meta-Llama-3.1-8B-Instruct
RUNPOD_MODEL_QUALITY=meta-llama/Meta-Llama-3.1-70B-Instruct
RUNPOD_MODEL_REASONING=meta-llama/Meta-Llama-3.1-70B-Instruct
RUNPOD_MODEL_LARGE=meta-llama/Meta-Llama-3.1-70B-Instruct
```

> **Important**: The `RUNPOD_BASE_URL` must end with `/openai/v1`

---

## 3. Restart / Redeploy

After setting the variables:

```bash
# Local
cd backend
python -m uvicorn app.main:app --reload
```

Or redeploy on Vercel if you're using that.

---

## 4. Test It Quickly

Run this in the backend folder:

```bash
python -c "
import os, sys
sys.path.insert(0, '.')
from app.config import RUNPOD_API_KEY, RUNPOD_BASE_URL, RUNPOD_MODEL_MAP
print('RUNPOD_API_KEY set:', bool(RUNPOD_API_KEY))
print('RUNPOD_BASE_URL :', RUNPOD_BASE_URL)
print('Model map       :', RUNPOD_MODEL_MAP)
"
```

Then send a chat request from the frontend (or use the REST endpoint) using model `fast` or `quality`.

---

## 5. What Clients See

They will only ever see these options:

- Fast
- Quality
- Reasoning
- Large Context
- Small
- Medium

Nothing about RunPod, Grok, Claude, etc. appears anywhere.

---

## Troubleshooting

- 401 / Unauthorized → wrong or missing `RUNPOD_API_KEY`
- 404 → wrong `RUNPOD_BASE_URL` (must end with `/openai/v1`)
- Model not found → `RUNPOD_MODEL` or the mapped value is wrong for what is loaded on the pod
- Slow cold starts → normal with Serverless (use a pod with "Min Workers" > 0 if you want to avoid it)

---

You're done. The backend will now route all neutral models through RunPod when the variables are set.