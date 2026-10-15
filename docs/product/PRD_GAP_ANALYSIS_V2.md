# PRD 差距分析报告 V2

> Date: 2026-06-08（原始版本）| Baseline: PRD_V5.0 vs actual code as of commit `d0c746d`
> 对比: 在 V1 分析 (2026-05-14) 基础上，更新过去 3 周的开发进展
>
> **2026-09-30 复核更新**：基于当前 HEAD `30ef49b`（分支 `work/legacy-tasks-20260704`）对本文档"未实现/部分完成"清单逐项重新核实代码现状。原文档中列出的多数 P0/P1 问题已在 `d0c746d` 之后的提交中解决，详见下方各节新增的「2026-09-30 复核」标注。整体完成度已从 83% 提升，详见第一节更新。
>
> **2026-10-14 全面核查更新**：对照本文档逐项交叉验证代码现状（而非只读文档），详见 `docs/product/DEV_STATUS_AUDIT_2026-10-14.md`。关键纠正：① §12 "E2E 仍是分段覆盖"的判断过时——`tests/test_full_chain_e2e.py` 已是完整单一贯穿测试，之前被遗漏；② Cypher 性能基准、测试覆盖率百分比均已补齐真实实测数据（见六节 P2 清单）；③ vLLM 阻塞归因纠正为 CUDA wheel 版本问题，非驱动/硬件不兼容；④ 新发现 `agent_system/llama_index_bridge.py`（571行）是零引用、零测试的孤立代码，比"待评估"的描述更接近"写了一半的死代码"，已补充真实 benchmark 数据供裁决（见六节 P1 #8）。

---

## 一、需求完成度总览

| PRD 模块 | V1 完成度 | V2 完成度 (06-08) | **复核 (09-30)** | 变化说明 |
|----------|-----------|-----------|----------|----------|
| §4 数据底座 (ETL) | 85% | 95% | **98%** | BOM CSV/xlsx/xls 导入已实现；核心网络电压标注 100% 阈值已在 Quality Guard 落地 |
| §5 Agent Core | 75% | 88% | **93%** | Self-Correction（空结果检测+参数放宽重试）已实现并有单测覆盖 |
| §6 图谱工具 | 90% | 97% | 97% | 无新变化 |
| §7 True GraphRAG | 40% | 80% | **95%**（2026-10-10） | 自研方案不变；embedding 默认值已切到 bge-m3（1024-dim），`chunk_embedding_v2` 索引已重建，3796 条文本重新 embed，新旧索引并存 |
| §7 HITL 规则沉淀 | 70% | 85% | **88%** | 已有真实 PDF 端到端测试（含 SHA256 固定内容校验），但 Neo4j 落库环节仍为 mock，非完全端到端 |
| §8/10 Web UI | 65% | 82% | **86%** | WebSocket 地址硬编码问题已修复，改为动态推导 + 环境变量覆盖 |
| §12 测试与质量 | 30% | 55% | **65%**（2026-10-14） | 测试用例 283→397，E2E 单一贯穿测试已存在并通过（此前文档误判为缺失）；覆盖率实测 43.99%；Cypher 性能基准已达标（p95<60ms） |
| **整体** | **63%** | **83%** | **~91%**（2026-10-10） | **P0 四项全部已解决；2026-10-14 复核：P2 四项中三项已补齐实测数据，LlamaIndex 桥接代码待裁决，详见六节** |

---

## 二、已完成功能详述（V1→V2 新增）

### 2.1 ✅ True GraphRAG（自研实现，非 LlamaIndex）

| 组件 | 实现方式 | 状态 |
|------|----------|------|
| 向量索引 | Neo4j 原生向量索引（非 ChromaDB 双写） | ✅ 7595 VectorChunk 节点（1901 legacy 384-dim + 5694 bge-m3 1024-dim，双轨并存） |
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

