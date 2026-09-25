#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR" "$ROOT/scripts"

start_bg() {
  local name="$1"; shift
  local pidfile="$RUN_DIR/$name.pid"
  local logfile="$LOG_DIR/$name.log"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"
    return
  fi
  rm -f "$pidfile"
  nohup "$@" >>"$logfile" 2>&1 &
  echo $! >"$pidfile"
  echo "started $name (pid $!)"
}

# Neo4j is local and bundled with the project.
NEO4J_HOME="$ROOT/hardware_ai_expert/data/neo4j/neo4j-community-5.26.0"
export JAVA_HOME="${JAVA_HOME:-/data/tools/jdk-17}"
if ! "$NEO4J_HOME/bin/neo4j" status >/dev/null 2>&1; then
  "$NEO4J_HOME/bin/neo4j" start >/dev/null
  echo "started neo4j"
else
  echo "neo4j already running"
fi

# Ollama binary/model installation is environment-specific; use the local installation when present.
if command -v ollama >/dev/null 2>&1; then
  OLLAMA_BIN="$(command -v ollama)"
elif [[ -x /data/gemma4/bin/ollama ]]; then
  OLLAMA_BIN=/data/gemma4/bin/ollama
else
  echo "ERROR: ollama binary not found" >&2; exit 1
fi
if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  # OLLAMA_MODELS 必须指向实际模型库，否则 serve 会用空的 ~/.ollama/models，导致 gemma4:26b "not found"
  start_bg ollama env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="${OLLAMA_MODELS:-/data/gemma4/models}" "$OLLAMA_BIN" serve
else
  echo "ollama already running"
fi

# ChromaDB is optional for graph-only operation but required by the knowledge tier.
if ! curl -fsS --max-time 2 http://127.0.0.1:8000/api/v1/heartbeat >/dev/null 2>&1 && \
   ! curl -fsS --max-time 2 http://127.0.0.1:8000/api/v2/heartbeat >/dev/null 2>&1; then
  start_bg chromadb "$VENV/bin/chroma" run --host 127.0.0.1 --port 8000 --path "$ROOT/chroma_data"
else
  echo "chromadb already running"
fi

# FastAPI serves both the API and the built React SPA on port 8501.
if ! curl -fsS --max-time 2 http://127.0.0.1:8501/api/v1/health >/dev/null 2>&1; then
  start_bg api env PYTHONPATH="$ROOT/hardware_ai_expert" "$VENV/bin/uvicorn" api.main:app --host 0.0.0.0 --port 8501
else
  echo "api already running"
fi

"$ROOT/scripts/healthcheck.sh" || true
