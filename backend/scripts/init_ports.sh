#!/usr/bin/env bash
# Run INSIDE the RunPod GPU pod terminal (Connect → Web terminal / SSH).
# Starts Ollama on :11434 and Open WebUI on :8080 so RunPod HTTP proxies work.
set -euo pipefail

export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"

echo "=== [1/5] Ollama on 0.0.0.0:11434 ==="
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama already responding on 11434"
else
  echo "Starting ollama serve..."
  pkill -f "ollama serve" 2>/dev/null || true
  nohup env \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_KEEP_ALIVE="$OLLAMA_KEEP_ALIVE" \
    OLLAMA_NUM_PARALLEL="$OLLAMA_NUM_PARALLEL" \
    OLLAMA_MAX_LOADED_MODELS="$OLLAMA_MAX_LOADED_MODELS" \
    ollama serve >/tmp/ollama.log 2>&1 &
  for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      echo "Ollama up after ${i}s"
      break
    fi
    sleep 1
  done
fi

if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "ERROR: Ollama not up. Log:"
  tail -n 40 /tmp/ollama.log 2>/dev/null || true
  exit 1
fi
echo "tags: $(curl -sf http://127.0.0.1:11434/api/tags | head -c 120)..."

echo "=== [2/5] Pull small models if missing ==="
ollama pull qwen2.5:3b || true
ollama pull qwen2.5:7b || true

echo "=== [3/5] Open WebUI on :8080 ==="
start_webui_docker() {
  docker rm -f open-webui 2>/dev/null || true
  # On RunPod Linux, host Ollama is usually reachable at the gateway or host-gateway
  docker run -d --name open-webui \
    -p 8080:8080 \
    -e OLLAMA_BASE_URL=http://172.17.0.1:11434 \
    -e WEBUI_AUTH=false \
    -v open-webui:/app/backend/data \
    --add-host=host.docker.internal:host-gateway \
    --restart unless-stopped \
    ghcr.io/open-webui/open-webui:main
}

start_webui_pip() {
  # Fallback when Docker is not available
  python3 -m pip install -U open-webui >/tmp/openwebui-pip.log 2>&1 || \
    pip install -U open-webui >/tmp/openwebui-pip.log 2>&1
  pkill -f "open-webui" 2>/dev/null || true
  # open-webui serve binds 8080 by default in recent builds
  nohup env \
    OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    WEBUI_AUTH=false \
    open-webui serve --host 0.0.0.0 --port 8080 \
    >/tmp/open-webui.log 2>&1 &
}

if curl -sf http://127.0.0.1:8080/ >/dev/null 2>&1 \
  || curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
  echo "Something already listening on 8080"
elif command -v docker >/dev/null 2>&1; then
  echo "Starting Open WebUI via Docker..."
  start_webui_docker
  sleep 8
else
  echo "Docker missing — starting Open WebUI via pip..."
  start_webui_pip
  sleep 10
fi

echo "=== [4/5] Local health checks ==="
echo -n "11434: "
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo OK || echo FAIL
echo -n "8080:  "
if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ | grep -Eq '200|302|307'; then
  echo OK
else
  # some builds only answer after first hit
  sleep 5
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ || echo 000)
  echo "HTTP $code (if not 200/302, check: docker logs open-webui | tail -50  OR  tail -50 /tmp/open-webui.log)"
fi

echo "=== [5/5] RunPod Connect checklist ==="
echo "1. Pod page → Edit → Expose HTTP ports: 11434 AND 8080 (both required)"
echo "2. Connect → HTTP services → copy proxy URLs"
echo "3. Set on Vercel / Staff Admin → Connection:"
echo "     RUNPOD_OLLAMA_URL=https://<POD_ID>-11434.proxy.runpod.net"
echo "     RUNPOD_WEBUI_URL=https://<POD_ID>-8080.proxy.runpod.net"
echo ""
echo "From your PC after expose:"
echo "  curl -sS https://<POD_ID>-11434.proxy.runpod.net/api/tags"
echo "  curl -sI  https://<POD_ID>-8080.proxy.runpod.net/"