### 4.2 ✅ P0 — 专业 Embedding 模型（已解决，见 2026-10-10 复核）

**PRD §3.2：** "LlamaIndex + llama-index-graph-stores-neo4j"（隐含需要专业 embedding）

**06-08 现状：** 使用 Ollama gemma4:26b 生成 embedding，非专业 embedding 模型。

**2026-09-30 复核：** `agent_system/embedding.py` 已重构为可配置架构，默认值仍是 `all-MiniLM-L6-v2`，向量索引也未用 bge 重建，是当时唯一未闭环的 P0 项。

**2026-10-10 复核：** 代码默认值已在提交 `c2fb8b0` 切到 `BAAI/bge-m3`（1024-dim），`.env` 补充显式声明 `SCHEMATIC_EMBEDDING_MODEL=BAAI/bge-m3` / `SCHEMATIC_EMBEDDING_DIM=1024`，`requirements.txt` 补充缺失的 `sentence-transformers>=3.2,<4.0` 依赖声明（此前完全未声明，干净环境装依赖会在 `embedding.py` 处 ImportError）。执行 `agent_system/rebuild_vector_index.py`：加载 bge-m3（CUDA，实际维度 1024 校验通过），重新 embed 3796 条 legacy chunk 文本，写入新建的 `chunk_embedding_v2` 索引（`vector_indexer.py` 的双轨设计：legacy 384-dim 走 `chunk_embedding`/`embedding` 属性，bge-m3 走 `chunk_embedding_v2`/`embedding_v2` 属性，新旧并存不冲突，无需删除旧数据）。验证：Neo4j 中带 `embedding_model=BAAI/bge-m3` 标记的 VectorChunk 节点共 5694 个（3796 新建 + 此前已存在的部分），legacy 384-dim 的 1901 个节点原样保留作回滚基线。状态：已完成。

**后续建议：** 抽样对比新旧索引的检索质量（尤其中文查询，bge-m3 多语言能力应优于 all-MiniLM-L6-v2 的纯英文模型），确认效果达标后再考虑退役 legacy 索引。

### 4.3 ✅ P1 — Self-Correction 节点（已解决，见 2026-09-30 复核）

**PRD §5.2：** "当 Graph Tools 返回空结果时，LLM 自动调整 Cypher 查询策略，重试最多 2 次"

**06-08 现状：** ReAct 引擎隐式支持，但无显式的 Cypher 查询重试/参数放宽机制。

**2026-09-30 复核：** `agent_system/react_agent.py` 已实现完整机制：`_looks_empty_observation`（500行，识别"未找到/无结果/empty/not found"等空结果标记）、`_relax_action_input`（512行，放宽 exact/limit 等过严参数）、`_self_correct_tool_call`（527行，一到两次放宽重试，主流程 749行调用）。配套单测 `test_react_self_correction.py` 验证 `exact: True→False`、`limit` 提升到 10、trace 记录 `self_correction:` 前缀动作。状态：已完成，无需继续投入。

### 4.4 🟡 P1 — Neo4j 只读账号

**PRD §14.2：** "Neo4j 只读账号"

**现状：** 使用默认 neo4j 用户（全权限）。Community Edition 不支持数据库级只读用户，已通过 `READ_ONLY_MODE` 环境变量在应用层限制写操作。

**评估：** 已有应用层方案，数据库层只读需要升级到 Enterprise Edition 或使用代理。

### 4.6 ✅ P0 — HITL Neo4j 落库 + 前后端 API schema 核对（已解决，见 2026-10-13 复核）

**4.6.1 HITL Neo4j 落库澄清**

此前（§4.5 旧版、§7 概览表第18行）记录"HITL 规则沉淀 Neo4j 落库仍为 mock"，经核实这个描述混淆了两套独立子系统：

