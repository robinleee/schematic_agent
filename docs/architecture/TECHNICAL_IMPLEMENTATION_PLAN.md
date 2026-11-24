# schematic_agent — 技术实现方案

> 版本: V2.0 | 日期: 2026-06-29 | 状态: 以当前代码基线 (commit `d0c746d`) 全面重写
> 基线文档: PRD V5.1 | 前序版本: V1.0 (2026-04-29, 基于 PRD V3.0, 已作废)

---

## 0. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| V1.0 | 2026-04-29 | 初始版本，基于 PRD V3.0 + Solution V2.0 编制 | Jarvis |
| V2.0 | 2026-06-29 | 以 commit `d0c746d` 代码事实为基准全面重写：更新架构图（FastAPI+React+WS、AgentOrchestrator、自研 graph_rag、Neo4j 原生向量索引）、模块状态表、路线图；删除明文密码；回写全部已确认设计决策 | Jarvis |

---

## 1. 项目概述

### 1.1 目标
基于 EDA 异构数据图谱 + 自研 GraphRAG + ReAct Agent 的硬件原理图审查与故障诊断系统。

### 1.2 核心闭环
- **左移防御**: 原理图审查（去耦、上拉、ESD、AMR 降额、PinMux、电压兼容、电源完整性、差分对、连通性）
- **右移排障**: 故障诊断（电源链路追踪、信号路径中断溯源、共因失效定位、电源时序分析）
- **终身学习**: 分级知识检索（Tier0 GraphRAG / Tier1 本地 / Tier2 内网 / Tier3 公网）+ Datasheet HITL 审批

### 1.4 当前完成度: ~83%
（基于 PRD_GAP_ANALYSIS_V2 评估，详见第 7 节路线图）

---

## 2. 系统架构

