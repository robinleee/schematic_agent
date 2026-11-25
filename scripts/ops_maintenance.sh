#!/usr/bin/env bash
# 需要 root 的运维操作。用法：
#   sudo bash scripts/ops_maintenance.sh chroma    # 安装并启用 chromadb.service
#   sudo bash scripts/ops_maintenance.sh backup    # 停机 dump Neo4j + 隔离实例恢复演练
#   sudo bash scripts/ops_maintenance.sh rotate    # 轮换 Neo4j 密码，同步 .env，重启依赖服务
# 可一次给多个：sudo bash scripts/ops_maintenance.sh chroma backup rotate
# 脚本不打印任何密码。
set -euo pipefail

ROOT=/data/schematic_agent
APP_USER=caros
PY="$ROOT/.venv/bin/python"
NEO_HOME="$ROOT/hardware_ai_expert/data/neo4j/neo4j-community-5.26.0"
ENV_FILE="$ROOT/hardware_ai_expert/.env"
BACKUP_ROOT=/data/backups/neo4j
HERMES_UNIT=hermes-gateway-cfa4b284   # 托管 schematic MCP Server 的 Hermes 网关
export JAVA_HOME=/data/tools/jdk-17

[ "$(id -u)" = 0 ] || { echo "请用 sudo 运行" >&2; exit 1; }
as_app() { sudo -u "$APP_USER" -H env JAVA_HOME="$JAVA_HOME" "$@"; }

wait_port() {  # wait_port <port> <seconds>
  for _ in $(seq 1 "$2"); do
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0
    sleep 1
  done
  echo "端口 $1 在 $2 秒内未就绪" >&2; return 1
}

# 统计节点/关系数。参数：bolt 地址，auth 模式（env=读 .env 账号，none=无认证）
count_graph() {
  as_app "$PY" - "$1" "$2" <<'PY'
import os, sys, json
from dotenv import load_dotenv
from neo4j import GraphDatabase
uri, mode = sys.argv[1], sys.argv[2]
load_dotenv("/data/schematic_agent/hardware_ai_expert/.env")
auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")) if mode == "env" else None
d = GraphDatabase.driver(uri, auth=auth)
q = {lbl: f"MATCH (n:{lbl}) RETURN count(n) AS c" for lbl in ("Component", "Pin", "Net", "Project")}
q["_nodes"] = "MATCH (n) RETURN count(n) AS c"
q["_rels"] = "MATCH ()-[r]->() RETURN count(r) AS c"
with d.session() as s:
    print(json.dumps({k: s.run(v).single()["c"] for k, v in q.items()}, sort_keys=True))
d.close()
PY
}

do_chroma() {
  echo "== ChromaDB systemd 单元"
  if [ -f "$ROOT/.run/chromadb.pid" ] && kill -0 "$(cat "$ROOT/.run/chromadb.pid")" 2>/dev/null; then
    kill "$(cat "$ROOT/.run/chromadb.pid")"; sleep 3
  fi
  install -m 644 "$ROOT/deploy/systemd/chromadb.service" /etc/systemd/system/chromadb.service
  systemctl daemon-reload
  systemctl enable --now chromadb
  wait_port 8000 60
  systemctl is-active chromadb
}