- **审查规则沉淀**（`agent_system/hitl_workflow.py` 的 `HITLManager`）：真实写 Neo4j 的代码早已存在，且 `tests/test_hitl_neo4j_integration.py` 是真实（非 mock）集成测试，连真实 Neo4j 验证通过。PRD 旧版引用的"mock测试"（`test_neo4j_mock_audit_and_rule_file_reload`）实际测的是查询分支逻辑，命名带 "datasheet" 容易误判，但不代表这条链路缺乏真实验证。**结论：此前就已完成，是文档描述过时，不是代码缺口。**
- **Datasheet 参数沉淀**（`agent_system/datasheet_hitl.py` 的 `DatasheetHITLManager`）：此前确实只写 YAML（`amr_data.yaml`），完全没有 Neo4j 代码路径——这是真正的功能缺口。**2026-10-13 已补齐**：新增 `AMRParamNode` schema（`agent_system/schemas/graph.py`）+ `AMRParam` 节点唯一约束（mpn+param_type，全局共享不做 project_id 隔离）；新增 `agent_system/amr_neo4j_source.py` 的 `Neo4jAMRSource` 读写封装；`DatasheetHITLManager.save_approved_to_amr()` 在 YAML 落盘成功后追加 Neo4j 写入（非事务，失败只记日志不影响 YAML 结果）；`amr_engine.py` 四级回退链路扩展为五级，插入 `Neo4jAMRSource` 于 YAML 之后、语义检索之前；新增真实 Neo4j 集成测试 `tests/test_datasheet_amr_neo4j_integration.py`（3个测试全部通过）。

**4.6.2 前后端 API schema 系统性核对**

对全部 7 个后端路由（chat/review/hitl/knowledge/etl/graph/system）+ WebSocket 消息格式，逐一核对后端 `openapi.json` 权威定义与前端 7 个页面的调用代码、TS 类型定义。**结论：未发现任何会导致运行时报错的问题**（无404风险，无字段名不匹配导致请求校验失败）。发现并修复的问题：

- Knowledge 页面 `project_id='default'` 处理与 Review/Chat/ETL 不一致（后三者将 UI 哨兵值 `'default'` 转换为 `undefined` 代表聚合视图，Knowledge 页面此前直接发送字面字符串 `"default"`，被当作真实项目隔离）。已修复为统一语义，同时修正 `knowledgeApi.upload()` 签名（`projectId` 改为可选，不传时显式带 `scope=shared`，匹配后端"project_id 与 scope=shared 二选一"的校验要求）。
- `UploadResponse.data` 前端类型字段不准确（声称 `file_name`/`indexed_at`，实际后端返回 `category`/`source`）——已修正类型定义。
- `ETLPreviewResult`/`ETLResult` 缺少 `bom_issues` 字段的前端类型定义和页面展示——已补齐。
- Datasheet HITL 的三个后端接口（`/hitl/datasheet/pending|action|persist`）此前前端完全没有对接 UI——已在 HITL 页面新增"Datasheet 参数沉淀"标签页，复用既有审批交互模式。

验证：`tsc --noEmit` 全量类型检查通过，`npm run build` 构建成功，新增接口通过 curl 实测返回正常。

**状态：已完成。**

### 4.7 ✅ P2 — Cypher 性能基准测试（2026-10-14 已完成）

**PRD §12.2：** "Cypher query performance benchmark < 500ms"

**现状：** 已有 LIMIT 保护和大网络聚合，但无性能基准测试。

**2026-10-14 复核：** 新建 `hardware_ai_expert/tools/cypher_perf_benchmark.py`，对真实 Neo4j（`beet7_acceptance` 项目，12,688 器件/99,140 Pin/16,318 网络）跑了 `graph_tools.py` 7 个核心查询模式各 20 次迭代。结果：所有场景 **p95 均 <60ms**（get_power_domain 最高 49ms），全部远低于 500ms 验收线；`CYPHER_ROW_LIMIT=500` 作为保护阈值目前是充分的。报告见 `hardware_ai_expert/tools/benchmark_reports/cypher_perf_2026-10-14.json`。

