# PRD 修改建议书

> 版本: V1.0 | 日期: 2026-04-30 | 调研范围: 代码 + Neo4j 数据 + PRD 文档全量

---

## 一、执行摘要

经过对项目代码、Neo4j 实际数据、PRD 文档的三方交叉验证，发现 **PRD 与代码实现之间存在系统性偏差**。PRD 当前定位是"完整产品愿景文档"，但实际代码处于"核心功能可用、高级特性缺失"的状态。

**建议修改策略**: 将 PRD 从"愿景驱动"调整为**"代码对齐 + 渐进演进"**，明确标注每个模块的"已实现 / 待实现 / 设计变更"状态。

---

## 二、现状差距总览

### 2.1 架构偏差矩阵

| PRD 声明 | 实际状态 | 偏差等级 | 建议处理 |
|----------|----------|----------|----------|
| LangGraph 状态机 | 简化自定义状态机 | 高 | 修改 PRD：降级为"简化状态机"，LangGraph 列为 Phase 3 演进目标 |
| graph_tools: 8+ 工具 | 6 个基础工具 | 高 | 修改 PRD：删除未实现的工具描述，补充实际 6 个工具的 API |
| Web UI (Streamlit) | 空目录 | 高 | 修改 PRD：标记为 Phase 4，剥离到独立文档 |
| Pin.Type = POWER/SIGNAL/GND | 100% 为 None | 高 | 新增设计: 补充 PINUSE 解析 + PartType 推断方案 |
| `[:POWERED_BY]` 关系 | 完全未创建 | 高 | 新增设计: 电源树生成方案 |
| Knowledge Router Tier 2/3 | 仅接口占位 | 中 | 修改 PRD：明确标注"接口预留"，补充集成契约 |
| Datasheet 处理器 | 未开始 | 中 | 修改 PRD：标记为 Phase 2，明确 OCR 方案选型 |
| AMR 电容耐压降额 | 数据源缺失 | 中 | 修改 PRD：标注依赖"料号库建设"前置条件 |
| 目录结构 | 完全不符 | 中 | 重构 PRD: 以实际目录为准 |

### 2.2 数据质量阻塞点

当前 Neo4j 中的数据缺陷直接阻塞了 PRD 中设计的多个核心功能：

```
Pin.Type = None (100%)
  - PinMux 检查的 POWER/GND/SIGNAL 分类失效
  - ESD 检查的 "连接器信号线" 识别失效
  - 电源域分析的引脚角色判定失效

IC PartType 未分类 (原始 Cadence 库名)
  - MCU/FPGA/PMIC 识别失败 -> 去耦规则适用性判断失效
  - 器件功能推断失败 -> 诊断 Agent 无法定位

无 [:POWERED_BY] 关系
  - 电源树诊断完全不可用
  - 共因失效定位不可用
  - Boot 失败分析不可用

电容耐压未知
  - AMR 电容降额检查跳过
```

**建议**: PRD 必须新增"数据质量提升"作为 Phase 0（前置阶段），不解决数据问题则后续功能无法落地。

---

## 三、PRD 具体修改建议

### 3.1 重构目录结构描述

**当前 PRD（Solution.md Section 2）**:
```
project-root/
  agent/          # LangGraph 状态机
  graph_tools/    # 图谱查询工具
  knowledge/      # 知识库与检索
  rules/          # 审查规则引擎
  web_ui/         # Streamlit 前端
  data/           # 测试数据
  tests/          # 单元测试
```

**实际代码结构**:
```
schematic_agent/
  hardware_ai_expert/          # 主开发目录
    agent_system/               # Agent + Review + Graph Tools + AMR
      agent_core.py
      graph_tools.py
      knowledge_router.py
      amr_engine.py
      init_neo4j_schema.py
      review_engine/            # 三层架构实现
        engine.py
        whitelist.py
        config/default_rules.yaml
        templates/
          base.py, decap.py, pullup.py, esd.py, amr.py, pinmux.py
      schemas/                  # Pydantic 模型（PRD 未提及）
        graph.py, agent.py, review.py, knowledge.py
    etl_pipeline/               # Cadence 网表解析
      chip_parser.py
      prt_parser.py
      net_parser.py
      run_real_etl.py
      load_to_neo4j.py
      load_topology.py
    web_ui/                     # 空目录（仅 __init__.py）
    data/
    requirements.txt
    .env
  netlist_parser/               # 早期版本（代码重复，未维护）
    PRD/                        # 设计文档存放
    *.py                        # 旧版解析器
```

