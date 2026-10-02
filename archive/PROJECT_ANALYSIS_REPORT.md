# 项目现状 vs PRD V5.0 对比分析报告

**生成日期**: 2026-05-28  
**PRD 版本**: V5.0 (架构重构与高可靠演进版)  
**代码基线**: `/data/schematic_agent/hardware_ai_expert/`  
**总代码量**: ~28,363 行 Python + 340 行 YAML 规则

---

## 总体完成度: 72%

| 维度 | 完成度 | 说明 |
|------|--------|------|
| 数据底座层 (ETL) | 85% | 核心功能完备，Pin.Name fallback 机制偏弱 |
| Agent Core | 75% | ReAct 框架已实现，Self-Correction 缺失 |
| Smart Graph Tools | 80% | 聚合/差分/电源树已实现，Cypher 重试缺失 |
| True GraphRAG | 60% | 桥接层已有，但未使用 LlamaIndex |
| HITL 知识沉淀 | 70% | Datasheet HITL 完整，Web UI 审批部分实现 |
| Web UI | 75% | 主界面+4 子页面，HITL 看板功能待补全 |
| 审查引擎 | 90% | 10 个规则模板 + YAML 配置体系完整 |
| 测试覆盖 | 65% | 198 个测试用例，缺少 E2E 真实数据测试 |

---

## 按 PRD 章节逐项分析

### 第1章: 产品愿景与定位

| 需求项 | 状态 | 说明 |
|--------|------|------|
| 左移防御（原理图审查） | ✅已完成 | Review Engine 完整实现，10 个模板 + YAML 规则 |
| 右移排障（硬件故障诊断） | 🟡部分完成 | Agent 可对话式诊断，但缺少专用故障根因定位流程 |
| 终身学习（HITL 知识获取） | 🟡部分完成 | Datasheet HITL 流程已实现，但 Web 审批看板功能有限 |

### 第2章: 核心架构重构 (V4→V5)

| 需求项 | 状态 | 说明 |
|--------|------|------|
| ETL 强制语义解析，Pin.Name fallback | 🟡部分完成 | `chip_parser.py` 提取 Pin.Name，但缺少 PRD 要求的"根据封装与网表历史推演" fallback 机制，仅抛 warning |
| PartType 智能标准化（废弃硬编码正则） | ✅已完成 | `part_type_standardizer.py` (494行) 三层降级策略：BOM Description→Model 规则→Value 推断，20+ 标准类型枚举 |
| True GraphRAG 融合 (LlamaIndex) | ❌未实现 | `graph_rag_bridge.py` (524行) 手动实现了 `[:DESCRIBES]` 关系桥接，但**未使用 LlamaIndex**，而是自定义 ChromaDB+Neo4j 查询 |
| 图谱工具暴力截断废除→Cypher 聚合下推 | ✅已完成 | `graph_tools.py:175` `get_net_components()` 实现了智能聚合，阈值 DEFAULT_AGGREGATION_THRESHOLD=100，大网络自动摘要 |
| 轻量级 LLM 路由替代正则匹配 | ✅已完成 | `llm_intent_router.py` (492行) 实现了 LLM 分类器 + keyword fallback 双路由 |
| Datasheet HITL 审核流 | ✅已完成 | `datasheet_hitl.py` (463行) 完整的 Pending/Approve/Reject 工作流，YAML 持久化 |

### 第3章: 系统整体架构

| 需求项 | 状态 | 说明 |
|--------|------|------|
| Agent Core 状态机 | ✅已完成 | `agent_core.py` (1365行) 实现 parse→plan→tool_execution→reasoning→report 状态流转 |
| ReAct Agent | ➕超出PRD | `react_agent.py` (785行) 实现了完整的 ReAct 循环（Observation→Thought→Action），含复合任务拆解 |
| Review Engine 确定性规则校验 | ✅已完成 | `review_engine/engine.py` + 10 个模板，340 行 YAML 规则配置 |
| Smart Graph Tools | ✅已完成 | `graph_tools.py` (2271行) 含 get_net_components、get_power_domain、get_i2c_devices 等 |
| GraphRAG Router | 🟡部分完成 | 桥接层已实现，但未使用 LlamaIndex 框架 |
| ETL Pipeline & Quality Guard | ✅已完成 | 完整的解析链 + `quality_guard.py` (302行) 阈值拦截 |