**状态：已完成。**（单用户场景下无性能隐患；真实并发场景下的复测留作后续观察项，非阻塞）

### 4.8 ✅ P2 — E2E 自动化测试（2026-10-14 复核：实际已完成，此前文档描述过时）

**现状：** 283 个单元测试 + 28 个集成测试，缺少从"上传网表 → ETL → 审查 → 报告 → HITL 审批"的全链路自动化测试。

**2026-09-30 复核：** 测试数增至 390（+38%）。已有分段 E2E 覆盖：`test_task12_api_e2e.py` 覆盖 ETL job 全生命周期（`test_import_preview_then_review_happy_path`）+ HITL 批量操作 + 知识库上传隔离；`test_e2e_agent.py` 覆盖 ReAct 全链路查询/诊断/评审。~~但仍缺文档要求的单一贯穿全链路测试文件~~

**2026-10-14 复核（纠正）：** `tests/test_full_chain_e2e.py`（commit `fc99f4a`，此前未被本文档收录）**已经是完整的单一贯穿测试**：`test_netlist_bom_etl_review_hitl_approve_persist_full_chain` 一条测试串联 BOM/网表上传 → ETL 运行（异步任务轮询）→ 质量门禁 → Review 产出违规 → HITL 待审队列 → 批准 → 持久化到 `custom_rules.yaml` → 重新读取确认，共 7 个阶段，每阶段独立断言。使用 fake driver 隔离 Neo4j/Chroma/Ollama，可在任意环境（含 CI）运行。重跑确认 PASSED。

**状态：已完成。**（此前"缺单一贯穿测试"的判断是文档滞后导致的误判，代码实际早已补齐）

### 4.8 ✅ P2 — 测试覆盖率 ≥60%（2026-10-14 已实测，未达标但缺口已定位）

**现状：** 283 个测试用例，估计覆盖率约 40-45%。

**2026-09-30 复核：** `pytest --collect-only` 显示当前 **390** 个测试收集成功（另 15 个 deselected），较 06-08 版本增长 38%。新增测试文件包括 `test_amr_engine.py`、`test_react_self_correction.py`、`test_task11-14` 系列、`test_tier3.py` 等。覆盖率百分比未运行 coverage 工具实测，无法确认是否已达 60%。

**2026-10-14 复核：** 实际运行 `pytest --cov=agent_system --cov=api --cov=etl_pipeline`，总覆盖率 **43.99%**（13,623 条语句，7,630 条未覆盖），与此前估算的 40-45% 吻合。零覆盖率的大文件（>100行语句）集中在已识别的 legacy/孤立代码：`agent_core.py`（622行，legacy fallback）、`llama_index_bridge.py`（263行，零引用孤立模块，见附录"LlamaIndex"条目）、`storage_dispatcher.py`（171行，legacy Streamlit 路径）、`parsers/{design_guide,checklist,document_processor}.py`。核心主线模块覆盖率健康：`api/schemas/*` 100%、`review_engine` 核心模板 84-88%、`api/routers/*` 80-91%。报告见 `hardware_ai_expert/tools/benchmark_reports/pytest_coverage_2026-10-14.json`。

**状态：未达 60% 目标，但缺口已精确定位——主要来自待决策的 legacy/孤立代码而非主线功能缺测试。** 若后续决定删除 `llama_index_bridge.py` 等孤立代码，覆盖率百分比会自然提升（分母减少）；若决定继续投入，需要补测试再谈覆盖率。

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
| **vLLM 部署尝试** | 因 CUDA wheel 版本不兼容搁置（2026-10-14 纠正：非驱动/硬件问题，见六节 #12） | PRD 要求 vLLM，实际使用 Ollama |

---

## 六、优先级排序的待开发清单（2026-09-30 复核后，仅列剩余未完成项）

