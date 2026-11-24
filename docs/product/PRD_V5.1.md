# 统一硬件 AI 专家系统（审查与诊断）产品需求文档 (PRD) - V5.1

版本: V5.1 (技术选型回写与需求收敛版) | 日期: 2026-06-29
说明: 本版本基于 V5.0 演进，重点修复审计发现的三大问题——(1) 回写已事实确立的技术选型决策（自研 GraphRAG / Ollama / React 为正式基线）；(2) 补全 V5.0 缺失的非功能需求、安全、测试验收、Web UI 细化章节，修复与 PRD_GAP_ANALYSIS_V2 的章节引用断裂；(3) 明确定义「核心网络识别率」「电压标注率」「AMR 覆盖率」三大指标的统计口径，并将多项目隔离等已实现能力纳入需求。

> **章节编号约定**: 本版扩展至 15 章，其中 §10 Web UI、§12 测试与质量、§14 安全要求（含 §14.2 Neo4j 只读账号）与 PRD_GAP_ANALYSIS_V2 的引用对齐。

---

## 1. 产品愿景与定位

打造一个基于本地化推理、隐私绝对安全的 Agentic 硬件辅助系统。通过构建物理单板的"数字孪生"底座，结合 Neo4j 与自研 GraphRAG 技术，实现硬件全生命周期的核心闭环：

- **左移防御（原理图审查）**: 在设计阶段，利用确定性规则与专家库结合，自动化巡检拓扑，精准拦截器件选型与连接违规。
- **右移排障（硬件故障诊断）**: 结合上下文感知多维图搜索，支持针对电源树失效、高频总线等复杂故障的根因定位。
- **终身学习（高置信知识获取）**: 建立基于 HITL（人类在环）的 Datasheet 参数提取机制，持续沉淀企业级本地专家知识库。

---

## 2. 核心架构决策说明 (V5.0 → V5.1 技术选型回写)

V5.0 原始要求的若干技术选型在实际落地中因环境约束发生偏离，这些偏离本身合理且已验证可行。本节正式回写决策，将其确立为 V5.1 基线，原 V5.0 要求降级为可选优化项。