**修改建议**:
1. 以 `hardware_ai_expert/` 为基准重写目录结构描述
2. 删除 `netlist_parser/` 的重复代码描述，标注为"历史版本，已归档"
3. 新增 `schemas/` 目录说明（实际为核心模块，PRD 完全未提及）
4. 标注 `web_ui/` 当前为空目录

### 3.2 Agent Core 章节重写

**当前 PRD 问题**:
- Agent_Core_Design.md 详细描述了 LangGraph 的 StateGraph、BaseAgentState、ReviewState/DiagnosisState
- 实际代码 agent_core.py 是简化状态机，无 LangGraph 依赖

**修改建议**:
```markdown
## Agent Core

### 当前实现 (V1.0)
采用简化自定义状态机，状态流转：
  entry -> classifier -> reasoning -> tool -> specific -> report -> end

- 任务分流基于关键词匹配（硬编码）
- 防死循环：tool_call_count + visited_nodes 计数器
- 已集成 ReviewRuleEngine（审查）和 KnowledgeRouter（查询）
- 诊断任务流状态机有定义，但电源时序分析逻辑缺失

### 演进路线
- V2.0 (Phase 3): 接入 LLM ReAct 循环，替换硬编码分流
- V3.0 (Phase 3+): 迁移至 LangGraph，支持条件边和并行工具调用
```

### 3.3 Graph Tools 章节修订

**当前 PRD 问题**:
- Graph_Tools_Design.md 描述了 `find_connected_peripherals(radius=2)` 等高级工具
- 实际只有 6 个基础查询工具

**修改建议**:
```markdown
## Graph Tools

### 已实现工具 (V1.0)
| 工具 | 功能 | 状态 |
|------|------|------|
| get_component_nets | RefDes -> 网络列表 | 可用 |
| get_net_components | Net -> 器件列表 | 可用 |
| get_power_domain | 电压等级聚合 | 可用 |
| get_i2c_devices | I2C 总线扫描 | 可用 |
| get_signal_path | 基础信号路径追踪 | 无 shortestPath 算法 |
| get_graph_summary | 图谱统计 | 可用 |

### 已知限制
- 使用高权限 Neo4j 账号（PRD 要求只读，待配置）
- 返回结果上限 50 条（MAX_RESULTS），超限返回摘要

### 待实现 (Phase 2+)
- find_connected_peripherals(radius=2) -- 周边器件查询
- get_power_tree() -- 电源树遍历（依赖 [:POWERED_BY] 关系）
```

### 3.4 数据模型章节修订

**当前 PRD 问题**:
- Schemas_Design.md 定义 PinNode 有 `Type: Literal["POWER", "SIGNAL", "GND"]`
- 实际 Neo4j 中 Pin 节点仅有 `Number` 和 `Id`

**修改建议**:
```markdown
## 数据模型

### 节点模型

#### ComponentNode
- RefDes (PK), Model, Value, PartType, MPN, Package
- PartType 为原始 Cadence 库名，非标准化分类

#### PinNode
- Id (PK), Number
- Name, Type, Net 属性当前缺失（ETL 未注入）
- 引脚功能通过关系推断: (Component)-[:HAS_PIN]->(Pin)-[:CONNECTS_TO]->(Net)

#### NetNode
- Name (PK), VoltageLevel
- VoltageLevel 已部分标注

### 数据质量修复方案 (新增章节)

#### Pin.Type 注入
- 解析 pstchip.dat 的 PINUSE 字段（chip_parser.py 已有解析逻辑）
- 映射规则: PINUSE=POWER -> Pin.Type="POWER"
- 预计覆盖率: >95%

#### IC PartType 分类
- 构建器件类型词典: MPN/Model 关键词 -> 类型 (MCU/FPGA/PMIC/...)
- 示例: "MT60B2G8HB" -> "MEMORY_DRAM"
- 策略: 规则词典为主 + LLM 辅助覆盖边缘 case

#### 电源树 [:POWERED_BY] 关系
- 从 LDO/Buck 器件的 OUTPUT 引脚正向推导
- 匹配 Net.VoltageLevel 与器件 Value 中的电压值
- 建立: (SourceComponent)-[:POWERED_BY]->(Net)-[:POWERED_BY]->(TargetComponent)
```

### 3.5 Review Engine 章节微调

**当前状态**: 实际代码与 PRD 设计基本一致，三层架构已落地