### 第3.2章: 核心依赖栈

| 需求项 | 状态 | 说明 |
|--------|------|------|
| vLLM 推理框架支持 | ✅已完成 | `llm_client.py:427` 实现 vLLM OpenAI-compatible 后端，支持 ollama/vllm provider 切换 |
| LlamaIndex 图文融合 | ❌未实现 | 代码中无任何 llama_index 导入或使用 |
| Neo4j >= 5.26 | ✅已完成 | 已部署 Neo4j 5.26.0 |
| ChromaDB | ✅已完成 | 已部署并集成 |
| Pydantic | ✅已完成 | `schemas/` 下 4 个 Pydantic 模型文件 |

### 第4章: 数据底座层 (ETL) 强化

| 需求项 | 状态 | 说明 |
|--------|------|------|
| Pin.Name 强制捕获 + fallback 推演 | 🟡部分完成 | `chip_parser.py` (118行) 提取 Pin.Name，但 fallback 仅为日志 warning，无推演逻辑 |
| PartType 智能标准化 | ✅已完成 | `part_type_standardizer.py` 三层策略完整 |
| Quality Guard 数据质量守门员 | ✅已完成 | `quality_guard.py` PartType≥90%、核心网络100% 阈值拦截 |
| ETL Web 桥接 | ➕超出PRD | `etl_web_bridge.py` (318行) 封装 ETL 为 Web 可调用 |

### 第5章: Agent Core 核心流转 (V2.0)

| 需求项 | 状态 | 说明 |
|--------|------|------|
| 混合意图拆解 (LLM Router) | ✅已完成 | `llm_intent_router.py` LLM 分类 → 结构化任务队列 |
| 复合任务队列执行 | ✅已完成 | `react_agent.py:636` `_run_composite()` 拆解执行多任务 |
| MAX_STEPS 防死循环 | ✅已完成 | `agent_core.py:88` MAX_STEPS=30（PRD 要求 15，更宽松） |
| Self-Correction 节点（空结果时调整 Cypher 重试） | ❌未实现 | 无自动 Cypher 调整重试机制 |

### 第6章: Smart Graph Tools

| 需求项 | 状态 | 说明 |
|--------|------|------|
| 智能特征聚合（大网络摘要） | ✅已完成 | `graph_tools.py:175` Cypher 层聚合，阈值 100 |
| `trace_differential_pair(start_pin)` | ✅已完成 | `graph_tools.py:1375` 差分走线追踪完整实现 |
| `discover_diff_pairs()` | ➕超出PRD | `graph_tools.py:1562` 批量发现差分对 |
| `get_power_tree()` 强化 | ✅已完成 | `graph_tools.py:552` 基于 POWERED_BY 关系的供电树钻取 |
| MPN 解码器 | ➕超出PRD | `mpn_decoder.py` (1440行) 器件型号智能解码 |

### 第7章: 知识外脑 (True GraphRAG & HITL)

| 需求项 | 状态 | 说明 |
|--------|------|------|
| PDF→ChromaDB 切片存储 | ✅已完成 | `document_processor.py` (302行) + `datasheet_processor.py` |
| 实体提取→Neo4j 节点 | ✅已完成 | `graph_rag/indexers/entity_extractor.py` (336行) |
| `[:DESCRIBES]` 关系建立 | ✅已完成 | `graph_rag_bridge.py:152` VectorChunk-[:DESCRIBES]->Component |
| 图向量联合检索 | 🟡部分完成 | 手动实现了从 Component→DESCRIBES→VectorChunk 检索，但未用 LlamaIndex 框架，缺少全局/社区级检索 |
| HITL Pending_Review 机制 | ✅已完成 | `datasheet_hitl.py` Pending→Approve→Reject 完整流程 |
| 审批后注入 default_rules.yaml 和 AMR 引擎 | 🟡部分完成 | `save_approved_to_amr()` 写入 AMR 数据，但**未自动注入 default_rules.yaml** |
| Web UI HITL 白名单审批看板 | 🟡部分完成 | `hitl_review.py` (395行) + `hitl_workflow.py` (469行) 基础审批功能，但看板功能有限 |

