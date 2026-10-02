# PRD 差距分析报告 V2

> Date: 2026-06-08（原始版本）| Baseline: PRD_V5.0 vs actual code as of commit `d0c746d`
> 对比: 在 V1 分析 (2026-05-14) 基础上，更新过去 3 周的开发进展
>
> **2026-09-30 复核更新**：基于当前 HEAD `30ef49b`（分支 `work/legacy-tasks-20260704`）对本文档"未实现/部分完成"清单逐项重新核实代码现状。原文档中列出的多数 P0/P1 问题已在 `d0c746d` 之后的提交中解决，详见下方各节新增的「2026-09-30 复核」标注。整体完成度已从 83% 提升，详见第一节更新。

---

## 一、需求完成度总览

| PRD 模块 | V1 完成度 | V2 完成度 (06-08) | **复核 (09-30)** | 变化说明 |
|----------|-----------|-----------|----------|----------|
| §4 数据底座 (ETL) | 85% | 95% | **98%** | BOM CSV/xlsx/xls 导入已实现；核心网络电压标注 100% 阈值已在 Quality Guard 落地 |
| §5 Agent Core | 75% | 88% | **93%** | Self-Correction（空结果检测+参数放宽重试）已实现并有单测覆盖 |
| §6 图谱工具 | 90% | 97% | 97% | 无新变化 |
| §7 True GraphRAG | 40% | 80% | **82%** | 自研方案不变；embedding 已支持通过环境变量切换模型，但默认值仍为 all-MiniLM-L6-v2，尚未切到 bge 系列 |
| §7 HITL 规则沉淀 | 70% | 85% | **88%** | 已有真实 PDF 端到端测试（含 SHA256 固定内容校验），但 Neo4j 落库环节仍为 mock，非完全端到端 |
| §8/10 Web UI | 65% | 82% | **86%** | WebSocket 地址硬编码问题已修复，改为动态推导 + 环境变量覆盖 |
| §12 测试与质量 | 30% | 55% | **60%** | 测试用例 283→390（+38%），E2E 仍是分段覆盖而非单一贯穿测试 |
| **整体** | **63%** | **83%** | **~88%** | **P0 四项中三项已解决，仅专业 Embedding 模型默认值未切换** |

---

## 二、已完成功能详述（V1→V2 新增）

### 2.1 ✅ True GraphRAG（自研实现，非 LlamaIndex）

| 组件 | 实现方式 | 状态 |
|------|----------|------|
| 向量索引 | Neo4j 原生向量索引（非 ChromaDB 双写） | ✅ 1901 VectorChunk 节点 |
| 实体抽取 | LLM 实体抽取 + 正则降级 | ✅ graph_rag/indexers/entity_extractor.py |
| 社区检测 | Louvain 算法 | ✅ 22 个社区 |
| 三级检索 | local（向量）/ global（社区）/ graph（多跳）+ auto 路由 | ✅ |
| DESCRIBES 关系 | VectorChunk → Component | ✅ 10,504 条关系 |
| Tier0 集成 | KnowledgeRouter 阈值 0.3 | ✅ |

**与 PRD 的偏差：** 未使用 LlamaIndex，采用自研方案。自研方案在功能上已满足 PRD 需求（图文联合检索），但 embedding 质量仍依赖 Ollama gemma4:26b，未采用专业 embedding 模型。

### 2.2 ✅ 差分对追踪（#11）

- `trace_differential_pair(start_pin_id)` + `discover_diff_pairs(signal_type)` 工具
- 实测发现 224 个差分对，218 个完整，6 个不完整
- 差分对审查模板 + P/N 匹配/端接/共模电感检查规则

### 2.3 ✅ 共因失效可视化（#12）

- `get_common_cause_graph` + `common_cause_risk_score` 工具
- graph_viz 新标签页，支持电源链路/故障溯源/共因失效/组件关系/电源树

### 2.4 ✅ 多 Agent 编排（#14）

- `AgentOrchestrator` + ReviewAgent / DiagnosisAgent / QueryAgent
- ReActAgent 保留为 fallback

### 2.5 ✅ DRC 规则扩展（#15）