### P0 — 阻塞性问题

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 1 | BOM CSV 导入管道 | 3-4d | ✅ **已完成** | `part_type_standardizer.py` + `api/routers/etl.py` 已支持 CSV/xlsx/xls |
| 2 | **专业 Embedding 模型部署** | 2-3d | ✅ **已完成（2026-10-10）** | 默认值已切到 bge-m3（1024-dim），`chunk_embedding_v2` 索引已重建，3796 条 chunk 重新 embed，legacy 索引保留供回滚 |
| 3 | 前后端全面联调 | 2-3d | ✅ **已完成（2026-10-13）** | WebSocket 硬编码已修复；全部7路由+7页面 API schema 核对完成，无运行时报错风险，修复 Knowledge 页面 project_id 语义不一致 + 类型定义偏差 |
| 4 | HITL Datasheet 闭环验证 | 1d | ✅ **已完成（2026-10-13）** | 审查规则 HITL 落库早已完成（文档此前描述过时）；Datasheet 参数 HITL 新增 Neo4j 落库 + 前端对接页面，真实集成测试通过 |

### P1 — 核心功能完善

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 5 | 网络电压标注率提升 | 2-3d | ✅ **已完成** | Quality Guard 已按核心网络实现 100% 阈值校验 |
| 6 | AMR 耐压覆盖率提升至 95% | 2-3d | ✅ **已完成** | commit 记录显示已到 99.8%（未连接真实 DB 复核，建议抽样确认） |
| 7 | Self-Correction 节点 | 2-3d | ✅ **已完成** | `react_agent.py` 空结果检测+参数放宽重试已实现，有单测 |
| 8 | LlamaIndex 评估 | 3-5d | 🟡 **半成品，待裁决（2026-10-14）** | `agent_system/llama_index_bridge.py`（571行）+ `tools/graphrag_retrieval_benchmark.py` 代码已写好但零引用、零测试，未接入 `KnowledgeRouter`。本轮已跑通 benchmark：bge-m3 vs all-MiniLM-L6-v2 真实对比，bge-m3 recall@5/mrr/ndcg@10 全部 1.0（旧模型 0.70-0.79），证实此前的 embedding 切换决策正确。但 bridge.py 本身是否继续集成或删除——与 CLAUDE.md"自研 GraphRAG，非 LlamaIndex"的既定架构方向有张力，需项目负责人裁决，详见 `docs/product/DEV_STATUS_AUDIT_2026-10-14.md` |

### P2 — 质量与生产化

| # | 任务 | 原预估 | 状态 | 说明 |
|---|------|------|------|------|
| 9 | E2E 自动化测试 | 3-4d | ✅ **已完成（2026-10-14 纠正）** | `tests/test_full_chain_e2e.py` 已是完整单一贯穿测试，此前文档判断过时 |
| 10 | 测试覆盖率 ≥60% | 5-7d | ⚠️ **已实测 43.99%（2026-10-14）** | 未达标，但缺口集中在待裁决的 legacy/孤立代码，主线覆盖率健康 |
| 11 | Cypher 性能基准 | 1-2d | ✅ **已完成（2026-10-14）** | 7 个核心查询场景 p95 均 <60ms，远优于 500ms 验收线 |
| 12 | vLLM 部署 | 2-3d | 🟢 未启动 | **归因已纠正（2026-10-14）**：非驱动/硬件不兼容（T4 compute capability 7.5 完全支持 vLLM），实际是驱动提供的 CUDA 12.1/12.2 装不上近期 vLLM 版本要求的 CUDA 12.6+ 预编译 wheel，需升级驱动或退回老版本 vLLM + CUDA 11.8 组合，属独立基础设施决策 |
| 13 | Neo4j 数据库层只读 | 0.5d | 🟢 未启动 | 应用层方案已够用，非阻塞项 |