### 2.1 架构总览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          系统架构总览 (V2.0)                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌───────────────────────┐        ┌──────────────────────────────────────┐  │
│  │   React + TypeScript  │  HTTP  │        FastAPI Backend (:8501)        │  │
│  │   前端 (frontend/)    │◄──────►│   api/main.py + 7 routers + CORS      │  │
│  │   7 页面 / Ant Design │  WS    │   api/websocket/chat_ws.py (流式对话)  │  │
│  │   [✅ done]           │◄──────►│   [✅ done]                           │  │
│  └───────────┬───────────┘        └─────────────────┬────────────────────┘  │
│              │  useChatWebSocket hook                 │                       │
│              │                                        ▼                       │
│              │            ┌───────────────────────────────────────────┐      │
│              │            │          AgentOrchestrator                 │      │
│              │            │   agent_system/agent_orchestrator.py       │      │
│              │            │   [✅ done] 路由 → 专项 Agent / fallback    │      │
│              │            └─────┬───────────┬───────────┬─────────────┘      │
│              │         ┌────────┘           │           └────────┐            │
│              │         ▼                    ▼                    ▼            │
│              │  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐      │
│              │  │ ReviewAgent │    │DiagnosisAgent│    │  QueryAgent  │      │
│              │  │  9 tools    │    │  10 tools    │    │  8 tools     │      │
│              │  └──────┬──────┘    └──────┬───────┘    └──────┬───────┘      │
│              │         │  fallback        │                   │              │
│              │         └──────────────────┼───────────────────┘              │
│              │                            ▼                                   │
│              │            ┌───────────────────────────────────────────┐      │
│              │            │          ReActAgent (primary)              │      │
│              │            │   agent_system/react_agent.py (786行)      │      │
│              │            │   Thought→Action→Observation, MAX_STEPS=10 │      │
│              │            │   16 graph tools + run_review + search_kb  │      │
│              │            │   [✅ done]                               │      │
│              │            └─────┬─────────────────┬─────────────────┘        │
│              │                  │                 │                         │
│              │     ┌────────────▼───┐    ┌────────▼──────────┐              │
│              │     │ Review Engine  │    │   Graph Tools     │              │
│              │     │  9 templates   │    │  16 Cypher tools  │              │
│              │     │  24 rules      │    │  project_id 隔离  │              │
│              │     │  热更新(mtime) │    │  CYPHER_ROW_LIMIT │              │
│              │     │  [✅ done]     │    │    = 500          │              │
│              │     └────────────────┘    └────────┬──────────┘              │
│              │                                   │                         │
│              │            ┌──────────────────────▼───────────────────┐      │
│              │            │     KnowledgeRouter (分级检索)            │      │
│              │            │  Tier0: GraphRAG (阈值0.3)                │      │
│              │            │  Tier1: 本地知识库  Tier2: 内网PLM        │      │
│              │            │  Tier3: 公网MPN检索 (9供应商模板)         │      │
│              │            └──────────────────────┬───────────────────┘      │
│              │                                   │                         │
│              │            ┌──────────────────────▼───────────────────┐      │
│              │            │     自研 GraphRAG (graph_rag/)            │      │
│              │            │  GraphRAGPipeline: local/global/graph/auto│      │
│              │            │  Neo4jVectorIndexer (原生向量索引,384维)  │      │
│              │            │  HardwareEntityExtractor + Louvain(22社区)│      │
│              │            │  [✅ done] 1901 chunks / 10504 DESCRIBES  │      │
│              │            └──────────────────────┬───────────────────┘      │
│              │                                   │                         │
│  ┌───────────▼───────────────────────────────────▼─────────────────────┐    │
│  │                     Neo4j 5.26 Graph DB                              │    │
│  │  [✅] 12,688 Components | 49,570 Pins | 8,159 Nets                  │    │
│  │  [✅] Pin.Type 100% | PartType UNKNOWN=1 | POWERED_BY=593           │    │
│  │  [✅] 原生向量索引 (VectorChunk) | 22 Communities                    │    │
│  │  [✅] project_id 全链路多项目隔离                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     ETL Pipeline (etl_pipeline/)                     │    │
│  │  [✅] 网表解析 → PartType 标准化 → 电压标注 → 电源树 → Quality Guard │    │
│  │  [✅] quality_guard.py: PartType≥90% + 核心网络识别 (类型级)         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │           LLM Backend: Ollama gemma4:26b (:11434)                    │    │
│  │  [✅] 51.9 tok/s | LLM 缓存 TTL 1h + 50% 淘汰 | Embedding 同源       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  遗留双轨: web_ui/app.py (Streamlit, 1973行) — 保留为 fallback       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心技术栈（已确认基线）

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design | 7 页面，WebSocket 流式对话，暗/亮主题 |
| 后端 | FastAPI + Uvicorn (:8501) | 7 routers + WebSocket，CORS allow-all |
| Agent | ReActAgent (自研) + AgentOrchestrator | 非硬编码，LLM 驱动 Thought→Action→Observation |
| 审查引擎 | 三层（Template+Config+Knowledge） | 9 模板 / 24 规则 / YAML 配置 / mtime 热更新 |
| GraphRAG | 自研 graph_rag/ (非 LlamaIndex) | Neo4j 原生向量索引，local/global/graph/auto 检索 |
| 图数据库 | Neo4j 5.26 Community Edition | 图 + 向量双引擎，project_id 多项目隔离 |
| LLM | Ollama gemma4:26b (:11434) | 本地推理，数据安全红线；vLLM 因 T4 驱动不兼容搁置 |
| Embedding | sentence-transformers all-MiniLM-L6-v2 (384维) | 当前与 gemma4:26b 同源，专业 embedding 模型为待优化项 |

**与 PRD V5.0 原始要求的偏差（已在 PRD V5.1 正式回写为基线决策）：**
- PRD 要求 `llama-index + llama-index-graph-stores-neo4j` → 实际自研 `graph_rag/`（Neo4j 原生向量索引，非 ChromaDB 双写）
- PRD 要求 vLLM + Llama3-70B/Qwen → 实际 Ollama gemma4:26b（vLLM 因 T4 驱动不兼容）
- PRD Phase 3 指定 Streamlit UI → 实际 React + TypeScript（Streamlit 降级为遗留双轨）

---

## 3. 模块完成状态详表