**修改建议**:
1. 补充已实现的 5 个模板清单：decap, pullup, esd, amr, pinmux
2. 标注 Layer 3（知识层）为"预留扩展点，未实现"
3. 补充白名单机制说明（已实现内存 + Neo4j 持久化）
4. 补充 AMR 电容降额检查为"已跳过，待料号库"

### 3.6 技术栈章节更新

**当前 PRD 问题**:
- 标注 `langgraph >= 0.1` 为核心依赖
- 实际代码未使用 LangGraph

**修改建议**:
```markdown
## 技术栈

### 核心依赖
- neo4j >= 5.26.0
- pydantic >= 2.10
- python-dotenv
- pyyaml

### 可选依赖（按功能按需安装）
- langchain / langgraph -- Phase 3 Agent 智能化时引入
- chromadb -- Tier 1 知识库（当前已运行但无数据）
- streamlit -- Phase 4 Web UI
- openai -- 如使用 OpenAI API（当前使用 Ollama）

### 本地 LLM
- Ollama + gemma4:26b (当前)
- 后续可切换至 vLLM 提升并发
```

### 3.7 MVP 范围重新定义

**当前 PRD 问题**:
- MVP 包含审查 + 诊断 + 查询 + Web UI，范围过宽
- 实际代码只有审查 + 查询可用

**修改建议**:
```markdown
## MVP 范围 (V1.0)

### In Scope
1. ETL 数据注入 -- Cadence 网表 -> Neo4j（已完成）
2. 审查规则引擎 -- 5 模板 + 13 规则（已完成）
3. 基础 Agent 交互 -- CLI 调用，支持 review/query（已完成）
4. 白名单管理 -- 内存 + Neo4j 持久化（已完成）

### Out of Scope (后续 Phase)
1. 故障诊断 -- 需要电源树 + LLM ReAct（Phase 3）
2. Web UI -- Streamlit 前端（Phase 4）
3. Datasheet 自动提取 -- OCR + 向量化（Phase 2）
4. Tier 2/3 知识检索 -- PLM/Octopart 集成（Phase 2+）
5. 高级图谱工具 -- 周边器件查询、电源树遍历（Phase 2）

### 数据质量前提
MVP 可用需先完成：
- [ ] Pin.Type 注入（P0）
- [ ] IC PartType 分类（P1）
- [ ] 电源树关系建立（P1）
```

### 3.8 安全章节补充

**当前 PRD 问题**:
- 提到 Neo4j 只读账号，但 graph_tools.py 实际使用高权限账号
- .env.swp 泄露风险未提及

**修改建议**:
```markdown
## 安全设计

### 已落实
- 审查引擎只读查询（Cypher 无写操作）
- 白名单写入使用独立约束检查
- 数据红线：项目信息不出公网

### 待落实
- [ ] graph_tools 切换至只读 Neo4j 账号
- [ ] 清理 .env.swp 等 Vim 交换文件
- [ ] 确认 .gitignore 包含 .env, *.swp
- [ ] Tier 3 脱敏逻辑完整验证（MPN 提取 + 上下文剥离）
```

---

## 四、新增章节建议

### 4.1 数据质量检查流水线 (新增)

建议在 PRD 中新增独立章节，设计 quality_checker.py 的职责：

```markdown
## 数据质量检查流水线

### 检查项
1. 必填字段检查 -- Component.Value 缺失率、Pin.Type 覆盖率
2. 类型一致性 -- PartType 是否落在标准词典中
3. 关系完整性 -- 孤儿节点（无 HAS_PIN 的 Component、无 CONNECTS_TO 的 Pin）
4. 电源域一致性 -- Net.VoltageLevel 与连接器件的额定电压是否匹配

### 输出
- 数据质量报告（JSON/Markdown）
- 不满足阈值时阻断下游审查任务
```

### 4.2 代码-PRD 双向追溯机制 (新增)

建议在 PRD 每个章节头部添加状态标签：

```markdown
## [模块名]

> 状态: 已实现 / 部分实现 / 未实现 / 设计变更
> 对应代码: agent_system/xxx.py
> 最后验证: 2026-04-30
```

### 4.3 已知问题与规避方案 (新增)

```markdown
## 已知问题登记

| 问题 | 影响 | 规避方案 | 修复计划 |
|------|------|----------|----------|
| Pin.Type 缺失 | PinMux/ESD 检查降级 | 通过 Component.PartType 推断 | Phase 0 |
| PartType 无标准 | IC 识别失败 | 建立器件类型词典 | Phase 0 |
| 无电源树关系 | 诊断功能不可用 | 暂不启用诊断任务 | Phase 2 |
| graph_tools 非只读 | 安全风险 | ETL 用高权限，Agent 用只读 | Phase 1 |
```