- 4 个新模板 + 10 条 YAML 规则，总规则数 14→24
- 新模板：voltage_compat / power_integrity / connectivity / diff_pair
- 实测检测 237 个新违规

### 2.6 ✅ 前端重构（React + TypeScript + Ant Design）

- 从 Streamlit 单体迁移到 FastAPI + React 前后端分离
- 7 个页面：Chat / Review / HITL / Knowledge / ETL / Graph / System
- WebSocket 流式对话支持（useChatWebSocket hook）
- 推理链路展示（ReasoningChain / ReasoningStep 组件）
- Ant Design 组件库，暗色/亮色主题

### 2.7 ✅ 其他 V1 后完成项

| 功能 | 说明 |
|------|------|
| 规则热更新 | ReviewRuleEngine 单例缓存 + mtime 检测自动重载 |
| 多网表支持 | project_id 全链路传播，项目 CRUD |
| Tier3 公网检索 | 轻量纯 Python，9 供应商模板，33 单元测试 |
| AMR 覆盖率 99.8% | 封装后缀归一化修复（0402C→0402） |
| 电压覆盖率 95.7% | VoltageLevelExtractor 扩展 |
| PartType UNKNOWN 1 | 分类修正（120→1） |
| LLM 缓存 TTL | 1 小时过期 + 50% 淘汰 |
| 诊断任务流深化 | trace_power_chain + trace_fault_root |
| 复合意图分解 | 健壮实体抽取 |
| OOM Guard | 白名单初始化 + 诊断路由修复 |

---

## 三、部分完成功能分析

### 3.1 ✅ 网络电压标注率（已解决，见 2026-09-30 复核）

**06-08 现状：** 8,159 个 Net 中仅 1,689 个有 VoltageLevel（20.7%）。PRD 要求"核心网络 (VCC/GND/3V3 等) 识别率 < 100% → 阻断"，但 Quality Guard 未强制电压标注率阈值。

**2026-09-30 复核：** `etl_pipeline/quality_guard.py:32` 已定义 `MIN_CORE_NET_RECOGNITION = 100.0`，`_check_core_nets()`（166-262行）按"核心网络"（`CORE_NET_PATTERNS`，第35行）逐个网络级校验识别率，公式为有效核心网络数/核心网络总数×100%，阈值 100%。注释说明这是 V5.1 从"类型级"升级到"网络级"的检查。**与原文档不同的关键点：PRD/文档谈的"20.7%"是全网络覆盖率，而 Quality Guard 现在正确地只对核心网络（而非全部信号网）要求 100%**，这正是建议中提出的方案。状态：已实现，无需继续投入。

### 3.2 ✅ AMR 电容耐压覆盖率（已解决，见 2026-09-30 复核）

**06-08 现状：** 5,714 个电容中 4,751 个有 voltage_rating（83.1%）。

**2026-09-30 复核：** Git log 显示多次提升：`d89f307`(85%) → `24d6f97`(98.2%) → `0ea0a93`"AMR voltage coverage 85%→99.8% — normalize package suffix (0402C→0402)"。`amr_engine.py:755` 的 `get_capacitor_voltage_rating` 实现三级回退（审批后 Datasheet 数据 → KB 查询 → 封装+容值经验表推断）。commit message 显示当前覆盖率 99.8%，已远超 95% 目标。**注意：该数字来自 commit message，未连接真实 Neo4j 实测复核，建议下次有数据库访问时抽样验证。**状态：基本解决，建议做一次实测确认。

### 3.3 ⚠️ True GraphRAG 未使用 LlamaIndex

**现状：** 采用自研 GraphRAG 方案（graph_rag/ 目录），功能上已满足 PRD 核心需求（图文联合检索、DESCRIBES 关系、社区检测）。

**差距：**
1. PRD 明确要求 `llama-index + llama-index-graph-stores-neo4j`
2. Embedding 质量未达最优（Ollama gemma4:26b 非专业 embedding 模型）
3. 缺少 chunk overlap、metadata filtering、hybrid search 等高级特性

**影响评估：** 当前自研方案可工作，LlamaIndex 迁移属于优化项而非阻塞性问题。