### 3.1 数据底座层 (ETL Pipeline)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| Cadence 网表解析 | ✅ | `chip_parser.py`, `prt_parser.py`, `net_parser.py` | 完整解析 pstchip/pstxprt/pstxnet |
| 数据融合注入 | ✅ | `main_etl.py` | Pydantic 校验 + UNWIND MERGE 批量注入 |
| **数据质量守门** | ✅ | `quality_guard.py` | PartType≥90% + 核心网络识别(类型级) 阈值熔断 |
| **PartType 标准化** | ✅ | `part_type_standardizer.py`, `refine_passive_types.py` | PartType UNKNOWN 从 120 降至 1 |
| **Pin.Type 注入** | ✅ | `main_etl.py` | PINUSE→Pin.Type 映射已实现，覆盖率 100% |
| **电源树生成** | ✅ | `generate_power_tree.py` | `[:POWERED_BY]` 关系已创建 (593 条) |
| **电压标注扩展** | ✅ | `expand_voltage_annotation.py` | POWER 网络覆盖率 95.7%，全网 20.7% |
| **BOM CSV 导入** | ❌ | — | **缺失**: CSV BOM 模板 + Description 字段映射 (P0 待开发) |

### 3.2 知识外脑层 (自研 GraphRAG)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| **向量索引** | ✅ | `graph_rag/indexers/vector_indexer.py` | Neo4j 原生向量索引 (384维, cosine)，1901 VectorChunk |
| **实体抽取** | ✅ | `graph_rag/indexers/entity_extractor.py` | LLM 实体抽取 + 正则降级 |
| **社区检测** | ✅ | `graph_rag/indexers/community_detector.py` | Louvain 算法，22 个社区 |
| **本地检索** | ✅ | `graph_rag/retrievers/local_retriever.py` | 向量相似度检索 |
| **全局检索** | ✅ | `graph_rag/retrievers/global_retriever.py` | 社区报告检索 |
| **图检索** | ✅ | `graph_rag/retrievers/graph_retriever.py` | 多跳遍历 (RefDes/MPN/Net) |
| **混合路由** | ✅ | `graph_rag/pipeline.py` | `query(mode=auto)` 自动选择 + hybrid fusion |
| DESCRIBES 关系 | ✅ | — | VectorChunk→Component，10,504 条 |
| ChromaDB | ⚠️ | `data/chroma_db/` | 仅遗留迁移源，活跃路径已切换至 Neo4j |
| **专业 Embedding** | ❌ | — | **缺失**: 当前用 all-MiniLM-L6-v2，建议升级 bge-m3 (P0 待开发) |
| **LlamaIndex 集成** | ❌ | — | 未采用，自研方案已满足功能需求（评估迁移 ROI） |

### 3.3 检索路由层 (Tiered Search)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| Tier 0 (GraphRAG) | ✅ | `knowledge_router.py` | KnowledgeRouter 阈值 0.3 集成 |
| Tier 1 (本地知识库) | ✅ | `knowledge_router.py` | 本地语义检索 |
| Tier 2 (内网 PLM) | ⚠️ | `knowledge_router.py` | 接口占位，无实际 PLM 集成 |
| Tier 3 (公网 MPN) | ✅ | `tier3_retriever.py` | 轻量纯 Python，9 供应商模板，39 单元测试 |
| 脱敏逻辑 | ⚠️ | — | MPN 提取逻辑有，完整上下文剥离未验证 |

### 3.4 Agent 核心层

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| **ReActAgent (主)** | ✅ | `react_agent.py` (786行) | Thought→Action→Observation, MAX_STEPS=10，16 tools |
| **AgentOrchestrator** | ✅ | `agent_orchestrator.py` (294行) | 路由→ReviewAgent/DiagnosisAgent/QueryAgent，fallback ReActAgent |
| **ReviewAgent** | ✅ | `agent_orchestrator.py:71` | 9 tools，审查专项 |
| **DiagnosisAgent** | ✅ | `agent_orchestrator.py:119` | 10 tools，故障树分析框架 |
| **QueryAgent** | ✅ | `agent_orchestrator.py:169` | 8 只读 tools |
| 复合意图拆解 | ✅ | `react_agent.py:541` | `_detect_composite_intent` 多任务队列 |
| 审查任务流 | ✅ | `react_agent.py:102` | ReviewRuleEngine per-project_id 缓存 |
| 诊断任务流 | ✅ | `react_agent.py` | trace_power_chain + trace_fault_root |
| 查询任务流 | ✅ | `react_agent.py:139` | KnowledgeRouter(project_id) 集成 |
| LLM 缓存 | ✅ | `llm_client.py` | TTL 1h + 50% 淘汰 |
| **Self-Correction** | ❌ | — | **缺失**: 显式 Cypher 查询重试/参数放宽机制 (P1 待开发) |
| 遗留状态机 | ⚠️ | `agent_core.py` (1366行) | HardwareAgent 保留为 fallback，默认委托 ReActAgent |