| 领域 | V5.0 原要求 | V5.1 正式基线 (已落地) | 偏离原因 | 可选优化路径 |
|------|------------|----------------------|----------|-------------|
| GraphRAG 框架 | llama-index + llama-index-graph-stores-neo4j | **自研 graph_rag/** (Neo4j 原生向量索引) | 自研方案已满足图文联合检索需求，减少依赖 | 文档量 >5000 chunks 时评估迁移 LlamaIndex |
| 向量存储 | ChromaDB + Neo4j 双库 | **Neo4j 原生向量索引** (384维 cosine) | 统一存储简化架构，ChromaDB 降为遗留迁移源 | — |
| LLM 推理 | vLLM + Llama3-70B/Qwen | **Ollama gemma4:26b** (:11434) | T4 GPU 驱动不兼容 vLLM；Ollama 51.9 tok/s 够用 | 驱动升级至 ≥535.104.05 后可切 vLLM |
| Embedding 模型 | (未明确) | **sentence-transformers all-MiniLM-L6-v2** | 当前与 LLM 同源，可工作 | **P0 待优化**: 升级 bge-m3 专业 embedding 模型 |
| Web UI 框架 | Streamlit (Phase 3) | **React 18 + TypeScript + Ant Design** | 前后端分离，扩展性强 | Streamlit 保留为遗留双轨 fallback |
| Agent 框架 | (未指定 LangGraph) | **自研 ReActAgent + AgentOrchestrator** | 降低依赖，复杂度可控 | — |
| 状态机 | 轻量级 LLM 路由 + 任务队列 | **ReAct Thought→Action→Observation + 多 Agent 编排** | 已超越原设计 | — |

**决策原则**: 已落地且验证可行的技术栈即为本版基线，不再每轮 gap 分析重复记录"未用 LlamaIndex"等偏差。优化项仅在触发条件满足时启动评估。

### 2.1 V5.0 架构重构成果回顾

| 痛点问题 (V4.0) | V5.0 重构方案 | V5.1 落地状态 |
|----------------|--------------|--------------|
| ETL 容错差 (缺失 Pin.Name/Type) | 强制化语义解析 + NLP 字典补齐 | ✅ Pin.Type 100%、PartType UNKNOWN=1 |
| 伪 GraphRAG 割裂 | True GraphRAG 融合 | ✅ 自研 GraphRAG (1901 chunks, 10504 DESCRIBES) |
| 图谱工具暴力截断 (MAX=50) | Cypher 下推与特征聚合 | ✅ CYPHER_ROW_LIMIT=500 + 智能聚合 |
| 状态机意图识别僵化 | 轻量级 LLM 路由引擎 | ✅ ReActAgent + 复合意图拆解 |
| Datasheet 提取幻觉 | HITL 审核流 | ⚠️ 管道已实现，端到端闭环待验证 (P0) |

---

## 3. 系统整体架构

### 3.1 技术架构图

```
用户输入 (React Web UI / WebSocket)
 |
 +----v----+
 | Agent | AgentOrchestrator → 路由 ReviewAgent / DiagnosisAgent / QueryAgent
 | Core | ReActAgent (fallback): Thought→Action→Observation, MAX_STEPS=10
 +----+----+
 |
 +----v-------------+ +------------------+ +---------------------------------+
 | Review Engine | | Smart Graph Tools| | KnowledgeRouter (分级检索) |
 | (确定性规则校验) | | (16 Cypher tools)| | Tier0 GraphRAG / Tier1 本地 |
 | 9 模板 24 规则 | | project_id 隔离 | | Tier2 内网PLM / Tier3 公网MPN |
 +----+----+----+ | +--------+-------+ +--------+------------------------+
 | | | | | | (Semantic + Topology)
 +----v----+ | | | |
 | AMR | | | +---------------> Neo4j (原生向量索引) <---- VectorChunk
 | Engine | | | +---+---+ [:DESCRIBES]
 +----------+ | | |
 | | |
 +---------------v----v-------------------------------v---+
 | ETL Pipeline & Quality Guard |
 | 网表解析 → PartType标准化 → 电压标注 → 电源树 → 质量熔断|
 +--------------------------------------------------------+
```

### 3.2 核心依赖栈 (V5.1 正式基线)

- **前端**: React 18 + TypeScript + Vite + Ant Design
- **后端**: FastAPI + Uvicorn (:8501) + WebSocket
- **Agent**: 自研 ReActAgent + AgentOrchestrator (非 LangGraph)
- **大模型推理底座**: 本地 Ollama (gemma4:26b)，保障本地响应速度与数据安全
- **GraphRAG**: 自研 graph_rag/ (Neo4j 原生向量索引，非 LlamaIndex)
- **图数据库**: Neo4j 5.26 Community Edition (图 + 向量双引擎)
- **Embedding**: sentence-transformers all-MiniLM-L6-v2 (384维) — **P0 待升级 bge-m3**
- **其他必备**: pydantic, sentence-transformers, python-dotenv

---

## 4. 数据底座层 (ETL) 强化方案

**优先级: 绝对 P0。数据不净，业务不兴。**

### 4.1 强制提取与对齐规则

- **Pin.Name 强制捕获**: 修改 chip_parser.py。若原生数据确实遗漏，启动 fallback 机制（根据封装与网表历史推演），并向控制台抛出 Critical Warning。
- **PartType 智能标准化**:
  - 废弃原始硬编码正则匹配。
  - 引入本地轻量级字典与 NLP 对齐服务：读取 BOM 的 Description 字段，将其映射为标准的 [MCU, PMIC, FPGA, LDO, BUCK, CONNECTOR, PASSIVE] 等枚举类型。
- **BOM CSV 导入** (✅ 已实现，2026-09 核实): 支持 CSV/Excel 格式 BOM 导入（RefDes、MPN、Description、Manufacturer、Quantity、Package），作为 AMR 参数查询和知识库关联的关键入口。实现见 `etl_pipeline/part_type_standardizer.py`（多编码探测 + 分隔符自动检测 + BOM Description 参与 PartType 标准化）与 API `POST /api/v1/etl` 的 `bom` 上传字段，测试见 `tests/test_bom_metadata.py`。**剩余**: BOM→MPN→AMR/知识库关联的端到端业务验证（见 §15 P1-4）。

### 4.2 数据质量守门员 (Quality Guard)

新增前置拦截模块，阈值如下：

- **Component PartType 标准化率 < 90% → 阻断运行。**
  - 统计口径: `(total_components - UNKNOWN_count) / total_components * 100%`
- **核心网络识别率 < 100% → 阻断运行。**
  - **V5.1 口径修正 (网络级，非类型级)**: 遍历所有匹配核心网络模式（VCC/GND/VDD/VSS/3V3/1V8/5V/12V/VBAT/VIN/VOUT/AVDD/DVDD/IOVDD）的具体网络名，要求**每个核心网络均被识别并标注电压等级**。
  - 统计口径: `已标注电压的核心网络数 / 匹配模式的核心网络总数 * 100%`
  - **不再使用类型级代理指标**（V5.0 实现仅检查 4 类电压各出现一次即判 100%，过于宽松）。

> 详见 §13 关键指标定义。

---

## 5. Agent Core 核心流转 (V2.0)

从"单线关键词状态机"升级为"ReAct 循环 + 多 Agent 编排"。

### 5.1 多 Agent 编排 (AgentOrchestrator)

AgentOrchestrator 根据意图路由至专项 Agent，失败/超时 fallback 至全工具 ReActAgent：

- **ReviewAgent**: 9 tools（run_review + 图谱查询），审查专项
- **DiagnosisAgent**: 10 tools（共因失效/电源链路/信号路径追踪），故障树分析框架
- **QueryAgent**: 8 只读 tools，规格查询专项

### 5.2 ReAct 循环与复合意图拆解

- Thought→Action→Observation 统一循环，MAX_STEPS=10
- 同工具重复上限 SAME_TOOL_REPEAT_LIMIT=3，图工具调用上限 4 次
- 复合意图自动拆解为子任务队列（如"查 I2C 上拉 + TPS5430 VOUT 公式"拆为两个子任务）
- 最后 2 步强制进入 final 答复，防死循环

### 5.3 防死循环与容错

- 设定 MAX_STEPS = 10。
- **Self-Correction 节点 (✅ 已实现，2026-09 核实)**: 当 Graph Tools 返回空/无命中结果时，自动放宽查询参数后重试，最多 2 次（第 1 次放宽过严条件，第 2 次丢弃过窄的实体过滤）。实现见 `agent_system/react_agent.py` 的 `_self_correct_tool_call` / `_relax_query_params`，测试见 `tests/test_react_self_correction.py`。

---

## 6. Smart Graph Tools (智能图谱工具箱)

解决原版粗暴截断问题，引入计算下推。

### 6.1 智能特征聚合 (Feature Aggregation)

针对 get_net_components 工具：
- **旧版**: 找到 GND，返回前 50 个节点，导致后续推断彻底错误。
- **新版逻辑 (已落地)**:
  - `CYPHER_ROW_LIMIT=500` 替代硬截断
  - 超大节点网络在 Cypher 层聚合统计（如"该网络包含 120 个电容，3 个电阻"）
  - 返回聚合摘要而非截断列表，保留完整拓扑语义

### 6.2 高级高频/电源路径工具 (已落地)

- `trace_differential_pair(start_pin)` + `discover_diff_pairs(signal_type)`: 差分对追踪，实测 224 对（218 完整 / 6 不完整）
- `get_power_tree()`: 基于 `[:POWERED_BY]` 关系向下钻取完整供电树拓扑 (593 条关系)
- `get_common_cause_graph` + `common_cause_risk_score`: 共因失效可视化与风险评分
- `trace_power_chain` + `trace_fault_root`: 诊断专用电源链路追踪与故障根因定位

### 6.3 多项目数据隔离

所有图谱工具均支持 `project_id` 参数，实现多网表/多项目数据全链路隔离。详见 §8。

---

## 7. 知识外脑 (自研 GraphRAG & HITL)

### 7.1 自研 GraphRAG 图文桥接 (非 LlamaIndex)

当解析一份包含 TPS5430 信息的 PDF 时：
1. 将 PDF 切片，通过 sentence-transformers 生成 embedding，存入 Neo4j VectorChunk 节点（原生向量索引，384维 cosine）。
2. 提取实体 (Component: "TPS5430")，在 Neo4j 中建立或匹配该节点。
3. 建立关系：`(VectorChunk)-[:DESCRIBES {type: "electrical_spec"}]->(Component: "TPS5430")`。
4. Agent 检索时，GraphRAGPipeline 支持 `mode=local/global/graph/auto`：
   - **local**: 向量相似度检索
   - **global**: Louvain 社区报告检索 (22 个社区)
   - **graph**: 多跳遍历 (RefDes/MPN/Net)
   - **auto**: 自动选择 + hybrid fusion

**与 V5.0 偏差**: 未使用 LlamaIndex，采用自研方案。功能已满足 PRD 核心需求。Embedding 质量当前依赖 all-MiniLM-L6-v2，**P0 待升级 bge-m3 专业模型**。

### 7.2 HITL 规则沉淀工作流

- LLM 自动从 PDF 提取出 AMR 降额参数（如电容耐压=50V）。
- 该参数状态标记为 `Pending_Review`，存入 Neo4j。
- 在 React Web UI 的 HITL 页面，由资深硬件工程师点击【Approve】。
- 审批通过后，正式注入审查规则引擎的 `default_rules.yaml` 和 AMR 引擎 `amr_data.yaml`。
- **规则热更新 (已实现)**: ReviewRuleEngine per-project_id 单例缓存 + mtime 检测自动重载，无需重启。

### 7.3 分级检索路由 (KnowledgeRouter)

- **Tier 0 (GraphRAG)**: 阈值 0.3，图文联合检索
- **Tier 1 (本地知识库)**: 本地语义检索
- **Tier 2 (内网 PLM)**: 接口占位，无实际 PLM 集成
- **Tier 3 (公网 MPN)**: 轻量纯 Python，9 供应商模板，脱敏后检索

---

## 8. 多项目数据隔离 (V5.1 新增 — 已实现能力纳入需求)

系统支持多网表/多项目并行管理与数据隔离：

- **project_id 全链路传播**: 从 ETL 导入、图谱查询、审查引擎到知识检索，所有操作均携带 project_id 标识
- **项目 CRUD**: 支持创建、切换、删除项目
- **ReviewRuleEngine per-project_id 单例**: 每个项目独立缓存规则引擎实例，支持独立规则配置
- **KnowledgeRouter(project_id)**: 知识检索按项目隔离
- **图谱工具 project_id 隔离**: 所有 Cypher 查询均带 project_id 过滤

**需求**: 任何项目 A 的查询、审查、知识检索不得返回项目 B 的数据。这是数据安全与多团队协作的基础要求。

---

## 9. 非功能需求 (V5.1 新增)

V5.0 缺失非功能需求章节，导致性能、并发、延迟无明确验收标准。本节补全。

### 9.1 性能要求

| 指标 | 目标 | 说明 |
|------|------|------|
| LLM 推理延迟 | < 5s (单轮) | Ollama gemma4:26b 实测 51.9 tok/s |
| Cypher 查询延迟 | < 500ms | 大网络走聚合摘要 (P2 待基准测试) |
| GraphRAG 检索延迟 | < 2s | local/global/graph 三模式 |
| ETL 全量导入 | < 10min (Beet7 规模) | 49,570 pins / 8,159 nets |
| 审查引擎全量规则 | < 30s | 24 规则 × 9 模板 |

### 9.2 并发与容量

| 指标 | 目标 | 说明 |
|------|------|------|
| 并发用户数 | ≥ 10 | FastAPI 异步 + WebSocket |
| 单项目最大规模 | 100,000 pins | Neo4j 索引优化保障 |
| 知识库容量 | 5,000 chunks | 当前 1,901，超 5,000 评估迁移 LlamaIndex |
| LLM 缓存命中率 | ≥ 50% | TTL 1h + 50% 淘汰 |

### 9.3 可用性

- 服务单点部署（当前阶段），后续可扩展为多副本
- Neo4j 数据库每日备份
- LLM 服务 Ollama 进程监控，异常自动重启

---

## 10. Web UI 需求 (V5.1 新增 — 与 GAP 分析 §8/10 对齐)

V5.0 Phase 3 仅提"Streamlit Web UI"，本节细化 React 前端需求。

### 10.1 技术栈

- React 18 + TypeScript + Vite + Ant Design
- 前后端分离，FastAPI 后端 (:8501) + React 前端
- WebSocket 流式对话 (useChatWebSocket hook)
- 暗/亮主题切换

### 10.2 页面需求 (7 页面)

| 页面 | 功能 | 状态 |
|------|------|------|
| **Chat** | WebSocket 流式对话，推理链路展示 (Thought→Action→Observation 时间线) | ✅ |
| **Review** | 审查结果展示，违规列表，白名单管理 | ✅ |
| **HITL** | Datasheet 提取参数审批看板，Approve/Reject 操作 | ✅ |
| **Knowledge** | 知识库管理，Datasheet 上传，GraphRAG 索引构建 | ✅ |
| **ETL** | 网表上传，ETL 触发，质量报告展示 | ✅ |
| **Graph** | graph_viz 多维度可视化（电源链路/故障溯源/共因失效/组件关系/电源树） | ✅ |
| **System** | 系统状态（Neo4j/Ollama/GraphRAG 健康检查） | ✅ |

### 10.3 推理链路可视化

- 时间线布局展示 Thought→Action→Observation 步骤
- 折叠面板 + 步骤图标
- 工具调用结果实时回显

### 10.4 待修复项 (P0)

- WebSocket 连接地址硬编码 `ws://localhost:8501`，需改为相对路径/环境变量
- 前后端 API schema 部分不匹配，需全面联调

---

## 11. 规则热更新与配置管理 (V5.1 新增 — 已实现能力纳入需求)

### 11.1 规则热更新

- ReviewRuleEngine 按 project_id 缓存单例实例
- 检测 `default_rules.yaml` 文件 mtime，变更时自动重载
- 无需重启服务即可更新审查规则

### 11.2 规则配置

- 规则文件: `review_engine/config/default_rules.yaml` (当前 24 条)
- 模板文件: `review_engine/templates/*.py` (当前 9 模板)
- 三层架构: Template (Layer 1) + Config (Layer 2) + Knowledge (Layer 3)

### 11.3 白名单管理

- WhitelistManager 读写白名单，过滤误报
- Web UI HITL 页面支持白名单交互操作

---

## 12. 测试与质量验收 (V5.1 新增 — 与 GAP 分析 §12 对齐)

V5.0 缺失测试与质量验收章节，本节补全。

### 12.1 测试体系

| 层级 | 说明 | 当前状态 |
|------|------|----------|
| **单元测试** | 模块级函数/类测试 | ✅ 283 用例 (8 文件) + 22 用例 (root 5 文件) = 305 |
| **集成测试** | 模块间协作测试 | ✅ 28 用例 (test_integration.py + test_e2e_agent.py) |
| **E2E 自动化** | 全链路：网表上传→ETL→审查→审批 | ❌ P2 待开发 |
| **测试覆盖率** | 代码覆盖率 | ⚠️ 估计 40-45%，目标 ≥60% (P2) |

### 12.2 测试用例口径核实 (2026-06-29)

- `hardware_ai_expert/tests/` 下 **12 个测试文件**（2026-09 核实，较 2026-06 的 8 个新增 test_tier3 / test_react_self_correction / test_bom_metadata / test_datasheet_hitl_loop），含数百个测试函数/类
- 根目录另有 5 个测试文件（test_etl_web/test_integration/test_phase1/test_phase3/test_phase4）
- **统一口径**: 后续文档引用测试用例数时，区分"tests/ 目录"与"全项目"，且注明核实日期与提交号（测试文件数会随开发增长）；测试尚未分层（unit/integration/e2e/live），无覆盖率门禁与 CI（见 §15 P2）

### 12.3 质量验收标准

| 验收项 | 标准 | 验证方式 |
|--------|------|----------|
| PartType 标准化率 | ≥ 90% | Quality Guard 自动熔断 |
| 核心网络识别率 | 100% (网络级) | Quality Guard 自动熔断 (P1 改造) |
| 审查规则覆盖 | 24 规则 × 9 模板 | 单元测试 test_review_engine.py (50 用例) |
| GraphRAG 检索 | recall@k ≥ 85% | P2 待建立基准 (当前无量化) |
| Cypher 查询延迟 | < 500ms | P2 待基准测试 |

### 12.4 持续集成

- 当前无 CI/CD 流水线（P2 待建设）
- 建议接入 iPipe 流水线：单元测试 → 集成测试 → 覆盖率报告

---

## 13. 关键指标定义 (V5.1 新增 — 统一统计口径)

V5.0 指标定义模糊，导致实现时口径偷换、文档间数据矛盾。本节明确三大核心指标的统计口径。

### 13.1 核心网络识别率

**定义**: 核心电源网络被系统识别并标注电压等级的比例。

**核心网络清单** (匹配以下模式的具体网络名，不区分大小写):
- 电源类: VCC, VDD, 5V, 12V, VIN, VOUT, AVDD, DVDD, IOVDD, VBAT
- 接地类: GND, VSS
- 常见轨压: 3V3/3.3V, 1V8/1.8V

**统计口径 (网络级，V5.1 修正)**:
```
核心网络识别率 = 已标注电压等级的核心网络数 / 匹配模式的核心网络总数 × 100%
```
- 分子: 遍历所有匹配 CORE_NET_PATTERNS 的具体网络名，其中具有 VoltageLevel 属性的网络数
- 分母: 所有匹配 CORE_NET_PATTERNS 的具体网络名总数
- **阈值: < 100% → 阻断运行**

**与 V5.0 实现的差异**: V5.0 实现 (`quality_guard.py`) 为**类型级**校验——仅检查 4 类电压 (VCC/VDD, GND/VSS, 3.3V, 1.8V) 是否各出现至少一次，是过于宽松的代理指标。V5.1 要求改为网络级校验。**P1 待改造。**

> **V5.1 实现说明 (2026-06-29)**: QualityGuard 运行在 ETL 注入前（无 VoltageLevel 数据），已实现**网络级连通性校验**——逐个枚举匹配 CORE_NET_PATTERNS 的具体网络名，校验每个核心网络具有有效连通性（≥2 pin 连接，排除 stub/解析伪影），并硬性要求电源类与接地类核心网络均存在。recognition = 有效核心网络数 / 核心网络总数 × 100%。实测 Beet7 网表：1068/1076 核心网络有效连通，8 个疑似 stub（类型级校验会误判为 100% 通过）。电压等级标注校验为后续 post-injection 增强项。

### 13.2 电压标注率

**定义**: 全网中具有 VoltageLevel 属性的网络比例。区分两个子口径:

**口径 A — 全网电压标注率**:
```
全网电压标注率 = 有 VoltageLevel 的 Net 数 / 总 Net 数 × 100%
```
- 当前值: 20.7% (1,689 / 8,159)

**口径 B — POWER 网络电压标注率**:
```
POWER 网络电压标注率 = 有 VoltageLevel 的 POWER 网络 数 / POWER 网络总数 × 100%
```
- 当前值: 95.7%

**文档引用约定**: 后续文档必须注明引用的是口径 A 还是口径 B，禁止混用。ROADMAP_NEXT.md 中 17.3% 为历史值（已过期），以本节为准。

**目标**: 核心网络 100%（见 §13.1），POWER 网络 ≥ 95%（当前达标），全网标注率为参考指标不设硬阈值。

### 13.3 AMR 电容耐压覆盖率

**定义**: 电容器件中具有 voltage_rating 参数的比例。

**统计口径**:
```
AMR 覆盖率 = 有 voltage_rating 的电容数 / 电容总数 × 100%
```
- 分子: 通过 MPN Decoder 或 amr_data.yaml 获取到 voltage_rating 的电容数
- 分母: 全网电容器件总数（PartType=PASSIVE 且封装为电容类）

**当前值**: 83.1% (4,751 / 5,714)

**口径差异说明**: GAP 分析 V1 记载 99.8%（封装后缀归一化修复后），V2 记载 83.1% 并注"统计口径可能不同"。**V5.1 统一口径如上**，以 V2 的 83.1% 为当前基线。差异原因: V1 的 99.8% 可能仅统计了 MPN 可解析的电容子集，V2 的 83.1% 统计了全网电容。

**目标**: ≥ 95%（P1 待提升，依赖 BOM 导入补充小众 MPN 解析）

---

## 14. 安全要求 (V5.1 新增 — 与 GAP 分析 §14.2 对齐)

V5.0 缺失安全要求章节，本节补全。

### 14.1 数据安全红线

- **本地化推理**: 所有 LLM 推理通过本地 Ollama 完成，数据不出本机
- **凭据管理**: 数据库账号密码通过 `.env` 环境变量注入，**禁止明文写入文档或代码**
- **公网检索脱敏**: Tier3 公网 MPN 检索仅发送 MPN 编号，剥离完整上下文

### 14.2 Neo4j 只读账号

**V5.0 要求**: Neo4j 只读账号。

**V5.1 落地方案**:
- Neo4j Community Edition **不支持数据库级只读用户**（需 Enterprise Edition）
- **当前方案 (已落地)**: 通过应用层 `READ_ONLY_MODE` 环境变量限制写操作，graph_tools 在只读模式下禁止 MERGE/CREATE/DELETE
- **升级路径**: 升级 Neo4j 至 Enterprise Edition 后，可创建数据库级只读账号
- **评估**: 当前应用层方案已满足安全需求，数据库层只读为可选增强

### 14.3 凭据安全

- `.env` 文件不入版本控制（.gitignore 排除）
- 技术文档中**禁止出现明文密码**（V1.0 技术方案 §8.2 曾含 `password: SecretPassword123`，V2.0 已删除）
- 生产环境凭据通过密钥管理系统注入

---

## 15. 实施路线图 (V5.1 — 当前状态基线)

### 已完成阶段 (V5.0 Phase 1-3 全部完成或超越)

- ✅ Phase 1: 底座重建（ETL 强化、Pin.Type 100%、PartType UNKNOWN=1、Quality Guard、图谱工具 Cypher 下推）
- ✅ Phase 2: Agent 升级与 GraphRAG（自研 GraphRAG、ReActAgent、复合意图、多 Agent 编排）
- ✅ Phase 3: 高级审查规则与 Web 闭环（React UI、9 模板 24 规则、图谱可视化、推理链展示、HITL 看板）
- ✅ 超出项: 多项目隔离、规则热更新、差分对追踪、共因失效可视化、Tier3 公网检索、LLM 缓存

### 当前待开发清单 (源自 PRD_GAP_ANALYSIS_V2 第六节)

#### P0 — 阻塞性问题

> **2026-09-22 核实更新**: 原 P0 清单中「BOM CSV 导入」与「Self-Correction」的代码实现已完成（见 §4.1、§5.3），现将重心校正为「跑通真实闭环 + 恢复运行环境」，与 `ROADMAP_DEVELOPMENT_CHECKLIST_2026-08.md` 对齐。

1. ~~**BOM CSV 导入管道** (§4.1)~~ ✅ 代码已实现 — 剩余为端到端业务验证（BOM→MPN→AMR/知识库，见 P1-4）
2. **专业 Embedding 模型部署** (bge-m3) — `embedding.py` 已支持 `SCHEMATIC_EMBEDDING_MODEL` 环境变量切换（代码就绪），**剩余**: 实际部署 bge-m3、重建向量索引、建立 recall/MRR 评估；仍为头号质量风险
3. **前后端全面联调** (§10.4) — 修复 WebSocket 地址硬编码，逐页面验证
4. **HITL Datasheet 闭环验证** (§7.2) — 管道与 `tests/test_datasheet_hitl_loop.py` 已在，剩余 3-5 个真实 PDF 端到端跑通
5. **恢复并统一服务启动/健康检查** — 一键启停 Neo4j/Ollama/ChromaDB/FastAPI/React，System 页面显示真实（含 degraded）状态

#### P1 — 核心功能完善

5. ~~**Quality Guard 改为网络级校验**~~ ✅ (§13.1) — 已完成: 核心网络识别从类型级改为网络级连通性校验
6. **网络电压标注率提升** (§13.2) — 扩展模式库 + 核心网络 100% 阈值
7. **AMR 耐压覆盖率提升至 95%** (§13.3) — 依赖 BOM 导入补充小众 MPN
8. ~~**Self-Correction 节点** (§5.3)~~ ✅ 已实现 — Cypher 空结果重试 + 参数放宽机制（`react_agent._self_correct_tool_call`）
9. **LlamaIndex 评估** — 评估是否迁移，或继续优化自研方案

#### P2 — 质量与生产化

10. **E2E 自动化测试** (§12.1) — 全链路：网表上传→审查→审批
11. **测试覆盖率 ≥60%** (§12.1) — 补充 parser/template/graph_tools 测试
12. **Cypher 性能基准** (§9.1) — 验证 < 500ms 目标
13. **vLLM 部署** (§2) — 需 NVIDIA 驱动 ≥535.104.05
14. **Neo4j 数据库层只读** (§14.2) — 需 Enterprise Edition

---

## 附录: V5.0 → V5.1 变更摘要

| 变更项 | 说明 |
|--------|------|
| §2 新增 | 技术选型决策回写（自研 GraphRAG / Ollama / React 为基线） |
| §3 更新 | 架构图与依赖栈更新为实际落地状态 |
| §4.2 修正 | 核心网络识别率改为网络级口径 |
| §8 新增 | 多项目数据隔离需求 |
| §9 新增 | 非功能需求（性能/并发/可用性） |
| §10 新增 | Web UI 需求细化（与 GAP 分析 §8/10 对齐） |
| §11 新增 | 规则热更新与配置管理 |
| §12 新增 | 测试与质量验收（与 GAP 分析 §12 对齐） |
| §13 新增 | 关键指标定义（统一三大指标口径） |
| §14 新增 | 安全要求（与 GAP 分析 §14.2 对齐） |
| §15 更新 | 路线图更新为当前状态基线 |

---

*本版本由 Jarvis 基于 PRD V5.0 + 审计报告 (DOC_AUDIT_PRD_TECH_PLAN_2026-06-12.md) + 代码基线 commit `d0c746d` 编制，2026-06-29*

*2026-09-22 状态回写: 依据当前代码基线核实，将已完成但仍标为「待开发」的项（BOM CSV/Excel 导入、Self-Correction 节点）更正为「已实现」，明确 Embedding 已可配置切换（部署/评估待做），更新测试文件计数，并将 P0 重心校正为「跑通真实闭环 + 恢复运行环境」，与 ROADMAP_DEVELOPMENT_CHECKLIST_2026-08.md 对齐。*