**建议：** 短期维持自研方案，中期（文档量 > 5000 chunks 时）迁移到 LlamaIndex。

### 3.4 ⚠️ 前端 API 对接不完整（部分解决，见 2026-09-30 复核）

**现状：** React 前端与 FastAPI 后端的接口对接存在多处问题：
1. HITL 路由调用了不存在的方法（已修复：get_pending_reviews → get_pending_list）
2. 前端 baseURL 硬编码 localhost（已修复：改为相对路径）
3. WebSocket 连接地址硬编码 `ws://localhost:8501`（未修复）
4. 部分 API schema 与后端返回格式不匹配

**2026-09-30 复核：** 第 3 点已修复。`frontend/src/hooks/useWebSocket.ts:19-24` 改为根据 `window.location.protocol/host` 动态推导 ws/wss，并支持 `VITE_WS_URL`/`VITE_API_URL` 环境变量覆盖；`frontend/src/api/client.ts:27` 同样使用 `VITE_API_URL`。未发现残留的 `ws://localhost` 硬编码。第 4 点（API schema 不匹配）未逐一复核，仍建议做一次系统性联调。

**建议：** 全面做一次前后端接口联调测试，逐页面验证 schema 一致性。

**预估：** 1 天（WebSocket 部分已完成，剩余主要是 schema 核对）

### 3.5 ⚠️ HITL Datasheet 审批闭环未实测（部分解决，见 2026-09-30 复核）

**现状：** `datasheet_parser.py` → `datasheet_hitl.py` → `hitl_workflow.py` → `save_approved_rules()` 管道已实现，但缺少端到端的真实数据验证。

**差距：** 
1. 从真实 PDF 提取 → Pending → 工程师审批 → 注入规则引擎的全流程未跑通
2. `save_approved_to_amr()` 写入 `amr_data.yaml` 后，`AMRDataSource` 是否自动重载未确认（注：规则热更新已实现 mtime 检测）

**2026-09-30 复核：** 第 1 点已大幅推进。`tests/test_datasheet_hitl_loop.py` 的 `test_real_pdf_pending_evidence_only`（148行起）使用**真实 PDF**（sn74lvc1g34.pdf、tlv733p-q1.pdf、tps389006.pdf，SHA256 校验固定内容），跑通 `DatasheetParser.parse_pdf → add_extracted_component → get_pending_list`，`test_datasheet_hitl_approve_and_persist_to_amr` 验证 approve→save_approved_to_amr 写入闭环。**但** `test_neo4j_mock_audit_and_rule_file_reload`（168行）注释自陈是 Neo4j 条件匹配的 mock，"not an independent DB integration test"——即落库到真实图数据库这一环节仍未做端到端验证。

**建议：** 补一次接真实 Neo4j（非 mock）的落库验证，闭环即可视为完成。

**预估：** 0.5 天（原 1 天，PDF 提取与审批部分已完成）

---

## 四、未实现功能清单

### 4.1 ✅ P0 — BOM CSV 导入（已解决，见 2026-09-30 复核）

**PRD §4.1：** "读取 BOM 的 Description 字段，将其映射为标准的 PartType 枚举类型"

**06-08 现状：** ETL 导入页仅支持 Cadence 网表，无 CSV BOM 导入。

**2026-09-30 复核：** `etl_pipeline/part_type_standardizer.py` 已实现完整 BOM 导入器：CSV（`_load_csv`，347行）、Excel `.xlsx`（405行，依赖 openpyxl）、旧式 `.xls`（457行，依赖 xlrd），带列名模糊匹配（RefDes/Description/MPN/Manufacturer/Qty）。API 层 `api/routers/etl.py:167,216` 已接收 `bom: Optional[UploadFile]` 参数，`api/services/uploads.py:21` 声明 `"bom": {".csv", ".xlsx", ".xls"}` 白名单，`main_etl.py:36-39` 自动查找 BOM 文件。状态：已完成，无需继续投入。

### 4.2 🔴 P0 — 专业 Embedding 模型（部分解决，见 2026-09-30 复核 —— 仍是唯一未闭环的 P0 项）

