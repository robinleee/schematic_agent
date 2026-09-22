# 恢复运行环境 Runbook (P0-1)

> 对应 `ROADMAP_DEVELOPMENT_CHECKLIST_2026-08.md` 的 **P0-1 统一服务启动与健康检查**。
> 核实日期: 2026-09-22。本文档反映**当前机器的真实状态**，不是从零安装指南。

## 0. 结论先行:环境已就绪

本机 **依赖与服务已完整部署**，无需重装。恢复运行 = 启动已有服务:

```bash
cd /data/schematic_agent
bash scripts/start_dev.sh      # 启动 Neo4j + Ollama + ChromaDB + FastAPI
bash scripts/healthcheck.sh    # 健康检查，期望 HEALTHY 4/4
bash scripts/stop_dev.sh       # 停止（Neo4j 由 neo4j stop，其余按 .run/*.pid kill）
```

已验证:一键启动后 `healthcheck.sh` 返回 `HEALTHY: 4/4 services`。

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
