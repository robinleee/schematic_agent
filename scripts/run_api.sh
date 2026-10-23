#!/usr/bin/env bash
# schematic_agent FastAPI 启动脚本
#
# 为什么要有这个脚本：SPA 由 FastAPI 直接托管时，Vite 产物 `<script type="module" crossorigin>`
# 属于 CORS 请求会带 Origin，而 api/security.py 的 SecurityBoundary 在 API_CORS_ORIGINS 为空时
# 对任何带 Origin 的请求返回 403 → /assets/*.js 全 403 → 页面白屏。这里把必需的 origin 固化。
#
# 用法：
#   scripts/run_api.sh            # 后台启动（默认 8501）
#   scripts/run_api.sh fg         # 前台运行（调试）
#   scripts/run_api.sh stop|restart|status
#   PORT=8600 scripts/run_api.sh  # 换端口
#   API_CORS_ORIGINS="http://x:8501" scripts/run_api.sh   # 覆盖默认 origin 列表
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/uvicorn}"
PORT="${PORT:-8501}"
HOST="${HOST:-0.0.0.0}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/uvicorn.log"
PID_FILE="$LOG_DIR/uvicorn.$PORT.pid"

export PYTHONPATH="$ROOT/hardware_ai_expert${PYTHONPATH:+:$PYTHONPATH}"
export API_SECURITY_MODE="${API_SECURITY_MODE:-offline}"
# 默认放行本机 / 内网 IP / 运维跳板机的外部访问地址；外部部署请自行覆盖。
export API_CORS_ORIGINS="${API_CORS_ORIGINS:-http://127.0.0.1:${PORT},http://localhost:${PORT},http://192.168.66.238:${PORT},http://172.20.98.190:${PORT},http://127.0.0.1:3000,http://localhost:3000}"

pid_on_port() {
  ss -ltnp 2>/dev/null | grep ":${PORT} " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true
}

is_healthy() {
  curl -sf -m 5 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1
}

case "${1:-start}" in
  fg)
    exec "$PYTHON" api.main:app --host "$HOST" --port "$PORT"
    ;;
  start)
    if pid="$(pid_on_port)" && [ -n "$pid" ]; then
      echo "端口 ${PORT} 已被 pid ${pid} 占用；如需重启用 scripts/run_api.sh restart"
      exit 1
    fi
    setsid nohup "$PYTHON" api.main:app --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 </dev/null &
    echo $! >"$PID_FILE"
    for _ in $(seq 1 30); do
      sleep 1
      if is_healthy; then
        echo "started pid=$(cat "$PID_FILE") port=${PORT} health=ok log=${LOG_FILE}"
        exit 0
      fi
    done
    echo "启动超时（30s）；最后 20 行日志：" >&2
    tail -20 "$LOG_FILE" >&2
    exit 1
    ;;
  stop)
    pid="$(pid_on_port)"
    if [ -z "$pid" ]; then
      echo "端口 ${PORT} 上没有进程"
      exit 0
    fi
    kill "$pid"
    for _ in $(seq 1 15); do
      sleep 1
      [ -z "$(pid_on_port)" ] && { echo "stopped pid=$pid"; exit 0; }
    done
    echo "pid $pid 未在 15s 内退出" >&2
    exit 1
    ;;
  restart)
    "$0" stop || true
    exec "$0" start
    ;;
  status)
    pid="$(pid_on_port)"
    if [ -z "$pid" ]; then
      echo "down (port ${PORT})"
      exit 1
    fi
    if is_healthy; then
      echo "up pid=${pid} port=${PORT} health=ok"
    else
      echo "degraded pid=${pid} port=${PORT} health=fail"
      exit 2
    fi
    ;;
  *)
    echo "用法: $0 [start|stop|restart|status|fg]" >&2
    exit 64
    ;;
esac
