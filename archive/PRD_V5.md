# 统一硬件 AI 专家系统（审查与诊断）产品需求文档 (PRD) - V5.0

版本: V5.0 (架构重构与高可靠演进版) | 日期: 2026-04-30
说明: 本版本基于 V4.0 代码基线进行深度重构，重点修复了“伪 GraphRAG”断层、粗暴图谱截断、硬编码路由等架构隐患，确立了“高可靠 ETL -> 真实图谱增强 -> 本地安全推理”的演进路径。

## 1. 产品愿景与定位

打造一个基于本地化推理、隐私绝对安全的 Agentic 硬件辅助系统。通过构建物理单板的"数字孪生"底座，并结合 Neo4j 与 LlamaIndex 驱动的 True GraphRAG 技术，实现硬件全生命周期的核心闭环：

• **左移防御（原理图审查）：** 在设计阶段，利用确定性规则与专家库结合，自动化巡检拓扑，精准拦截器件选型与连接违规。
• **右移排障（硬件故障诊断）：** 结合上下文感知多维图搜索，支持针对电源树失效、高频总线等复杂故障的根因定位。
• **终身学习（高置信知识获取）：** 建立基于 HITL（人类在环）的 Datasheet 参数提取机制，持续沉淀企业级本地专家知识库。

## 2. 核心架构重构说明 (V4.0 -> V5.0)

| 痛点问题 (V4.0) | 重构方案 (V5.0) | 核心价值 |
|----------------|----------------|---------|
| ETL 容错差 (缺失 Pin.Name/Type) | **强制化语义解析：** 升级解析器，引入轻量级本地 NLP/小模型字典，精准补齐缺失引脚名与器件类型 (PartType)。 | 避免下游规则（如 MUX 检查）彻底瘫痪。 |
| 伪 GraphRAG 割裂 | **True GraphRAG 融合：** 使用 LlamaIndex 将 ChromaDB 中的文档 Chunk 与 Neo4j 实体建立 [:DESCRIBES] 关系，实现图向量联合检索。 | 一次 Query 同时获取"物理连接关系"与"芯片手册规范"。 |
| 图谱工具暴力截断 (MAX=50) | **Cypher 下推与特征聚合：** 废除硬截断。对于超大节点网络（如 GND/VCC），下推至图库层聚合特征摘要（如"包含 120 个电容"）。 | 防止 Agent 获取残缺拓扑导致误判。 |
| 状态机意图识别僵化 | **轻量级 LLM 路由引擎：** 引入轻量级 LLM Classifier 替代正则匹配，支持复杂/混合工程意图拆解与队列执行。 | 工程师可自然提问，不再需要输入指令化关键词。 |
| Datasheet 提取幻觉 | **HITL 审核流：** 所有通过大模型提取的 AMR 耐压、阻容公式，必须经审核区（Pending）确认后方可落盘生效。 | 保证规则库 100% 确定性，拒绝"烧板子"风险。 |

## 3. 系统整体架构

### 3.1 技术架构图

```
用户输入 (CLI / Web UI)
 |
 +----v----+
 | Agent | 轻量级 LLM 路由 (Intent Parser & Task Queue) -> 拆解复合任务
 | Core | 状态机演进: parse -> plan -> tool_execution -> reasoning -> report
 +----+----+
 |
 +----v-------------+ +------------------+ +---------------------------------+
 | Review Engine | | Smart Graph Tools| | LlamaIndex True GraphRAG Router |
 | (确定性规则校验) | | (Cypher 聚合查询)| | (Tier 1 本地 / Tier 2 接口) |
 +----+----+----+ | +--------+-------+ +--------+------------------------+
 | | | | | | (Semantic + Topology)
 +----v----+ | | | |
 | AMR | | | | +---v---+ [:DESCRIBES] +--------+
 | Engine | | | +---------------> Neo4j <----------------> Chroma |
 +----------+ | | +---+---+ +--------+
 | | |
 +---------------v----v-------------------------------v---+
 | ETL Pipeline & Quality Guard |
 | 网表解析 -> NLP 实体对齐 -> 孤儿节点清洗 -> 强类型注入|
 +--------------------------------------------------------+
```

### 3.2 核心依赖栈更新

• **大模型推理底座:** 本地部署 vLLM 推理框架加速开源大模型（如 Llama3-70B-Instruct 或 Qwen），保障本地响应速度与极低的系统延迟。
• **图文融合引擎:** llama-index + llama-index-graph-stores-neo4j。
• **其他必备:** neo4j (>= 5.26), chromadb, pydantic。

## 4. 数据底座层 (ETL) 强化方案

**优先级: 绝对 P0。数据不净，业务不兴。**

### 4.1 强制提取与对齐规则