### 3.5 审查规则引擎 (Review Engine)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| 模板层 (Layer 1) | ✅ | `templates/*.py` | **9 模板**: decap, pullup, esd, amr, pinmux, voltage_compat, power_integrity, connectivity, diff_pair |
| 配置层 (Layer 2) | ✅ | `config/default_rules.yaml` | **24 条规则**，YAML 配置 |
| 知识层 (Layer 3) | ⚠️ | `datasheet_hitl.py`, `hitl_workflow.py` | HITL 管道已实现，端到端闭环未实测 |
| **规则热更新** | ✅ | `react_agent.py:102` | ReviewRuleEngine per-project_id 单例 + mtime 检测自动重载 |
| 白名单管理 | ✅ | `whitelist.py` | 读写逻辑 + Web UI 交互 |
| 报告生成 | ✅ | `engine.py` | Markdown 格式报告 + BOS 导出 |

### 3.6 图谱工具层 (Graph Tools)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| 器件属性查询 | ✅ | `get_component_nets` | RefDes→网络列表 |
| 网络器件查询 | ✅ | `get_net_components` | Net→器件列表 (智能聚合) |
| 电源域查询 | ✅ | `get_power_domain` | 电压等级聚合 |
| 电源树查询 | ✅ | `get_power_tree` | `[:POWERED_BY]` 向下钻取 |
| I2C 器件查询 | ✅ | `get_i2c_devices` | I2C 总线扫描 |
| 信号路径追踪 | ✅ | `get_signal_path` | shortestPath 算法 |
| 图摘要 | ✅ | `get_graph_summary` | 统计信息 |
| **差分对发现** | ✅ | `discover_diff_pairs` | 实测 224 对 (218 完整 / 6 不完整) |
| **差分对追踪** | ✅ | `trace_differential_pair` | P/N 一致性检查 |
| **共因失效图** | ✅ | `get_common_cause_graph` | 电源链路/故障溯源 |
| **共因风险评分** | ✅ | `common_cause_risk_score` | 风险量化 |
| **电源链路追踪** | ✅ | `trace_power_chain` | 诊断专用 |
| **故障根因追踪** | ✅ | `trace_fault_root` | 诊断专用 |
| 截断机制 | ✅ | `graph_tools.py` | `CYPHER_ROW_LIMIT=500` + 智能聚合 (已废除 MAX_RESULTS=50 硬截断) |
| **project_id 隔离** | ✅ | `graph_tools.py` | 全链路多项目数据隔离 |
| 周边器件查询 | ⚠️ | — | `find_connected_peripherals` 未实现 (P2) |

### 3.7 交互前端 (React + TypeScript)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| **React 前端** | ✅ | `frontend/src/` | FastAPI + React 前后端分离 |
| Chat 页面 | ✅ | `frontend/src/pages/Chat/` | WebSocket 流式对话 (useChatWebSocket hook) |
| Review 页面 | ✅ | `frontend/src/pages/Review/` | 审查结果展示 |
| HITL 页面 | ✅ | `frontend/src/pages/HITL/` | 白名单审批操作看板 |
| Knowledge 页面 | ✅ | `frontend/src/pages/Knowledge/` | 知识库管理 |
| ETL 页面 | ✅ | `frontend/src/pages/ETL/` | 网表上传与 ETL 触发 |
| Graph 页面 | ✅ | `frontend/src/pages/Graph/` | graph_viz 多维度可视化 (电源链路/故障溯源/共因失效/组件关系/电源树) |
| System 页面 | ✅ | `frontend/src/pages/System/` | 系统状态 |
| 推理链路展示 | ✅ | `components/ReasoningChain/` | 时间线布局 + 折叠面板 + 步骤图标 |
| 图谱可视化联动 | ✅ | `pages/Graph/` | Neo4j 局部网络渲染 |
| 主题 | ✅ | `styles/` | Ant Design 暗色/亮色 |
| 遗留 Streamlit | ⚠️ | `web_ui/app.py` (1973行) | 保留为 fallback 双轨 |
| **前后端联调** | ⚠️ | — | WebSocket 地址硬编码 ws://localhost:8501 未修复 (P0) |

