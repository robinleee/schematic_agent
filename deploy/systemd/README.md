# systemd units（caros-PURLEY 单机部署）

四套常驻服务，全部 `User=caros`，`RequiresMountsFor=/data`，开机自启：

| 单元 | 作用 | 端口 |
|---|---|---|
| `ollama.service` | Ollama（gemma4:26b，`OLLAMA_MODELS=/data/gemma4/models`） | 11434 |
| `neo4j.service` | Neo4j 5.26（`neo4j console`，`JAVA_HOME=/data/tools/jdk-17`） | 7474 / 7687 |
| `chromadb.service` | ChromaDB（`--path /data/schematic_agent/chroma_data`） | 8000 |
| `schematic-api.service` | FastAPI/uvicorn（`scripts/run_api.sh fg`） | 8501 |

安装（需要 sudo）：

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ollama neo4j chromadb schematic-api
```

若 ChromaDB 已由 `scripts/start_dev.sh` 手动拉起，启用 systemd 前先停掉它：
`kill "$(cat .run/chromadb.pid)"`。

日常操作：

```bash
systemctl status schematic-api neo4j ollama chromadb
sudo systemctl restart schematic-api      # 改后端代码后
journalctl -u schematic-api -f            # 也可看 logs/uvicorn.log
```

注意：

- `scripts/run_api.sh start|stop|restart` 是**手动**模式，与 systemd 抢同一端口；systemd 接管后改用 `systemctl restart schematic-api`。
  `scripts/run_api.sh status` 只读，仍可用。
- `scripts/start_dev.sh` 幂等（先探活再启动），systemd 在跑时会打印 already running，不会冲突。
- ChromaDB（:8000）必须常驻。`KnowledgeRouter` 连不上服务端时会静默回退到
  `hardware_ai_expert/data/chroma_db` 的本地 PersistentClient，它和服务端的 `chroma_data/`
  是两份不同的数据：服务端离线期间写入的知识，服务端恢复后查不到。