### 第8章: 实施路线图对照

| Phase | 需求项 | 状态 |
|-------|--------|------|
| Phase1 P0 | ETL 强化 Pin.Name 强制提取 | 🟡部分完成 |
| Phase1 P0 | Quality Guard 熔断 | ✅已完成 |
| Phase1 P1 | Graph Tools Cypher 聚合下推 | ✅已完成 |
| Phase2 P0 | LlamaIndex ChromaDB↔Neo4j 打通 | ❌未实现（手动桥接代替） |
| Phase2 P1 | LLM Intent Router | ✅已完成 |
| Phase2 P2 | Datasheet→HITL→Rule Capsule 闭环 | 🟡部分完成（缺 Rule 自动注入） |
| Phase3 P1 | AMR 电容降额逻辑 | ✅已完成（`review_engine/templates/amr.py`） |
| Phase3 P1 | Streamlit Web UI + 图谱可视化 | ✅已完成（`graph_viz.py` 872行 PyVis） |
| Phase3 P2 | HITL 白名单审批看板 | 🟡部分完成 |

---

## 超出 PRD 的额外功能 (➕)

| 功能 | 文件 | 说明 |
|------|------|------|
| ReAct Agent | `react_agent.py` (785行) | 完整 ReAct 循环，超出状态机要求 |
| MPN 解码器 | `mpn_decoder.py` (1440行) | 器件型号智能解码系统 |
| 差分对发现 | `graph_tools.py:1562` | 批量发现差分对 |
| ETL Web 桥接 | `etl_web_bridge.py` (318行) | 命令行→Web 封装 |
| 知识库管理页面 | `knowledge_base.py` (765行) | 5 Tab 知识库管理 |
| Agent Orchestrator | `agent_orchestrator.py` (293行) | 多 Agent 编排 |
| TI Datasheet 提取器 | `ti_datasheet_extractor.py` (263行) | TI 器件专用提取 |
| 被动器件类型细化 | `refine_passive_types.py` (87行) | CAP/RES 细分 |
| GraphRAG 社区检测 | `community_detector.py` (222行) | 图谱社区发现 |

---

## 优先级排序的待办清单

### P0 — 架构关键缺失

1. **引入 LlamaIndex 框架** — 当前 `graph_rag_bridge.py` 是手动实现，缺少 LlamaIndex 的全局检索、社区摘要等高级能力。需将现有桥接逻辑迁移到 `llama-index-graph-stores-neo4j`
2. **实现 Self-Correction 节点** — Agent 当 Graph Tools 返回空结果时，无法自动调整 Cypher 查询策略重试。建议在 `react_agent.py` 的 `_execute_tool()` 中增加重试逻辑

### P1 — 功能补全

3. **Pin.Name fallback 推演机制** — `chip_parser.py` 缺少"根据封装与网表历史推演"缺失 Pin.Name 的逻辑
4. **HITL 审批→规则自动注入** — `save_approved_to_amr()` 写入 AMR 数据后，需自动更新 `default_rules.yaml` 和刷新审查引擎
5. **HITL Web 审批看板增强** — `hitl_review.py` 需增加批量审批、过滤、统计等功能
6. **故障诊断专用流程** — 当前诊断依赖通用 ReAct 循环，缺少电源树失效、高频总线等专用根因定位模板

### P2 — 质量提升

7. **E2E 测试补全** — 当前 `test_e2e_agent.py` (209行) 需要真实网表数据集成测试
8. **MAX_STEPS 对齐 PRD** — 当前 30，PRD 要求 15，需评估是否调整
9. **ETL Pipeline 测试** — 缺少 `etl_pipeline/` 下的单元测试
10. **GraphRAG 全局/社区检索** — `global_retriever.py` (129行) 和 `community_detector.py` 已有框架但未与主流程集成

---

*报告由 Jarvis 自动生成，基于 PRD V5.0 与代码库逐项对比*
