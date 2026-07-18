#!/usr/bin/env bash
set -e
echo "=== start WebUI 8080 ==="
python3 -m venv /opt/openwebui-venv
/opt/openwebui-venv/bin/pip install -U pip open-webui
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export WEBUI_AUTH=false
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8080/tcp 2>/dev/null || true
fi
nohup /opt/openwebui-venv/bin/open-webui serve --host 0.0.0.0 --port 8080 >/tmp/open-webui.log 2>&1 &
echo "started pid $!"
for i in $(seq 1 45); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ || echo 000)
  echo "try $i http=$code"
  case "$code" in 200|302|307) break ;; esac
  sleep 4
done
tail -30 /tmp/open-webui.log || true
(ss -lntp 2>/dev/null || true) | grep -E "11434|8080" || true
curl -sI http://127.0.0.1:8080/ | head -8 || true