• **Pin.Name 强制捕获：** 修改 chip_parser.py。若原生数据确实遗漏，启动 fallback 机制（根据封装与网表历史推演），并向控制台抛出 Critical Warning。
• **PartType 智能标准化：**
  • 废弃原始硬编码正则匹配。
  • 引入本地轻量级字典与 NLP 对齐服务：读取 BOM 的 Description 字段，将其映射为标准的 [MCU, PMIC, FPGA, LDO, BUCK, CONNECTOR, PASSIVE] 等枚举类型。

### 4.2 数据质量守门员 (Quality Guard)

新增前置拦截模块，阈值如下：
• Component PartType 标准化率 < 90% -> 阻断运行。
• 核心网络 (VCC/GND/3V3 等) 识别率 < 100% -> 阻断运行。

## 5. Agent Core 核心流转 (V2.0)

从“单线关键词状态机”升级为“任务队列执行器”。

### 5.1 混合意图拆解 (The Router)

当用户输入："查一下板子上的 I2C 上拉有没有问题，另外 TPS5430 的 VOUT 公式是什么？"

LLM Router 将输出结构化任务队列：
 1. Task 1: [REVIEW] target="I2C_BUS", rule="pullup_check"
 2. Task 2: [KNOWLEDGE_QUERY] component="TPS5430", intent="VOUT_formula"

### 5.2 防死循环与容错

• 设定 MAX_STEPS = 15。
• 增加 Self-Correction 节点：当 Graph Tools 返回空结果时，LLM 自动调整 Cypher 查询策略（例如放宽匹配条件），重试最多 2 次。

## 6. Smart Graph Tools (智能图谱工具箱)

解决原版粗暴截断问题，引入计算下推。

### 6.1 智能特征聚合 (Feature Aggregation)

针对 get_net_components 工具：
• **旧版:** 找到 GND，返回前 50 个节点，导致后续推断彻底错误。
• **新版逻辑:**
  • 若节点数量 > 阈值，在 Cypher 层聚合统计（如："该网络包含 120 个电容，3 个电阻"）。
  • 返回聚合摘要而非截断列表，保留完整拓扑语义。

### 6.2 增加高级高频/电源路径工具

• 预留 `trace_differential_pair(start_pin)` 工具，专用于未来排查 PCIe、MIPI 等差分走线的一致性。
• 升级 `get_power_tree()`，基于强化的 [:POWERED_BY] 关系支持从 LDO 向下钻取完整供电树拓扑。

## 7. 知识外脑 (True GraphRAG & HITL)

### 7.1 LlamaIndex 图文桥接

当解析一份包含 TPS5430 信息的 PDF 时：
 1. 将 PDF 切片存入 ChromaDB。
 2. 提取实体 (Component: "TPS5430")，在 Neo4j 中建立或匹配该节点。
 3. 建立关系：`(VectorChunk_ID)-[:DESCRIBES {type: "electrical_spec"}]->(Component: "TPS5430")`。
 4. Agent 检索时，可从图谱节点的关联边直接跳跃提取 Chroma 语义数据。

### 7.2 HITL 规则沉淀工作流

• LLM 自动从 PDF 提取出 AMR 降额参数（如电容耐压=50V）。
• 该参数状态标记为 `Pending_Review`，存入本地 SQLite/Neo4j。
• 在未来的 Web UI 仪表盘中，由资深硬件工程师点击【Approve】。
• 审批通过后，正式注入审查规则引擎的 `default_rules.yaml` 和 AMR 引擎中。

## 8. 实施路线图 (Roadmap)

### Phase 1: 底座重建与防爆机制 (Weeks 1-2)
• **[P0]** 强化 ETL Pipeline，强制提取 Pin.Name，实现 BOM Description 辅助的 PartType 标准化。
• **[P0]** 引入 Quality Guard 脚本，不达标网表直接熔断。
• **[P1]** 重构 Graph Tools，实现 Cypher 计算下推与智能特征聚合，废除 50 节点截断。

### Phase 2: Agent 升级与 True GraphRAG (Weeks 3-4)
• **[P0]** 使用 LlamaIndex 将 ChromaDB 与 Neo4j 打通，建立 [:DESCRIBES] 关系网络。
• **[P1]** 重构 Agent Core，上线基于本地大模型（如 vLLM 驱动的开源模型）的 Intent Router 队列。
• **[P2]** 打通本地 Datasheet 库 -> HITL 审批流 -> Rule Capsule 的测试数据闭环。

### Phase 3: 高级审查规则与 Web 闭环 (Weeks 5-6)
• **[P1]** 补齐 AMR 电容降额逻辑（依托 Phase 2 沉淀的耐压数据）。
• **[P1]** 开发 Streamlit Web UI，实现可交互的节点图谱可视化（PyVis/Echarts）。
• **[P2]** 在 UI 层上线 HITL 白名单审批操作看板。
