#!/usr/bin/env bash
# WS6 doctor: checks the pieces the full stack needs before `make up`.
# Safe to run any time; it only pings/list endpoints, it never calls the model.
set -uo pipefail

fail=0
ok() { printf '  \033[32m[ok]\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31m[FAIL]\033[0m %s\n' "$1"; fail=1; }

echo "== Kallang WS6 doctor =="

# 1. Docker daemon and its memory cap.
if docker info >/dev/null 2>&1; then
  ok "docker daemon running"
  mem_bytes=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  if [ "${mem_bytes:-0}" -gt 0 ] 2>/dev/null; then
    mem_gib=$((mem_bytes / 1024 / 1024 / 1024))
    printf '       docker memory cap: %s GiB\n' "$mem_gib"
    if [ "$mem_gib" -ge 4 ]; then ok "memory >= 4 GiB"; else bad "memory below 4 GiB (increase in Docker Desktop)"; fi
  else
    bad "could not read the docker memory cap"
  fi
else
  bad "docker daemon not running (start Docker Desktop)"
fi

# 2. Ollama reachable from the host (list endpoint only, no model call).
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  ok "ollama reachable from host on 127.0.0.1:11434"
else
  bad "ollama not reachable on 127.0.0.1:11434"
fi

# 3. Ollama reachable from inside a container (host.docker.internal) — same list endpoint.
if docker run --rm --entrypoint python python:3.12-slim -c \
  "import urllib.request,sys; urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=3)" >/dev/null 2>&1; then
  ok "ollama reachable from inside a container (host.docker.internal)"
else
  bad "containers cannot reach host.docker.internal:11434 (see README/HANDOFF)"
fi

# 4. The configured model is pulled.
if tags=$(curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags 2>/dev/null); then
  if printf '%s' "$tags" | grep -q '"gemma4:12b"'; then
    ok "model gemma4:12b is pulled"
  else
    bad "gemma4:12b is not pulled (ollama pull gemma4:12b)"
  fi
else
  bad "could not list ollama models"
fi

# 5. The ports the stack binds to must be free.
for port in 8080 8501; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    bad "port $port is already in use (free it before make up)"
  else
    ok "port $port is free"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "doctor: some checks failed"
  exit 1
fi
echo "doctor: all checks passed"