### 3.8 API 后端 (FastAPI)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| FastAPI App | ✅ | `api/main.py` | :8501, CORS allow-all, docs at /docs |
| Chat Router | ✅ | `api/routers/chat.py` | 对话接口 |
| Review Router | ✅ | `api/routers/review.py` | 审查接口 |
| HITL Router | ✅ | `api/routers/hitl.py` | 审批接口 (get_pending_list) |
| Knowledge Router | ✅ | `api/routers/knowledge.py` | 知识库接口 |
| ETL Router | ✅ | `api/routers/etl.py` | ETL 触发接口 |
| Graph Router | ✅ | `api/routers/graph.py` | 图谱查询接口 |
| System Router | ✅ | `api/routers/system.py` | 系统状态接口 |
| **WebSocket** | ✅ | `api/websocket/chat_ws.py` | 流式对话推送 |

---

## 4. 关键数据质量状态

### 4.1 当前数据状态 (Beet7 网表)

| 指标 | V1 (05-14) | V2 (06-08) | 状态 |
|------|------------|------------|------|
| Components | 12,688 | 12,688 | ✅ |
| Pins | 49,570 | 49,570 | ✅ |
| Nets | 8,159 | 8,159 | ✅ |
| PartType UNKNOWN | 120 | **1** | ✅ 已修复 |
| Pin.Type 覆盖率 | 100% | **100%** | ✅ 已修复 |
| POWERED_BY 关系 | 955 | **593** | ✅ (ETL schema 演进) |
| 网络电压标注率 (全网) | 17.3% | **20.7%** | ⚠️ (POWER 网 95.7%) |
| AMR 电容耐压覆盖率 | 85% | **83.1%** | ⚠️ (统计口径待统一) |
| VectorChunk | 0 | **1,901** | ✅ |
| DESCRIBES 关系 | 0 | **10,504** | ✅ |
| Communities | 0 | **22** | ✅ |
| Review 规则数 | 14 | **24** | ✅ |
| 测试用例 | ~179 | **283** (tests/) + 22 (root) | ✅ |

### 4.2 Quality Guard 当前实现与已知缺陷

`quality_guard.py` 当前实现两项阈值熔断：
- **PartType 标准化覆盖率 ≥ 90%** — 按 UNKNOWN 器件数统计，已达标
- **核心网络识别率 = 100%** — ✅ **V5.1 已改为网络级校验**：逐个枚举匹配 CORE_NET_PATTERNS 的具体网络名，校验每个核心网络具有有效连通性（≥2 pin，排除 stub/解析伪影），并硬性要求电源类与接地类核心网络均存在。实测 Beet7 网表：1068/1076 有效连通，8 个疑似 stub（旧类型级校验会误判为 100% 通过）。详见 PRD V5.1 §13.1。

---

## 5. 技术债务与风险

### 5.1 技术债务

| 债务项 | 影响 | 偿还计划 |
|--------|------|----------|
| Embedding 用生成模型同源产出 | GraphRAG 检索质量受限 (头号风险) | P0: 部署 bge-m3 专业 embedding 模型 |
| 前后端 WebSocket 地址硬编码 | 部署后前端无法连接 | P0: 改为相对路径 / 环境变量 |
| HITL 闭环未端到端实测 | 规则沉淀流程可能断裂 | P0: 3-5 个真实 PDF 闭环验证 |
| Quality Guard 核心网络校验过宽 | 不达标网表可能漏过 | ✅ 已改为网络级校验 (V5.1) |
| Streamlit 遗留双轨 | 维护成本 | P2: 确认 React 稳定后下线 |
| 无 Self-Correction 节点 | 空结果时无自动重试 | P1: Cypher 查询重试机制 |
| 无 E2E 自动化测试 | 全链路回归无保障 | P2: 网表上传→审查→审批自动化 |

