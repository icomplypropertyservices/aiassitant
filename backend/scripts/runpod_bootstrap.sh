#!/usr/bin/env bash
# Run this ONCE inside your RunPod GPU pod terminal (Jupyter / SSH / web terminal).
# Installs Ollama + Open WebUI and pulls the fleet models for AI Business Assistant.
set -euo pipefail

echo "=== [1/4] Install Ollama ==="
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

# Listen on all interfaces so RunPod HTTP proxy can reach it
export OLLAMA_HOST=0.0.0.0:11434
# Start in background if not already running
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi
echo "Ollama up: $(curl -sf http://127.0.0.1:11434/api/tags | head -c 80 || echo 'waiting...')"

echo "=== [2/4] Pull models (Tier A — fits 24GB with room to swap) ==="
# Start small so the pod is useful immediately; pull heavier ones next.
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull deepseek-r1:8b
ollama pull qwen2.5:14b
# Optional on 24GB (quantized); skip if OOM — use A40/48GB for comfort:
# ollama pull qwen2.5:32b
# ollama pull deepseek-r1:14b

echo "=== [3/4] Open WebUI (admin console on port 8080) ==="
# Prefer Docker; fall back to pip. Bind 0.0.0.0 so RunPod proxy can reach it.
if command -v docker >/dev/null 2>&1; then
  docker rm -f open-webui 2>/dev/null || true
  docker run -d --name open-webui \
    -p 8080:8080 \
    -e OLLAMA_BASE_URL=http://172.17.0.1:11434 \
    -e WEBUI_AUTH=false \
    -v open-webui:/app/backend/data \
    --add-host=host.docker.internal:host-gateway \
    --restart unless-stopped \
    ghcr.io/open-webui/open-webui:main
  echo "Open WebUI (Docker) starting on :8080"
  sleep 5
  curl -sf -o /dev/null http://127.0.0.1:8080/ && echo "8080 local OK" || echo "8080 still starting — wait ~30s"
else
  echo "Docker not found — trying open-webui via pip..."
  if python3 -m pip install -U open-webui >/tmp/openwebui-pip.log 2>&1 \
    || pip install -U open-webui >/tmp/openwebui-pip.log 2>&1; then
    pkill -f "open-webui" 2>/dev/null || true
    nohup env OLLAMA_BASE_URL=http://127.0.0.1:11434 WEBUI_AUTH=false \
      open-webui serve --host 0.0.0.0 --port 8080 >/tmp/open-webui.log 2>&1 &
    sleep 8
    curl -sf -o /dev/null http://127.0.0.1:8080/ && echo "8080 local OK (pip)" || echo "8080 FAIL — see /tmp/open-webui.log"
  else
    echo "Could not install Open WebUI. Ollama-only is fine for the app (port 11434)."
  fi
fi

echo "=== [4/4] Done ==="
echo "Models:"
ollama list
echo ""
echo "Copy these into Vercel / backend .env:"
echo "  RUNPOD_OLLAMA_URL=https://<POD_ID>-11434.proxy.runpod.net"
echo "  RUNPOD_WEBUI_URL=https://<POD_ID>-8080.proxy.runpod.net"
echo "Find proxy URLs under Connect → HTTP services on the pod page."
