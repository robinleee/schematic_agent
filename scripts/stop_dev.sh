#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"

for name in api chromadb ollama; do
  pidfile="$RUN_DIR/$name.pid"
  if [[ -f "$pidfile" ]]; then
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      echo "stopped $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
done

NEO4J_HOME="$ROOT/hardware_ai_expert/data/neo4j/neo4j-community-5.26.0"
if "$NEO4J_HOME/bin/neo4j" status >/dev/null 2>&1; then
  "$NEO4J_HOME/bin/neo4j" stop >/dev/null
  echo "stopped neo4j"
fi