### 5.2 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Embedding 质量不佳 | 高 | 向量检索准确率低，GraphRAG 效果打折 | 部署 bge-m3，评估 recall@k 指标 |
| 前后端接口不同步 | 中 | 用户操作报错 | 建立 OpenAPI schema 契约，自动化联调 |
| HITL 闭环未验证 | 中 | 规则沉淀流程断裂 | 选 3-5 个真实 PDF 端到端验证 |
| vLLM 兼容性 | 低 | PRD 原要求 vLLM，T4 驱动不兼容 | 继续用 Ollama (51.9 tok/s 够用)，vLLM 为后续优化 |
| LlamaIndex 迁移成本 | 低 | 自研方案已可工作 | 评估检索质量，<85% 再考虑迁移 |

---

## 6. 关键设计决策（全部已确认，无待决策项）

### 6.1 已确认决策

| 决策 | 内容 | 理由 |
|------|------|------|
| Agent 框架 | 自研 ReActAgent + AgentOrchestrator (非 LangGraph) | 降低依赖，复杂度可控，已验证可行 |
| 审查引擎架构 | 三层（Template+Config+Knowledge） | PRD 要求，已验证可行 |
| LLM 底座 | 本地 Ollama gemma4:26b | 数据安全红线；vLLM 因 T4 驱动不兼容搁置 |
| GraphRAG | 自研 graph_rag/ (非 LlamaIndex) | 功能已满足，Neo4j 原生向量索引 |
| 向量存储 | Neo4j 原生向量索引 (非 ChromaDB 双写) | 统一存储，简化架构 |
| 数据库 | Neo4j 5.26 Community Edition | 图 + 向量双引擎 |
| 前端框架 | React + TypeScript + Ant Design (非 Streamlit) | 前后端分离，扩展性强 |
| Datasheet OCR | PyMuPDF + LLM | 简单优先，Qianfan 作为增强 |
| IC 分类 | 规则词典 + LLM 辅助 | 确定性强 + 覆盖边缘 |
| 电源树生成 | 规则推导 (从 LDO/Buck 引脚正向推导) | 确定性强 |
| 多项目隔离 | project_id 全链路传播 | 支持多网表/多项目场景 |
| 规则热更新 | mtime 检测自动重载 + per-project_id 单例缓存 | 无需重启即可更新规则 |
| 只读安全 | 应用层 `READ_ONLY_MODE` 环境变量 | Community Edition 不支持数据库级只读用户 |

> **注**: V1.0 §7.2「待决策」四项（Datasheet OCR / IC 分类 / Web UI 框架 / 电源树生成）已全部被事实决策，见上表。LlamaIndex 与 vLLM 降级为可选优化项。

---

## 7. 实施路线图（当前状态基线，2026-06-29）

### 已完成阶段（V1.0 路线图 Phase 1-4 全部完成或超越）

- ✅ ETL 数据质量提升（Pin.Type 100%、PartType UNKNOWN=1、电源树 593 关系、Quality Guard）
- ✅ 知识库建设（自研 GraphRAG、1901 chunks、22 社区、Tier3 公网检索）
- ✅ Agent 智能化（ReActAgent + AgentOrchestrator + 复合意图拆解 + LLM 缓存）
- ✅ Web UI 闭环（React 7 页面 + WebSocket + 图谱可视化 + 推理链展示）
- ✅ 超出项：多 Agent 编排、多项目隔离、规则热更新、差分对追踪、共因失效可视化、DRC 规则扩展 (14→24)

### 当前待开发清单（源自 PRD_GAP_ANALYSIS_V2 第六节，按优先级）

#### P0 — 阻塞性问题

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| 1 | **BOM CSV 导入管道** | 无 | 解锁 AMR 参数查询和知识库关联的关键入口 (PRD §4.1) |
| 2 | **专业 Embedding 模型部署** (bge-m3) | GPU | 提升向量检索质量，头号质量风险 |
| 3 | **前后端全面联调** | 无 | 逐页面验证 API 对接，修复 WebSocket 地址硬编码 |
| 4 | **HITL Datasheet 闭环验证** | 无 | 3-5 个真实 PDF 端到端跑通 |