---

## 五、实施优先级建议

### Phase 0: 数据质量提升 (1-2 周，前置条件)
1. ETL 补充 Pin.Type 注入（chip_parser PINUSE -> Neo4j）
2. 创建 IC PartType 分类词典
3. Neo4j 创建 [:POWERED_BY] 关系
4. 实现 quality_checker.py

### Phase 1: 安全与稳定性 (1 周)
1. 配置 Neo4j 只读账号
2. graph_tools 切换只读连接
3. 清理敏感文件（.env.swp）

### Phase 2: 知识库建设 (2 周)
1. Datasheet PDF -> 文本解析
2. 文本切片 + ChromaDB 向量化
3. Tier 2/3 接口实现

### Phase 3: Agent 智能化 (2-3 周)
1. 接入 LLM ReAct 循环
2. 电源时序分析逻辑
3. 信号链路故障定位
4. （可选）迁移至 LangGraph

### Phase 4: Web UI + 闭环 (2 周)
1. Streamlit 基础界面
2. 推理链路可视化
3. 白名单 HITL 交互

---

## 六、文档组织建议

当前 PRD 文档分散在 netlist_parser/PRD/ 下，建议重构为：

```
PRD/
  README.md                   # PRD 总览 + 状态看板
  01_Architecture.md           # 系统架构（与实际代码对齐）
  02_ETL_Design.md             # ETL + 数据质量（新增数据质量章节）
  03_Data_Model.md             # 数据模型 + Schema
  04_Agent_Core.md             # Agent 核心（标注简化状态机）
  05_Review_Engine.md          # 审查规则引擎
  06_Graph_Tools.md            # 图谱工具（与实际 6 个工具对齐）
  07_Knowledge_System.md       # 知识库 + 检索路由
  08_Web_UI.md                 # Web UI（标记为待开发）
  09_Security.md               # 安全设计（补充待落实项）
  10_Roadmap.md                # 实施路线图（5 Phase + 数据前置）
  CHANGELOG.md                 # PRD 版本变更记录
```

**状态看板格式**（建议放在 README.md）：

```markdown
## 项目状态看板

| 模块 | PRD 状态 | 代码状态 | 数据就绪 | 整体可用 |
|------|----------|----------|----------|----------|
| ETL | 完成 | 完成 | Pin.Type 缺失 | 80% |
| Review Engine | 完成 | 完成 | 完成 | 95% |
| Agent Core | 设计变更 | 简化版 | 完成 | 70% |
| Graph Tools | 设计变更 | 6个工具 | 完成 | 75% |
| Knowledge | 完成 | Tier1 only | 无数据 | 30% |
| Web UI | 完成 | 未开始 | -- | 0% |
| AMR Engine | 完成 | 电阻可用 | 电容缺数据源 | 60% |
```

---

## 七、总结

本次 PRD 修改的核心原则是：**让文档成为代码的真实映射，而非理想蓝图**。

### 必须修改（阻塞开发）
1. 目录结构 -> 以 hardware_ai_expert/ 为准
2. Agent Core -> 标注为简化状态机，LangGraph 列为演进目标
3. Graph Tools -> 删除未实现工具，补充实际 API
4. 数据模型 -> 标注 Pin.Type/Name/Net 缺失现状
5. MVP 范围 -> 剥离未实现的诊断/Web UI

### 强烈建议新增
1. 数据质量检查流水线设计
2. 数据质量修复方案（Pin.Type、PartType、电源树）
3. 章节状态标签（已实现/待实现/设计变更）
4. 已知问题登记与规避方案
5. PRD 版本变更记录（CHANGELOG）

### 可选优化
1. 技术栈依赖标注"必需"vs"可选"
2. 补充性能基准（当前 500ms 目标无实测数据）
3. 补充测试策略（当前 PRD 无测试章节）

---

> 本文档基于对以下内容的全面调研生成：
> - PRD 文档: netlist_parser/PRD/*.md (6份)
> - 核心代码: hardware_ai_expert/agent_system/ (14+ 文件)
> - ETL 代码: hardware_ai_expert/etl_pipeline/ (5+ 文件)
> - Neo4j 数据: 12,688 Components, 8,159 Nets, 49,570 Pins 实地查询
> - 端到端验证: 审查引擎 5 模板 13 规则全量运行