**PRD §3.2：** "LlamaIndex + llama-index-graph-stores-neo4j"（隐含需要专业 embedding）

**06-08 现状：** 使用 Ollama gemma4:26b 生成 embedding，非专业 embedding 模型。

**2026-09-30 复核：** `agent_system/embedding.py` 已重构为可配置架构，通过 `SCHEMATIC_EMBEDDING_MODEL` 环境变量切换模型，代码注释（1-6行）明确提到 bge-m3/bge-large-zh-v1.5 为设计目标，`graph_rag/schemas.py:68` 也已写好 bge 维度对照注释。**但默认值仍是 `all-MiniLM-L6-v2`（embedding.py:23），并未真正切到 bge 系列**，向量索引也未用 bge 重建。这是当前 P0 清单里唯一还没有实质性解决的项。

**建议：** 设置默认环境变量为 `bge-m3` 或 `bge-large-zh-v1.5`，重新跑一次 Neo4j 向量索引全量重建，并抽样对比检索质量。

**预估：** 1-2 天（代码基础设施已具备，剩下是配置切换 + 重建索引 + 验证）

### 4.3 ✅ P1 — Self-Correction 节点（已解决，见 2026-09-30 复核）

**PRD §5.2：** "当 Graph Tools 返回空结果时，LLM 自动调整 Cypher 查询策略，重试最多 2 次"

**06-08 现状：** ReAct 引擎隐式支持，但无显式的 Cypher 查询重试/参数放宽机制。

**2026-09-30 复核：** `agent_system/react_agent.py` 已实现完整机制：`_looks_empty_observation`（500行，识别"未找到/无结果/empty/not found"等空结果标记）、`_relax_action_input`（512行，放宽 exact/limit 等过严参数）、`_self_correct_tool_call`（527行，一到两次放宽重试，主流程 749行调用）。配套单测 `test_react_self_correction.py` 验证 `exact: True→False`、`limit` 提升到 10、trace 记录 `self_correction:` 前缀动作。状态：已完成，无需继续投入。

### 4.4 🟡 P1 — Neo4j 只读账号

**PRD §14.2：** "Neo4j 只读账号"

**现状：** 使用默认 neo4j 用户（全权限）。Community Edition 不支持数据库级只读用户，已通过 `READ_ONLY_MODE` 环境变量在应用层限制写操作。

**评估：** 已有应用层方案，数据库层只读需要升级到 Enterprise Edition 或使用代理。

### 4.5 🟡 P1 — 前后端全面联调（部分解决，见 2026-09-30 复核）

**现状：** React 前端与 FastAPI 后端接口曾存在多处对接问题。

**2026-09-30 复核：** WebSocket 硬编码问题（见 3.4）已修复。剩余主要是 API schema 与后端返回格式的系统性核对，尚未做逐页面联调。

**预估：** 1-2 天（原 2-3 天，WebSocket 部分已完成）

### 4.6 🟢 P2 — Cypher 性能基准测试

**PRD §12.2：** "Cypher query performance benchmark < 500ms"

**现状：** 已有 LIMIT 保护和大网络聚合，但无性能基准测试。

**预估：** 1-2 天

### 4.7 🟢 P2 — E2E 自动化测试（部分解决，见 2026-09-30 复核）

**现状：** 283 个单元测试 + 28 个集成测试，缺少从"上传网表 → ETL → 审查 → 报告 → HITL 审批"的全链路自动化测试。

**2026-09-30 复核：** 测试数增至 390（+38%）。已有分段 E2E 覆盖：`test_task12_api_e2e.py` 覆盖 ETL job 全生命周期（`test_import_preview_then_review_happy_path`）+ HITL 批量操作 + 知识库上传隔离；`test_e2e_agent.py` 覆盖 ReAct 全链路查询/诊断/评审。**但仍缺文档要求的单一贯穿全链路测试文件**——链路验证是分段的，不是一条完整测试路径。

**预估：** 2-3 天（原 3-4 天，分段基础已具备，只需串联）

### 4.8 🟢 P2 — 测试覆盖率 ≥60%（部分解决，见 2026-09-30 复核）

**现状：** 283 个测试用例，估计覆盖率约 40-45%。