#### P1 — 核心功能完善

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| 5 | ~~**Quality Guard 改为网络级校验**~~ ✅ | 无 | 已完成 (V5.1): 核心网络识别从类型级改为网络级连通性校验 (见 §4.2) |
| 6 | **网络电压标注率提升** | 无 | 扩展模式库 + 核心网络 100% 阈值检查 |
| 7 | **AMR 耐压覆盖率提升至 95%** | #1 BOM 导入 | 补充小众 MPN 解析 + Datasheet 数据 |
| 8 | **Self-Correction 节点** | 无 | Cypher 查询重试 + 参数放宽机制 |
| 9 | **LlamaIndex 评估** | #2 Embedding | 评估是否迁移，或继续优化自研方案 |

#### P2 — 质量与生产化

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| 10 | **E2E 自动化测试** | 无 | 全链路：网表上传→审查→审批 |
| 11 | **测试覆盖率 ≥60%** | 无 | 补充 parser/template/graph_tools 测试 |
| 12 | **Cypher 性能基准** | 无 | 验证 < 500ms 目标 |
| 13 | **vLLM 部署** | 驱动升级 | 需 NVIDIA 驱动 ≥535.104.05 |
| 14 | **Neo4j 数据库层只读** | Enterprise | 当前应用层 READ_ONLY_MODE 已够用 |

---

## 8. 附录

### 8.1 文件清单

```
hardware_ai_expert/
├── agent_system/
│   ├── react_agent.py              # ReActAgent (主, 786行)
│   ├── agent_orchestrator.py       # AgentOrchestrator + 3 专项 Agent (294行)
│   ├── agent_core.py               # 遗留 HardwareAgent (1366行, fallback)
│   ├── graph_tools.py              # 16 Cypher tools + project_id 隔离
│   ├── knowledge_router.py         # Tier0-3 分级检索路由
│   ├── llm_client.py               # LLM 客户端 + 缓存 TTL
│   ├── llm_intent_router.py        # LLMIntentRouter
│   ├── amr_engine.py               # AMR 降额引擎
│   ├── mpn_decoder.py              # MPN 解码器 (98.2% 覆盖)
│   ├── tier3_retriever.py          # Tier3 公网 MPN 检索 (9 供应商)
│   ├── datasheet_parser.py         # Datasheet PDF 解析
│   ├── datasheet_processor.py      # Datasheet 处理器
│   ├── datasheet_hitl.py           # Datasheet HITL
│   ├── hitl_workflow.py            # HITLManager / PendingReview
│   ├── graph_rag_bridge.py         # GraphRAGBridge
│   ├── embedding.py                # Embedding 服务
│   ├── kb_persistence.py           # 知识库持久化
│   ├── etl_web_bridge.py           # ETLWebExecutor
│   ├── storage_dispatcher.py       # 存储分发
│   ├── init_neo4j_schema.py        # Neo4j Schema 初始化
│   ├── initialize_knowledge_base.py # 知识库初始化
│   ├── graph_rag/                  # 自研 GraphRAG
│   │   ├── pipeline.py             # GraphRAGPipeline (local/global/graph/auto)
│   │   ├── schemas.py              # VectorChunk/Community/RetrievalResult
│   │   ├── indexers/
│   │   │   ├── vector_indexer.py   # Neo4jVectorIndexer (原生向量索引)
│   │   │   ├── entity_extractor.py # HardwareEntityExtractor
│   │   │   └── community_detector.py # CommunityDetector (Louvain)
│   │   └── retrievers/
│   │       ├── local_retriever.py  # 向量相似度
│   │       ├── global_retriever.py # 社区报告
│   │       └── graph_retriever.py  # 多跳遍历
│   ├── review_engine/
│   │   ├── engine.py               # ReviewRuleEngine (per-project_id 单例 + mtime 热更新)
│   │   ├── whitelist.py            # WhitelistManager
│   │   ├── config/default_rules.yaml  # 24 条规则
│   │   └── templates/              # 9 模板
│   │       ├── base.py
│   │       ├── decap.py / pullup.py / esd.py / amr.py / pinmux.py
│   │       ├── voltage_compat.py / power_integrity.py
│   │       ├── connectivity.py / diff_pair.py
│   └── schemas/                    # Pydantic models
├── api/
│   ├── main.py                     # FastAPI app (:8501)
│   ├── dependencies.py
│   ├── routers/                    # 7 routers (chat/review/hitl/knowledge/etl/graph/system)
│   ├── schemas/                    # 请求/响应模型
│   └── websocket/chat_ws.py        # WebSocket 流式对话
├── etl_pipeline/
│   ├── main_etl.py                 # ETL 主流程
│   ├── chip_parser.py / prt_parser.py / net_parser.py
│   ├── part_type_standardizer.py   # PartType 标准化
│   ├── refine_passive_types.py     # 被动器件类型精修
│   ├── expand_voltage_annotation.py # 电压标注扩展
│   ├── generate_power_tree.py      # 电源树生成
│   ├── quality_guard.py            # 质量守门 (PartType≥90% + 核心网络识别)
│   ├── load_to_neo4j.py / load_topology.py
│   ├── run_etl_validation.py / run_real_etl.py
├── web_ui/
│   └── app.py                      # 遗留 Streamlit (1973行, fallback)
├── tests/                          # 8 测试文件, 283 测试用例
│   ├── test_amr_engine.py (21)
│   ├── test_e2e_agent.py (20)
│   ├── test_graph_tools.py (39)
│   ├── test_integration.py (33)
│   ├── test_llm_client.py (15)
│   ├── test_mpn_decoder.py (66)
│   ├── test_review_engine.py (50)
│   └── test_tier3.py (39)
├── data/                           # chroma_db/ datasheets/ kb/ neo4j/ netlist_Beet7/ output/
├── amr_data.yaml                   # AMR 耐压数据
└── requirements.txt

frontend/                           # React + TypeScript 前端
├── src/
│   ├── App.tsx / main.tsx
│   ├── pages/                      # 7 页面 (Chat/Review/HITL/Knowledge/ETL/Graph/System)
│   ├── components/                 # ReasoningChain / graph_viz 等
│   ├── hooks/                      # useChatWebSocket
│   ├── api/ stores/ styles/ types/ utils/
├── package.json / vite.config.ts / tsconfig.json
```

