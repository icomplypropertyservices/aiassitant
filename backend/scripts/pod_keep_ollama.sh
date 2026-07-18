#!/usr/bin/env bash
# Run on the RunPod GPU pod (web terminal or SSH) after every pod start/restart.
# Keeps Ollama on 0.0.0.0:11434 so RunPod HTTP proxy works.
set -euo pipefail

export OLLAMA_HOST=0.0.0.0:11434
export OLLAMA_KEEP_ALIVE=24h

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

# If already healthy, exit
if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama already up on :11434"
  ollama list || true
  exit 0
fi

echo "Starting ollama serve..."
nohup env OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=24h ollama serve >/tmp/ollama.log 2>&1 &
sleep 4

for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama healthy"
    break
  fi
  sleep 1
done

curl -sf http://127.0.0.1:11434/api/tags || { echo "FAILED: Ollama not responding"; tail -20 /tmp/ollama.log; exit 1; }

# Ensure core models
ollama pull qwen2.5:3b || true
ollama pull qwen2.5:7b || true

echo "Models:"
ollama list
echo "OK — expose HTTP port 11434 in RunPod Connect if not already."
echo "Proxy: https://<POD_ID>-11434.proxy.runpod.net/api/tags"