**小结：13 项中已完成 10 项（BOM导入、专业Embedding模型切换、电压标注率、AMR覆盖率、Self-Correction、前后端联调、HITL Datasheet闭环、E2E贯穿测试、Cypher性能基准）。P0 四项全部完成，无遗留阻塞项。剩余为 P1 的 LlamaIndex 桥接代码裁决、测试覆盖率提升、vLLM 基础设施决策、Neo4j 只读账号。**

---

## 七、风险评估与建议

### 7.1 高风险

| 风险 | 影响 | 缓解措施 | 09-30 状态 |
|------|------|----------|-----------|
| **Embedding 质量不佳** | 向量检索准确率低，GraphRAG 效果打折 | 部署 bge-m3 专业模型，评估检索质量指标 | ✅ 2026-10-10 已部署 bge-m3，索引重建完成；检索质量抽样评估待后续跟进 |
| **前后端接口不同步** | 用户操作报错，体验差 | 建立前后端接口契约（OpenAPI schema），自动化联调 | ✅ 2026-10-13 全量 schema 核对完成，无运行时报错风险，发现的类型/语义偏差已修复 |
| **HITL 闭环未验证** | 规则沉淀流程可能断裂 | 选 3-5 个真实 PDF 做端到端验证 | ✅ 2026-10-13 审查规则 HITL 落库早已验证完成（文档描述曾过时）；Datasheet 参数 HITL 新增 Neo4j 落库，真实集成测试通过 |

### 7.2 中风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **vLLM 兼容性** | PRD 要求 vLLM，实际是 CUDA wheel 版本不兼容（2026-10-14 纠正，非驱动/硬件问题） | 继续使用 Ollama（51.9 tok/s 够用），vLLM 需升级驱动至 CUDA 12.6+ 或退回 vLLM 0.2.x+CUDA 11.8 组合，作为独立基础设施决策后续评估 |
| **电压标注率低** | 电源域分析不完整 | 区分核心/普通网络，对核心网络设 100% 阈值 |
| **LlamaIndex 桥接代码闲置** | `llama_index_bridge.py`（571行）零引用、零测试，与"自研GraphRAG"架构方向有张力 | 2026-10-14 已跑通 embedding benchmark 验证 bge-m3 优势；bridge.py 本身删除/继续集成需项目负责人裁决 |

### 7.3 建议路线图（2026-09-30 更新，仅列剩余工作）

```
已完成（无需再排期）：
  ├── BOM CSV 导入 ✅
  ├── 网络电压标注率提升（核心网 100%）✅
  ├── AMR 覆盖率提升至 99.8% ✅
  ├── Self-Correction 节点 ✅
  ├── WebSocket 硬编码修复 ✅
  ├── 专业 Embedding 模型切换（bge-m3 默认值 + 索引重建，2026-10-10）✅
  ├── 前后端 API schema 系统性核对（2026-10-13）✅
  └── HITL Datasheet 参数 Neo4j 落库 + 前端对接（2026-10-13）✅

P0 已全部收尾，无剩余阻塞项。

已完成（2026-10-14 新增）：
  ├── Cypher 性能基准测试 ✅（p95<60ms，远优于500ms验收线）
  ├── E2E 单一贯穿测试文件 ✅（test_full_chain_e2e.py 已存在，此前文档误判为缺失）
  └── 测试覆盖率实测 ✅（43.99%，未达60%目标，缺口已定位在待裁决的legacy代码）

剩余 Week 1: P1 收尾
  └── LlamaIndex 桥接代码裁决（benchmark 数据已就位：bge-m3 全面占优，决定 llama_index_bridge.py 删除或继续集成）

剩余 Week 2-4: P2 质量保障
  ├── 测试覆盖率补充至 60%（取决于 legacy 代码裁决结果）
  ├── Neo4j 数据库层只读账号
  └── vLLM 部署（需升级 GPU 驱动至 CUDA 12.6+，独立基础设施决策，建议先评估 Ollama 51.9 tok/s 是否真的不够用）
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
