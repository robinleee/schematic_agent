# 恢复运行环境 Runbook (P0-1)

> 对应 `ROADMAP_DEVELOPMENT_CHECKLIST_2026-08.md` 的 **P0-1 统一服务启动与健康检查**。
> 核实日期: 2026-09-22。本文档反映**当前机器的真实状态**，不是从零安装指南。

## 0. 结论先行:环境已就绪

本机 **依赖与服务已完整部署**，无需重装。恢复运行 = 启动已有服务:

主线界面是 React + FastAPI。先在 `frontend/` 执行 `npm run build` 生成 `dist/`，再运行下面的启动命令；FastAPI 在 :8501 托管 React SPA，`/docs` 提供 API 文档。开发模式可另在 `frontend/` 执行 `npm run dev`，Vite 在 :3000 代理 API/WS 到 :8501。遗留 `hardware_ai_expert/web_ui/app.py` (Streamlit) 不在默认启动链路中，七页面实时验收完成前保留，不归档。

```bash
cd /data/schematic_agent
bash scripts/start_dev.sh      # 启动 Neo4j + Ollama + ChromaDB + FastAPI
bash scripts/healthcheck.sh    # 健康检查，期望 HEALTHY 4/4
bash scripts/stop_dev.sh       # 停止（Neo4j 由 neo4j stop，其余按 .run/*.pid kill）
```

已验证:一键启动后 `healthcheck.sh` 返回 `HEALTHY: 4/4 services`。
该记录只证明当时四项服务可达，不能替代当前环境健康检查或 React 七页面核心操作验收。

## 1. 既有资产清单（均已存在）

- Python 虚拟环境: `.venv/`（Python 3.8.10，已装 fastapi/uvicorn/neo4j/pydantic/sentence-transformers/chromadb/openpyxl/pyyaml/python-dotenv）
- Neo4j: 项目内置 `hardware_ai_expert/data/neo4j/neo4j-community-5.26.0`（依赖 `JAVA_HOME=/data/tools/jdk-17`）
- Ollama: `/data/gemma4/bin/ollama`（模型 `gemma4:26b`）
- 前端: `frontend/node_modules/` 已装，`frontend/dist/` 已构建（FastAPI 在 :8501 直接托管该 SPA）
- 图数据: Neo4j 已载入 142,765 节点（Pin 99,140 / Component 25,376 / Net 16,318 / VectorChunk 1,901 / Community 22），含 `project_id`: `legacy`、`beet7_acceptance`

## 2. 脚本清单

- `scripts/start_dev.sh` — 幂等启动全部服务，PID 写入 `.run/*.pid`，日志写入 `logs/*.log`，末尾自动跑健康检查
- `scripts/stop_dev.sh` — 停止 api/chromadb/ollama（按 PID）+ neo4j（`neo4j stop`）
- `scripts/healthcheck.sh` — 探测 Neo4j:7474 / Ollama:11434 / ChromaDB:8000 / FastAPI:8501，输出 HEALTHY/DEGRADED
- `scripts/recovery.py` — 离线备份计划 / 受限备份执行；恢复**只生成计划**，不会写入或覆盖数据
- `scripts/check_data_quality.py` — **新增(2026-09-22)**，按 project_id 输出统一数据质量指标

```bash
.venv/bin/python scripts/check_data_quality.py                    # 全部项目
.venv/bin/python scripts/check_data_quality.py --project legacy   # 指定项目
```

## 3. 关键环境变量（`hardware_ai_expert/.env`，python-dotenv 自动加载）

- `NEO4J_URI`（默认 `bolt://localhost:7687`）/ `NEO4J_USER` / `NEO4J_PASSWORD`
- `NEO4J_READ_ONLY`（`true` 时 graph_tools 禁写，见 PRD §14.2）
- `OLLAMA_URL`（默认 `http://localhost:11434`）/ `OLLAMA_MODEL`（默认 `gemma4:26b`）
- `SCHEMATIC_EMBEDDING_MODEL`（默认 `all-MiniLM-L6-v2`，可切 `bge-m3`）/ `SCHEMATIC_EMBEDDING_DIM`
- `TIER3_ENABLED` / `TIER3_TYPE`（公网 MPN 检索开关）