do_backup() {
  local ts dir drill before after
  ts=$(date +%Y%m%d-%H%M%S); dir="$BACKUP_ROOT/$ts"; drill="$dir/drill"
  install -d -o "$APP_USER" -g "$APP_USER" "$BACKUP_ROOT" "$dir"
  echo "== 1/4 记录源库计数"
  before=$(count_graph bolt://127.0.0.1:7687 env); echo "$before" | tee "$dir/counts_source.json"

  echo "== 2/4 停机 dump（API 与 Neo4j 短暂不可用）"
  systemctl stop schematic-api neo4j
  # dump 失败也要把服务拉回来
  trap 'systemctl start neo4j; wait_port 7687 120 && systemctl start schematic-api' EXIT
  as_app "$NEO_HOME/bin/neo4j-admin" database dump neo4j --to-path="$dir"
  systemctl start neo4j; wait_port 7687 120; systemctl start schematic-api
  trap - EXIT
  ls -la "$dir"/neo4j.dump

  echo "== 3/4 在隔离实例中恢复（127.0.0.1:17687，独立目录，不影响生产）"
  as_app mkdir -p "$drill"
  as_app rsync -a --exclude data --exclude logs --exclude run "$NEO_HOME/" "$drill/"
  as_app mkdir -p "$drill/data" "$drill/logs" "$drill/run"
  as_app tee -a "$drill/conf/neo4j.conf" >/dev/null <<'CONF'

# ---- restore drill overrides ----
dbms.security.auth_enabled=false
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:17687
server.http.listen_address=127.0.0.1:17474
server.https.enabled=false
CONF
  as_app env NEO4J_HOME="$drill" "$drill/bin/neo4j-admin" database load neo4j \
    --from-path="$dir" --overwrite-destination=true
  as_app env NEO4J_HOME="$drill" "$drill/bin/neo4j" start
  wait_port 17687 120
  sleep 5
  after=$(count_graph bolt://127.0.0.1:17687 none); echo "$after" | tee "$dir/counts_restored.json"
  as_app env NEO4J_HOME="$drill" "$drill/bin/neo4j" stop

  echo "== 4/4 校验"
  if [ "$before" = "$after" ]; then
    echo "RESTORE_OK 计数一致；dump：$dir/neo4j.dump"
    rm -rf "$drill"
  else
    echo "RESTORE_MISMATCH 源库与恢复库计数不一致，保留 $drill 供排查" >&2; exit 2
  fi
}

do_rotate() {
  echo "== 轮换 Neo4j 密码"
  as_app "$PY" - "$ENV_FILE" <<'PY'
import os, re, secrets, shutil, sys, time
from dotenv import dotenv_values
from neo4j import GraphDatabase
path = sys.argv[1]
env = dotenv_values(path)
uri = env.get("NEO4J_URI") or "bolt://localhost:7687"
user, old = env.get("NEO4J_USER") or "neo4j", env["NEO4J_PASSWORD"]
ro_user = env.get("NEO4J_READONLY_USER")
new_main, new_ro = secrets.token_urlsafe(24), secrets.token_urlsafe(24)

# 先写好新 .env（不覆盖），数据库改密成功后再原子替换；旧文件留 0600 备份
def put(t, key, val):
    pat = re.compile(rf"^{key}=.*$", re.M)
    return pat.sub(lambda _: f"{key}={val}", t) if pat.search(t) else t.rstrip("\n") + f"\n{key}={val}\n"
text = put(open(path, encoding="utf-8").read(), "NEO4J_PASSWORD", new_main)
if ro_user:
    text = put(text, "NEO4J_READONLY_PASSWORD", new_ro)
backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(path, backup); os.chmod(backup, 0o600)
tmp = path + ".new"
with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
    fh.write(text)

d = GraphDatabase.driver(uri, auth=(user, old))
with d.session(database="system") as s:
    others = [r["user"] for r in s.run("SHOW USERS") if r["user"] != user]
    for u in others:
        # 没有在 .env 里配置的账号改成不落盘的随机密码，等同停用
        pw = new_ro if u == ro_user else secrets.token_urlsafe(24)
        s.run(f"ALTER USER `{u}` SET PASSWORD $p CHANGE NOT REQUIRED", p=pw).consume()
    s.run("ALTER CURRENT USER SET PASSWORD FROM $old TO $new", old=old, new=new_main).consume()
d.close()
os.replace(tmp, path)
d = GraphDatabase.driver(uri, auth=(user, new_main)); d.verify_connectivity(); d.close()
print(f"ROTATED users={[user] + others} env_backup={backup}")
PY
  systemctl restart schematic-api
  systemctl restart "$HERMES_UNIT"   # MCP Server 是它的子进程，启动时读 .env
  wait_port 8501 120
  sleep 3
  curl -fsS http://127.0.0.1:8501/api/v1/system/status >/dev/null && echo "API OK（新密码）"
}

[ $# -gt 0 ] || { sed -n 2,7p "$0"; exit 1; }
for step in "$@"; do
  case "$step" in
    chroma) do_chroma ;;
    backup) do_backup ;;
    rotate) do_rotate ;;
    *) echo "未知步骤：$step" >&2; exit 1 ;;
  esac
done