### 8.2 环境配置

```bash
# 核心服务（凭据通过 .env 注入，禁止明文写入文档）
Neo4j:     bolt://localhost:7687      # 账号密码见 .env: NEO4J_USER / NEO4J_PASSWORD
Ollama:    http://localhost:11434     # model: gemma4:26b
FastAPI:   http://localhost:8501      # docs: /docs
React Dev: http://localhost:5173      # Vite dev server

# Python 版本
Python 3.12.8

# 关键依赖
neo4j==5.26.0
fastapi
pydantic==2.10.4
sentence-transformers        # all-MiniLM-L6-v2 (384维)
python-dotenv==1.0.1

# 前端
Node.js + React 18 + TypeScript + Vite + Ant Design

# 安全说明
# - Neo4j Community Edition 不支持数据库级只读用户
# - 已通过应用层 READ_ONLY_MODE 环境变量限制写操作
# - 数据库升级到 Enterprise Edition 后可启用数据库层只读账号
```

### 8.3 验证命令

```bash
# 0. 进入虚拟环境
source .venv/bin/activate

# 1. 审查引擎全量测试
cd /data/schematic_agent/hardware_ai_expert
python3 -c "
from agent_system.review_engine import ReviewRuleEngine
from agent_system.graph_tools import _get_driver
engine = ReviewRuleEngine(_get_driver())
violations = engine.run_rules()
print(f'Total violations: {len(violations)}')
"

# 2. Agent Core 端到端测试 (ReActAgent)
python3 -c "
from agent_system.react_agent import ReActAgent
agent = ReActAgent()
result = agent.run('检查板子上的去耦电容')
print(result)
"

# 3. ETL 数据质量检查
python3 etl_pipeline/run_etl_validation.py

# 4. 全量单元测试 (283 用例)
python3 -m pytest tests/ -v

# 5. GraphRAG 检索测试
python3 -c "
from agent_system.graph_rag.pipeline import GraphRAGPipeline
pipe = GraphRAGPipeline()
result = pipe.query('TPS5430 的输出电压范围', mode='auto')
print(result)
"

# 6. 前端启动
cd /data/schematic_agent/frontend && npm run dev
```

---

*本方案以 commit `d0c746d` 代码事实为基准，由 Jarvis 于 2026-06-29 全面重写至 V2.0*
