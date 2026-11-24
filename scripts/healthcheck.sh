#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pass=0; total=0
check() {
  local name="$1" url="$2"; total=$((total+1))
  if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
    echo "OK   $name ($url)"; pass=$((pass+1))
  else
    echo "FAIL $name ($url)"
  fi
}
check "Neo4j HTTP" "http://127.0.0.1:7474"
check "Ollama" "http://127.0.0.1:11434/api/tags"
if curl -fsS --max-time 3 http://127.0.0.1:8000/api/v1/heartbeat >/dev/null 2>&1 || \
   curl -fsS --max-time 3 http://127.0.0.1:8000/api/v2/heartbeat >/dev/null 2>&1; then
  echo "OK   ChromaDB (http://127.0.0.1:8000)"; pass=$((pass+1))
else
  echo "FAIL ChromaDB (http://127.0.0.1:8000)"
fi
total=$((total+1))
check "FastAPI" "http://127.0.0.1:8501/api/v1/health"
if [[ "$pass" -eq "$total" ]]; then
  echo "HEALTHY: $pass/$total services"; exit 0
fi
echo "DEGRADED: $pass/$total services"; exit 1