**2026-09-30 复核：** `pytest --collect-only` 显示当前 **390** 个测试收集成功（另 15 个 deselected），较 06-08 版本增长 38%。新增测试文件包括 `test_amr_engine.py`、`test_react_self_correction.py`、`test_task11-14` 系列、`test_tier3.py` 等。覆盖率百分比未运行 coverage 工具实测，无法确认是否已达 60%。

**预估：** 3-5 天（原 5-7 天，用例规模已扩大，主要缺运行一次 coverage 报告确认实际百分比）

---

## 五、超出 PRD 的额外功能

以下功能已实现但 PRD 未明确要求：

| 功能 | 说明 | 价值 |
|------|------|------|
| **多 Agent 编排** | AgentOrchestrator + 3 个专项 Agent | 超出 PRD 单 Agent 架构，提升专业性 |
| **Tier3 公网 MPN 检索** | 9 供应商模板，纯 Python | PRD 只提 Tier 1/2/3 框架，未细化 |
| **多网表/多项目数据隔离** | project_id 全链路传播 | PRD 未涉及多项目场景 |
| **规则热更新** | mtime 检测自动重载 | PRD 未明确要求热更新 |
| **LLM 缓存 TTL** | 1 小时过期 + 50% 淘汰 | 性能优化，PRD 未涉及 |
| **前端重构为 React** | Streamlit → FastAPI + React + TypeScript | PRD 指定 Streamlit，实际超出 |
| **图谱可视化** | graph_viz 多维度可视化 | PRD 仅提 PyVis/ECharts，实际更丰富 |
| **推理链路展示** | 时间线布局 + 折叠面板 + 步骤图标 | PRD 提到但未细化，实现超出预期 |
| **Louvain 社区检测** | 22 个电源社区 | PRD 未明确要求社区检测 |
| **vLLM 部署尝试** | 因驱动兼容性问题搁置 | PRD 要求 vLLM，实际使用 Ollama |

---

## 六、优先级排序的待开发清单（2026-09-30 复核后，仅列剩余未完成项）

### P0 — 阻塞性问题

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 1 | BOM CSV 导入管道 | 3-4d | ✅ **已完成** | `part_type_standardizer.py` + `api/routers/etl.py` 已支持 CSV/xlsx/xls |
| 2 | **专业 Embedding 模型部署** | 2-3d | 🔴 **仍未完成** | 代码已支持切换（`SCHEMATIC_EMBEDDING_MODEL`），但默认值仍是 all-MiniLM-L6-v2，未切到 bge-m3/bge-large-zh，需重建向量索引 |
| 3 | 前后端全面联调 | 2-3d | ⚠️ 部分完成 | WebSocket 硬编码已修复；剩余为 API schema 系统性核对，1-2d |
| 4 | HITL Datasheet 闭环验证 | 1d | ⚠️ 部分完成 | 真实 PDF 提取+审批已跑通；Neo4j 落库环节仍是 mock，需补 0.5d |

### P1 — 核心功能完善

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 5 | 网络电压标注率提升 | 2-3d | ✅ **已完成** | Quality Guard 已按核心网络实现 100% 阈值校验 |
| 6 | AMR 耐压覆盖率提升至 95% | 2-3d | ✅ **已完成** | commit 记录显示已到 99.8%（未连接真实 DB 复核，建议抽样确认） |
| 7 | Self-Correction 节点 | 2-3d | ✅ **已完成** | `react_agent.py` 空结果检测+参数放宽重试已实现，有单测 |
| 8 | LlamaIndex 评估 | 3-5d | 🟡 待评估 | 依赖 #2 Embedding 先完成，尚未启动评估 |

### P2 — 质量与生产化

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 9 | E2E 自动化测试 | 3-4d | ⚠️ 部分完成 | 已有分段 E2E，缺单一贯穿全链路测试文件，剩余 2-3d |
| 10 | 测试覆盖率 ≥60% | 5-7d | ⚠️ 部分完成 | 用例数 283→390，覆盖率百分比未实测，剩余 3-5d |
| 11 | Cypher 性能基准 | 1-2d | 🟢 未启动 | 无变化 |
| 12 | vLLM 部署 | 2-3d | 🟢 未启动 | 无变化，依赖驱动升级 |
| 13 | Neo4j 数据库层只读 | 0.5d | 🟢 未启动 | 应用层方案已够用，非阻塞项 |