## 4. 全新机器安装（仅当 `.venv`/内置服务缺失时）

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-api.txt -r hardware_ai_expert/requirements.txt
pip install sentence-transformers pyyaml openpyxl   # 注：这三项被代码依赖但未列入 requirements
# Neo4j / Ollama / JDK-17 需按 §1 路径就位；前端: cd frontend && npm ci && npm run build
```
> **依赖声明缺口**: `sentence-transformers`、`pyyaml`、`openpyxl` 被代码引用但两个 requirements 文件均未列出，建议补入。

## 5. 验收检查（P0-1）

- [x] `start_dev.sh` 可一键拉起，`healthcheck.sh` = HEALTHY 4/4
- [x] Neo4j 有数据，`check_data_quality.py` 输出与 PRD 一致（legacy: PartType 100%、全网电压 20.7% = 1689/8159）
- [x] **System 页面显示真实状态** — 已修复（见 §6），`/api/v1/system/status` 现返回 4 服务 running + 真实 data_stats

## 6. 已知问题

1. ~~**`agent_system.connection_pool` 模块缺失**~~ ✅ **已修复 (2026-09-22)**：新建 `agent_system/connection_pool.py`（提供 `get_neo4j_driver` / `get_ollama_client`，导入时 load_dotenv、凭据仅取自环境变量）；并修复 `api/routers/system.py` 中 `data_stats` 因 `get_graph_summary()` 返回 str 而恒为 0 的问题（改为直接 Cypher 统计）。实测 `/api/v1/system/status`：Neo4j/Ollama/ChromaDB/API 均 running，data_stats = 25,376 组件 / 99,140 pin / 16,318 net / PartType 99.5%。
2. **VectorChunk 无 project_id** — 1,901 个 chunk 未带 project_id，按项目统计时显示为 0，需确认 GraphRAG 是否应做项目隔离（关联 PRD §8）。**未修复**（属产品设计决策，非崩溃 bug）。

## 7. Task14: 离线备份与恢复边界（未经实际演练）

所有命令从仓库根目录执行。默认仅描述，不启动/停止服务、不读写备份；
`--target` 必须是显式绝对路径，不得与活跃数据目录重叠。不要把密码、token 放入路径或命令行。
执行前先人工核实路径、可用空间、文件权限及停机窗口。

```bash
# 仅预览；Neo4j 要求内置 bin/neo4j-admin 可执行
.venv/bin/python scripts/recovery.py backup neo4j --target /safe/backups/neo-20260925
.venv/bin/python scripts/recovery.py backup chromadb --target /safe/backups/chroma-20260925
.venv/bin/python scripts/recovery.py backup api
.venv/bin/python scripts/recovery.py backup ollama

# 仅在人工停服、确认数据库无写入后，明确指定新的目标路径才可执行备份
.venv/bin/python scripts/recovery.py backup neo4j --target /safe/backups/neo-20260925 --execute
.venv/bin/python scripts/recovery.py backup chromadb --target /safe/backups/chroma-20260925 --execute

# 恢复计划必须提供源目录和逐字确认；即使带 --execute 也会拒绝恢复
.venv/bin/python scripts/recovery.py restore neo4j --target /safe/backups/neo-20260925 --confirm 'RESTORE neo4j /safe/backups/neo-20260925'
.venv/bin/python scripts/recovery.py restore chromadb --target /safe/backups/chroma-20260925 --confirm 'RESTORE chromadb /safe/backups/chroma-20260925'
.venv/bin/python scripts/recovery.py restore api --target /safe/backups/api-deployment --confirm 'RESTORE api /safe/backups/api-deployment'
.venv/bin/python scripts/recovery.py restore ollama --target /safe/backups/ollama-models --confirm 'RESTORE ollama /safe/backups/ollama-models'
```

Neo4j 采用内置 5.26.0 的 `neo4j-admin database dump neo4j --to-path=<目录>`，
仅支持停止服务后的离线 dump；目标目录必须不存在且父目录已存在。未配置该工具则直接报不可用，
不退化为复制运行中的数据库。ChromaDB 使用 `start_dev.sh` 的 `chroma_data/` 离线目录副本；
备份时要求 :8000 和 :8501 均未监听（API 可使用 PersistentClient），拒绝覆盖目标及源目录内符号链接。
端口检查不能保证无其它写入进程，请人工确保所有写入方都已停止。
备份产物需单独核验完整性和版本匹配；失败的备份目录可能残留，脚本不会删除或重试覆盖。
恢复输出中的 Neo4j load 命令仅供人工审核，不会运行；ChromaDB 也不会自动拷回活跃目录。
不要对已有库执行覆盖式 load/copy：先制定隔离目标、回滚和版本兼容方案，再进行人工演练。

API 无独立数据存储，本脚本不备份部署配置；Ollama 模型保存在 `OLLAMA_MODELS`
（`start_dev.sh` 默认 `/data/gemma4/models`），脚本不导出模型，也不执行重新拉取或重启。
两者的 restore 只提示 `scripts/start_dev.sh` 和 `scripts/healthcheck.sh`，并非数据恢复。
`scripts/healthcheck.sh` 的 `DEGRADED: n/4` 返回码为 1，表示依赖不可达；
`/api/v1/system/status` 的单项 degraded 带通用 unavailable 原因、不泄露异常凭据，
API 自身仅在可访问该端点时显示 running。可查看 `logs/{api,ollama,chromadb}.log`
及 Neo4j 自身日志，但不要把含敏感信息的原始日志上传。本节未进行任何真实备份/恢复演练。