**小结：13 项中已完成 5 项（BOM导入、电压标注率、AMR覆盖率、Self-Correction、以及 WebSocket 修复归入#3的一部分），真正仍需投入的核心缺口是 #2 专业 Embedding 模型切换 —— 这是唯一完全未推进的 P0 项。**

---

## 七、风险评估与建议

### 7.1 高风险

| 风险 | 影响 | 缓解措施 | 09-30 状态 |
|------|------|----------|-----------|
| **Embedding 质量不佳** | 向量检索准确率低，GraphRAG 效果打折 | 部署 bge-m3 专业模型，评估检索质量指标 | 🔴 仍未解决 — 唯一剩余高风险项 |
| **前后端接口不同步** | 用户操作报错，体验差 | 建立前后端接口契约（OpenAPI schema），自动化联调 | ⚠️ WebSocket 已修复，schema 核对未做 |
| **HITL 闭环未验证** | 规则沉淀流程可能断裂 | 选 3-5 个真实 PDF 做端到端验证 | ⚠️ 真实 PDF 已验证，Neo4j 落库仍是 mock |

### 7.2 中风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **vLLM 兼容性** | PRD 要求 vLLM，但 T4 驱动不兼容 | 继续使用 Ollama（51.9 tok/s 够用），vLLM 作为后续优化 |
| **电压标注率低** | 电源域分析不完整 | 区分核心/普通网络，对核心网络设 100% 阈值 |
| **LlamaIndex 迁移成本** | 自研方案已可工作，迁移 ROI 不确定 | 评估检索质量，若 <85% 再考虑迁移 |

### 7.3 建议路线图（2026-09-30 更新，仅列剩余工作）

```
已完成（无需再排期）：
  ├── BOM CSV 导入 ✅
  ├── 网络电压标注率提升（核心网 100%）✅
  ├── AMR 覆盖率提升至 99.8% ✅
  ├── Self-Correction 节点 ✅
  └── WebSocket 硬编码修复 ✅

剩余 Week 1: P0 收尾
  ├── 专业 Embedding 模型切换（bge-m3/bge-large-zh 默认值 + 索引重建）—— 唯一真正阻塞项
  ├── 前后端 API schema 系统性核对
  └── HITL 闭环补一次真实 Neo4j（非 mock）验证

剩余 Week 2-3: P1 收尾
  └── LlamaIndex 评估（依赖 Embedding 先完成）

剩余 Week 4-6: P2 质量保障
  ├── E2E 单一贯穿测试文件（网表上传→ETL→审查→报告→HITL）
  ├── 测试覆盖率实测 + 补充至 60%
  ├── Cypher 性能基准
  └── vLLM 部署（如驱动升级）
```

---

## 附录：数据底座最新状态

| 指标 | V1 (05-14) | V2 (06-08) | 变化 |
|------|------------|------------|------|
| Components | 12,688 | 12,688 | — |
| Pins | 49,570 | 49,570 | — |
| Nets | 8,159 | 8,159 | — |
| PartType UNKNOWN | 120→1 | 1 | — |
| Pin.Type 覆盖率 | 100% | 100% | — |
| POWERED_BY | 955→593 | 593 | ETL schema 演进 |
| 网络电压标注率 | 17.3% | 20.7% | +3.4% |
| AMR 电容耐压覆盖率 | 85%→99.8% | 83.1%* | *注: 统计口径可能不同 |
| VectorChunk | 0→949 | 1,901 | +952 |
| DESCRIBES 关系 | 0 | 10,504 | 新增 |
| Communities | 0 | 22 | 新增 |
| KnowledgeSource | 0 | 5 | 新增 |
| Review 规则数 | 14 | 24 | +10 |
| 测试用例 | ~179 | 283 | +104 |
| 集成测试 | 0 | 28 | 新增 |

---

*报告由 Jarvis 基于 PRD_V5.0 与项目代码 commit `d0c746d` 生成*
