# 统一硬件 AI 专家系统（审查与诊断）产品需求文档 (PRD) - V4.0

> 版本: V4.0 | 日期: 2026-04-30 | 状态: 代码对齐版
> 说明: 本版本基于 V3.0 全面修订，以实际代码实现为基准，修正了架构、目录结构、模块状态等系统性偏差。

---

## 1. 产品愿景与定位

打造一个基于 EDA 异构数据图谱与 GraphRAG 技术驱动的 Agentic 硬件辅助系统。通过构建物理单板的"数字孪生"底座并外挂"原厂专家知识库"，实现硬件全生命周期的三大核心闭环：

* **左移防御（原理图审查）：** 在设计阶段，结合 Design Guide 规范自动化巡检全板拓扑，拦截器件选型与电气连接设计违规。
* **右移排障（硬件故障诊断）：** 在调试/售后阶段，接入测试日志，通过上下文感知多维图搜索，定位物理硬件的根因故障。
* **终身学习（自主知识获取）：** 具备分级路由安全检索机制与专家反馈闭环，自动解决冷门器件冷启动问题，持续丰富本地硬件知识库。

---

## 2. 项目状态看板

| 模块 | PRD V3.0 状态 | 代码实际状态 | 数据就绪度 | 整体可用 |
|------|---------------|--------------|------------|----------|
| ETL 数据底座 | 完成 | 完成 | 部分缺失 (Pin.Type) | 75% |
| 审查规则引擎 | 完成 | 完成 (5模板/13规则) | 部分缺失 | 90% |
| Agent Core | 完成 | 简化版 (非LangGraph) | 完成 | 65% |
| Graph Tools | 完成 | 6个基础工具 | 完成 | 70% |
| AMR 降额引擎 | 完成 | 电阻可用/电容跳过 | 部分缺失 | 60% |
| 知识路由 (Tier 1-3) | 完成 | Tier 1 可用/2-3占位 | 无数据 | 30% |
| Web UI (Streamlit) | 完成 | 未开始 (空目录) | — | 0% |
| Datasheet 处理 | 完成 | 未开始 | — | 0% |

> **关键结论**: 审查功能（左移防御）核心链路已打通，诊断功能（右移排障）因数据质量问题尚不可用，Web UI 完全未开始。

---

## 3. 系统整体架构

### 3.1 技术架构

```
用户输入 (CLI / 未来: Streamlit)
         |
    +----v----+
    |  Agent   |  简化状态机 (entry->classifier->reasoning->tool->specific->report->end)
    |  Core    |  任务分流: review / diagnosis / spec_query
    +----+----+
         |
    +----v-------------+  +----------------+  +------------------+
    |  Review Engine    |  |  Graph Tools   |  | Knowledge Router |
    |  (5 templates)    |  |  (6 cypher)    |  |  (Tier 1-3)      |
    +----+----+----+    |  +--------+-------+  +--------+---------+
         |    |    |    |           |                   |
         |    |    |    |           +----------+--------+---+
         |    |    |    |                      |            |
    +----v----+    |    |               +------v------+  +--v---------+
    | AMR      |    |    |               |   Neo4j     |  | ChromaDB   |
    | Engine   |    |    |               |  Graph DB   |  | Vector DB  |
    +----------+    |    |               +------+------+  +------------+
                    |    |                      |
    +---------------v----v----------------------v+
    |           ETL Pipeline                     |
    |  pstxnet + pstchip + pstxprt -> Neo4j      |
    +--------------------------------------------+
```

### 3.2 目录结构（与实际代码对齐）

```text
hardware_ai_expert/               # 主开发目录
|-- data/
|   |-- netlist_Beet7/             # 原始 EDA 网表 (pstxnet.dat, pstchip.dat, pstxprt.dat)
|   |-- output/                    # ETL 产物 (graph_components.json, topology_triplets.json)
|   |-- chroma_db/                 # ChromaDB 持久化目录
|-- etl_pipeline/                  # 数据解析与注入层
|   |-- chip_parser.py             # pstchip.dat 解析器 [已完成]
|   |-- prt_parser.py              # pstxprt.dat 解析器 [已完成]
|   |-- net_parser.py              # pstxnet.dat 解析器 [已完成]
|   |-- run_real_etl.py            # 真实网表 ETL 主流程 [已完成]
|   |-- main_etl.py                # 通用 ETL 框架 [已完成]
|   |-- load_to_neo4j.py           # 节点注入 (已集成到 run_real_etl) [已归档]
|   |-- load_topology.py           # 拓扑注入 (已集成到 run_real_etl) [已归档]
|   |-- quality_checker.py         # 数据质量检查模块 [待开发]
|-- agent_system/                  # 核心 Agent 逻辑层
|   |-- agent_core.py              # 状态机核心 [已完成-简化版]
|   |-- graph_tools.py             # Neo4j Cypher 查询工具箱 [已完成-6工具]
|   |-- knowledge_router.py        # Tier 1-3 检索路由 [部分完成]
|   |-- amr_engine.py              # AMR 降额引擎 [部分完成]
|   |-- init_neo4j_schema.py       # Neo4j 约束/索引初始化 [已完成]
|   |-- review_engine/             # 审查规则引擎 (三层架构)
|   |   |-- engine.py              # ReviewRuleEngine 总控 [已完成]
|   |   |-- whitelist.py           # 白名单管理 [已完成]
|   |   |-- config/
|   |   |   |-- default_rules.yaml # 13 条规则配置 [已完成]
|   |   |-- templates/
|   |   |   |-- base.py            # RuleTemplate + Registry [已完成]
|   |   |   |-- decap.py           # 去耦电容检查 [已完成]
|   |   |   |-- pullup.py          # 上拉电阻检查 [已完成]
|   |   |   |-- esd.py             # ESD/TVS 检查 [已完成]
|   |   |   |-- amr.py             # AMR 降额检查 [已完成]
|   |   |   |-- pinmux.py          # 引脚 MUX 检查 [已完成]
|   |-- schemas/                   # Pydantic 数据模型 [已完成]
|   |   |-- graph.py               # ComponentNode, PinNode, NetNode
|   |   |-- agent.py               # AgentMessage, ExecutionStep, AgentState
|   |   |-- review.py              # Violation, RuleConfig, WhitelistEntry
|   |   |-- knowledge.py           # KnowledgeQuery, SearchResult
|-- web_ui/
|   |-- __init__.py                # 空目录，待开发
|-- requirements.txt               # 依赖清单
|-- .env                           # 环境变量 (Neo4j, LLM)

netlist_parser/                    # 早期版本目录 [已归档，不再维护]
|-- PRD/                           # V3.0 设计文档存档
```

### 3.3 核心依赖栈

**必需依赖**:
- `neo4j >= 5.26.0` — 图数据库驱动
- `pydantic >= 2.10` — 数据模型校验
- `pyyaml` — 规则配置解析
- `python-dotenv` — 环境变量管理

**功能依赖**（按需安装）:
- `chromadb` — Tier 1 本地向量库（当前服务已运行，无数据）
- `streamlit` — Web UI（Phase 4）
- `langchain / langgraph` — Agent 高级编排（Phase 3 演进时引入）
- `openai` — 如使用 OpenAI 兼容 API

**本地 LLM**:
- 当前: Ollama + gemma4:26b
- 后续: 可切换至 vLLM 提升并发

---

## 4. 数据底座层 (ETL)

> 状态: 已完成 | 对应代码: `etl_pipeline/` | 最后验证: 2026-04-30

### 4.1 已完成功能

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| pstchip 解析 | `chip_parser.py` | 完成 | 器件库属性、引脚定义解析 |
| pstxprt 解析 | `prt_parser.py` | 完成 | RefDes -> 库模型名映射 |
| pstxnet 解析 | `net_parser.py` | 完成 | 拓扑三元组提取 |
| 数据融合 | `run_real_etl.py` | 完成 | 三表融合 + Neo4j 批量注入 |
| Schema 初始化 | `init_neo4j_schema.py` | 完成 | 约束与索引创建 |

### 4.2 数据质量现状与修复方案

#### 4.2.1 已知数据缺陷

| 缺陷 | 影响 | 严重程度 |
|------|------|----------|
| **Pin.Type = None (100%)** | PinMux/ESD/电源域分析失效 | P0 |
| **Pin.Name 缺失** | 引脚功能按名称匹配失效 | P1 |
| **IC PartType 未分类** | MCU/FPGA/PMIC 识别失败 | P1 |
| **无 `[:POWERED_BY]` 关系** | 电源树诊断、共因失效定位不可用 | P1 |
| **电容耐压未知** | AMR 电容降额检查跳过 | P2 |
| **PartType 种类繁多且不统一** | 规则适用性判断复杂 | P2 |

#### 4.2.2 根因分析

```
Pin.Type 缺失
  └── ETL 未解析 pstchip.dat 的 PINUSE 字段
      └── chip_parser.py 已有 PINUSE 解析逻辑，但 run_real_etl.py 未写入 Neo4j

IC PartType 未分类
  └── 网表中的 PartType 是原始 Cadence 库名（如 "MT60B2G8HB"）
      └── 需要 MPN/Model 匹配器件类型词典进行标准化分类

无 [:POWERED_BY] 关系
  └── ETL 未实现电源树推导逻辑
      └── 需要从 LDO/Buck 器件的 OUTPUT 引脚正向推导电源网络

电容耐压未知
  └── AMRDataSource.get_capacitor_voltage_rating() 返回 None
      └── 需要接入料号库或 Datasheet 提取
```

#### 4.2.3 修复方案

**Pin.Type 注入**:
```python
# 从 pstchip.dat 的 PINUSE 字段解析
PINUSE_MAPPING = {
    "POWER": "POWER",
    "GROUND": "GND",
    "NC": "NC",
    "INPUT": "SIGNAL",
    "OUTPUT": "SIGNAL",
    "BIDIR": "SIGNAL",
    "UNSPEC": "SIGNAL",
}
# 在 run_real_etl.py 的 batch_insert_topology 中增加 SET p.Type = pinuse 逻辑
```

**IC PartType 分类**:
```python
# 器件类型词典 (示例)
PART_TYPE_DICTIONARY = {
    r"MCU|STM32|MSP430|NRF5": "MCU",
    r"FPGA|CPLD|LATTICE|XILINX": "FPGA",
    r"PMIC|LDO|BUCK|TPS\d+|RT\d+": "PMIC",
    r"DDR|LPDDR|MT60B": "MEMORY_DRAM",
    r"FLASH|EEPROM|W25Q": "MEMORY_FLASH",
}
# 策略: 规则词典为主 (确定性高) + LLM 辅助覆盖边缘 case
```

**电源树 `[:POWERED_BY]` 关系**:
```cypher
// 从已标注电压的电源芯片 OUTPUT 引脚出发
MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
WHERE c.PartType CONTAINS "LDO" OR c.PartType CONTAINS "BUCK"
  AND p.Number IN ["VOUT", "OUTPUT", "SW"]
  AND n.VoltageLevel IS NOT NULL
MERGE (c)-[:POWERED_BY {voltage: n.VoltageLevel}]->(n)
```

### 4.3 数据质量检查流水线 (待开发)

建议实现 `quality_checker.py`，在 ETL 后自动执行：

| 检查项 | 阈值 | 失败处理 |
|--------|------|----------|
| Pin.Type 覆盖率 | >95% | 告警，阻断下游诊断任务 |
| Component.Value 缺失率 | <5% | 记录异常列表 |
| 孤儿节点 (无关系) | 0 | 自动清理或告警 |
| Net.VoltageLevel 标注率 | >80% | 告警 |
| PartType 标准分类率 | >80% | 告警 |

---

## 5. 审查规则引擎 (Review Engine)

> 状态: 已完成 | 对应代码: `agent_system/review_engine/` | 最后验证: 2026-04-30

### 5.1 三层架构实现

```
Layer 1 (Template): 通用检查模板
  |- decap_check     去耦电容检查
  |- pullup_check    上拉/终端电阻检查
  |- esd_check       ESD/TVS 保护检查
  |- amr_check       AMR 降额检查 (电阻功率)
  |- pinmux_check    引脚 MUX 检查

Layer 2 (Config): YAML 规则实例化
  |- default_rules.yaml (13 条规则)

Layer 3 (Knowledge): Datasheet 自动提取 [预留扩展点，未实现]
```

### 5.2 已实现的规则清单

| 规则 ID | 模板 | 检查内容 | 严重级别 |
|---------|------|----------|----------|
| POWER_3V3_DECAP | decap_check | 3.3V 电源去耦配置 | ERROR |
| POWER_1V8_DECAP | decap_check | 1.8V 电源去耦配置 | ERROR |
| I2C_STD_PULLUP | pullup_check | I2C 总线上拉电阻 | ERROR |
| USB_DP_PULLUP | pullup_check | USB D+ 上拉电阻 | ERROR |
| ESD_CONNECTOR_SIGNAL | esd_check | 连接器信号线 ESD 保护 | WARNING |
| ESD_USB_PORT | esd_check | USB 端口 ESD/TVS | ERROR |
| ESD_ETHERNET | esd_check | 以太网端口 ESD 保护 | ERROR |
| AMR_RESISTOR_POWER | amr_check | 电阻功率降额 | ERROR |
| PINMUX_OPEN_DRAIN | pinmux_check | OpenDrain 引脚上拉 | ERROR |
| PINMUX_IC_POWER | pinmux_check | IC 电源引脚连接 | WARNING |
| PINMUX_IC_GND | pinmux_check | IC 地引脚连接 | WARNING |
| PINMUX_NC_FLOAT | pinmux_check | NC 引脚悬空 | INFO |

### 5.3 已知限制

- **Layer 3 (Knowledge)**: 未实现，当前所有规则参数硬编码在 YAML 中
- **AMR 电容降额**: 因缺少电容耐压数据源，已跳过
- **白名单交互**: 已实现内存缓存 + Neo4j 持久化，但缺少 Web UI 的 HITL 闭环

### 5.4 白名单机制

```python
# 匹配逻辑: rule_id + refdes + net_name 三元组
# 优先级: 白名单 > severity 过滤
# 持久化: ReviewWhitelist 节点写入 Neo4j
```

---

## 6. Agent 核心层

> 状态: 简化版已完成 | 对应代码: `agent_system/agent_core.py` | 最后验证: 2026-04-30

### 6.1 当前实现 (V1.0)

采用**简化自定义状态机**（不依赖 LangGraph），状态流转：

```
entry -> classifier -> reasoning -> tool -> specific -> report -> end
```

| 状态 | 职责 |
|------|------|
| entry | 初始化，加载配置 |
| classifier | 意图识别（关键词匹配：review/diagnosis/spec_query） |
| reasoning | 根据任务类型选择执行路径 |
| tool | 调用 Graph Tools 或 Knowledge Router |
| specific | 执行具体任务（ReviewRuleEngine.run_rules() 等） |
| report | 格式化输出 Markdown 报告 |
| end | 结束，释放资源 |

### 6.2 已集成功能

| 任务类型 | 实现状态 | 说明 |
|----------|----------|------|
| review (审查) | 完成 | 调用 ReviewRuleEngine，输出违规报告 |
| spec_query (查询) | 完成 | 调用 KnowledgeRouter Tier 1 |
| diagnosis (诊断) | 部分 | 状态机有定义，电源时序分析逻辑缺失 |

### 6.3 防死循环机制

```python
# 三重防护
tool_call_count  > MAX_TOOL_CALLS (默认 10)  -> 强制结束
len(visited_nodes) > max_steps               -> 强制结束
state.recursion_depth > 3                    -> 强制结束
```

### 6.4 演进路线

| 版本 | 目标 | 关键变更 |
|------|------|----------|
| V1.0 (当前) | 硬编码分流可用 | 简化状态机，关键词匹配 |
| V2.0 (Phase 3) | LLM 驱动意图理解 | 接入 ReAct 循环，替换硬编码分流 |
| V3.0 (Phase 3+) | 高级编排 | 可选迁移至 LangGraph，支持条件边和并行工具 |

> **决策记录**: 当前保持简化状态机，因为系统复杂度可控，且 LangGraph 会增加依赖。当需要并行工具调用或复杂条件流转时再引入。

---

## 7. 图谱工具层 (Graph Tools)

> 状态: 6 个基础工具已完成 | 对应代码: `agent_system/graph_tools.py` | 最后验证: 2026-04-30

### 7.1 已实现的工具

| 工具名 | 功能 | 输入 | 输出 |
|--------|------|------|------|
| `get_component_nets` | 查询器件连接的网络 | RefDes | Net 列表 |
| `get_net_components` | 查询网络上的器件 | Net Name | Component 列表 |
| `get_power_domain` | 按电压等级聚合网络 | voltage_level | Net 列表 |
| `get_i2c_devices` | 扫描 I2C 总线器件 | — | I2C 器件列表 |
| `get_signal_path` | 信号路径追踪 | start_net, end_net | 路径节点列表 |
| `get_graph_summary` | 图谱统计 | — | 节点/关系统计 |

### 7.2 上下文防爆截断

```python
MAX_RESULTS = 50  # 单一查询返回上限
# 超限时返回统计摘要，而非完整列表
```

### 7.3 已知限制与待实现

| 限制 | 说明 | 计划 |
|------|------|------|
| 高权限连接 | 当前使用 neo4j 高权限账号，PRD 要求只读 | Phase 1 配置只读账号 |
| 无周边器件查询 | `find_connected_peripherals(radius=2)` 未实现 | Phase 2 |
| 无电源树遍历 | `get_power_tree()` 依赖 `[:POWERED_BY]` | Phase 2 |
| 信号路径无 shortestPath | 当前是基础遍历，非最短路径 | Phase 2 |

---

## 8. 知识外脑与检索路由

> 状态: Tier 1 可用，Tier 2/3 占位 | 对应代码: `agent_system/knowledge_router.py` | 最后验证: 2026-04-30

### 8.1 三级降级检索设计

```
Tier 1 (本地 ChromaDB)     [已完成-框架]
  |- 语义检索已就绪
  |- 当前无数据导入
  |- 响应: 毫秒级，安全

Tier 2 (内网 PLM)           [接口预留]
  |- 有接口占位代码
  |- 无实际 PLM 集成
  |- 需要公司内网 PDM/PLM API 接入

Tier 3 (脱敏外网)           [接口预留]
  |- 有脱敏逻辑框架
  |- 无实际 Octopart/API 集成
  |- MPN 提取逻辑有，完整上下文剥离未验证
```

### 8.2 脱敏策略

```python
# Tier 3 安全规则
1. 剥离所有电路图上下文
2. 剥离公司项目信息、BOM 描述
3. 仅允许携带干净的 MPN (Manufacturer Part Number)
4. 访问目标: 官方域名或元器件库 API
5. 获取结果自动沉淀至 Tier 1 (一次查询，永久本地化)
```

---

## 9. AMR 降额引擎

> 状态: 电阻功率降额已完成，电容耐压跳过 | 对应代码: `agent_system/amr_engine.py` | 最后验证: 2026-04-30

### 9.1 已实现

| 检查类型 | 实现状态 | 说明 |
|----------|----------|------|
| 电阻功率降额 | 完成 | 封装 -> 额定功率，P = V/R，验证 P < P_rated * derating_factor |
| 电容耐压降额 | 跳过 | 缺少电容耐压数据源 |

### 9.2 电阻封装功率映射

```python
PACKAGE_POWER_RATING = {
    "R0075": 0.03125, "R01005": 0.03125,
    "R015": 0.0625, "R0201": 0.05,
    "R0402": 0.0625, "R0603": 0.1,
    "R0805": 0.125, "R1206": 0.25,
    "R1210": 0.5, "R2010": 0.75,
    "R2512": 1.0,
}
```

### 9.3 电容耐压数据源（待建设）

需要接入以下数据源之一：
- 公司料号库 (PLM/ERP)
- Datasheet 自动提取 (Phase 2)
- 外部 API (Octopart 等，需脱敏)

---

## 10. Web UI 与交互

> 状态: 未开始 | 对应目录: `web_ui/` (空) | 计划: Phase 4

### 10.1 规划功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| Streamlit 基础界面 | P0 | 文本输入、报告展示 |
| 推理链路可视化 | P1 | Thought -> Action -> Observation |
| 图谱局部可视化 | P1 | Neo4j 节点关系网络渲染 |
| HITL 白名单交互 | P1 | 【忽略并加入白名单】按钮 |
| 报告导出 (PDF/Markdown) | P2 | — |

---

## 11. 数据模型

> 状态: 已完成 | 对应代码: `agent_system/schemas/` | 最后验证: 2026-04-30

### 11.1 节点模型

#### ComponentNode
```python
class ComponentNode(BaseModel):
    refdes: str          # 位号 (PK)
    model: str | None    # 库模型名
    value: str | None    # 参数值 (容值/阻值等)
    part_type: str | None # 器件类型 (原始 Cadence 库名，未标准化)
    mpn: str | None      # 制造商料号
    package: str | None  # 封装
```

#### PinNode
```python
class PinNode(BaseModel):
    id: str              # 全局唯一 ID: "RefDes_PinNumber" (PK)
    number: str          # 引脚编号
    # name: str | None   # [当前缺失] 引脚名称
    # type: str | None   # [当前缺失] POWER/SIGNAL/GND/NC
    # net: str | None    # [当前缺失] 连接网络名
```
> **注意**: Pin.Name/Type/Net 当前在 Neo4j 中缺失，需通过关系推断：`(Component)-[:HAS_PIN]->(Pin)-[:CONNECTS_TO]->(Net)`

#### NetNode
```python
class NetNode(BaseModel):
    name: str            # 网络名 (PK)
    voltage_level: float | None  # 电压等级 (已部分标注)
```

### 11.2 关系

```cypher
(Component)-[:HAS_PIN]->(Pin)-[:CONNECTS_TO]->(Net)
# 待添加:
# (Component)-[:POWERED_BY]->(Net)
# (Net)-[:POWERED_BY]->(Component)
```

---

## 12. 非功能性需求 (NFR)

### 12.1 数据红线与隐私隔离
- Agent 引擎与 LLM 必须支持纯本地物理机部署
- 绝不允许未脱敏的 BOM 描述、网表拓扑或项目代号上传至公有云
- **当前状态**: 使用本地 Ollama，符合红线

### 12.2 极速图谱响应
- Cypher 查询响应延迟目标 < 500ms
- **当前状态**: 未做系统基准测试，截断阈值 MAX_RESULTS=50 已设置
- **待办**: 增加性能基准测试与监控

### 12.3 BOM 数据准入与拦截
- 提供标准化 CSV BOM 导入模板
- 严重缺失关键字段（Value、Type）的物料在 ETL 阶段拦截
- **当前状态**: quality_checker.py 待开发

### 12.4 上下文防爆截断
- 单一查询返回节点/关系数超过阈值（50个）时强制截断
- **当前状态**: graph_tools.py 已实现 MAX_RESULTS=50

---

## 13. 实施路线图

### Phase 0: 数据质量提升 (1-2 周) — 前置条件

> **关键原则**: 不完成 Phase 0，诊断功能和部分审查规则无法真正落地

| 任务 | 负责人 | 工作量 | 交付标准 |
|------|--------|--------|----------|
| ETL 补充 Pin.Type 注入 | — | 2 天 | Pin.Type 覆盖率 > 95% |
| 创建 IC PartType 分类词典 | — | 2 天 | 分类覆盖率 > 80% |
| Neo4j 创建 `[:POWERED_BY]` 关系 | — | 2 天 | 电源树关系建立 |
| 实现 quality_checker.py | — | 2 天 | 数据质量检查流水线 |
| 配置 Neo4j 只读账号 | — | 1 天 | graph_tools 切换只读 |

### Phase 1: 安全与稳定性 (1 周)

| 任务 | 说明 |
|------|------|
| 清理敏感文件 | 删除 .env.swp 等 Vim 交换文件 |
| 确认 .gitignore | 包含 .env, *.swp |
| graph_tools 只读切换 | Agent 运行时仅使用只读账号 |

### Phase 2: 知识库建设 (2 周)

| 任务 | 说明 |
|------|------|
| Datasheet PDF -> 文本 | PyMuPDF 解析 (优先) / Qianfan-OCR (增强) |
| 文本切片 + ChromaDB 向量化 | — |
| datasheet_linker | MPN 关联 Neo4j |
| Tier 2/3 接口实现 | PLM/Octopart 集成 |

### Phase 3: Agent 智能化 (2-3 周)

| 任务 | 说明 |
|------|------|
| 接入 LLM ReAct 循环 | 替换硬编码分流 |
| 电源时序分析 | 基于 [:POWERED_BY] 的 Boot 失败诊断 |
| 信号链路故障定位 | 上下文感知多维路由 |
| 共因失效定位 | 沿电源树逆向寻址 |
| (可选) LangGraph 迁移 | 当需要复杂条件边时引入 |

### Phase 4: Web UI + 闭环 (2 周)

| 任务 | 说明 |
|------|------|
| Streamlit 基础界面 | — |
| 推理链路可视化 | Thought -> Action -> Observation |
| 图谱局部可视化 | Neo4j 节点关系渲染 |
| HITL 白名单按钮 | 【忽略并加入白名单】-> Neo4j 回写 |

---

## 14. 安全设计

### 14.1 已落实
- 审查引擎 Cypher 查询为只读（无写操作）
- 白名单写入使用独立约束检查
- 数据红线：项目信息不出公网（本地 Ollama）

### 14.2 待落实
- [ ] graph_tools 切换至只读 Neo4j 账号
- [ ] 清理 .env.swp 等 Vim 交换文件
- [ ] 确认 .gitignore 包含 .env, *.swp
- [ ] Tier 3 脱敏逻辑完整验证（MPN 提取 + 上下文剥离）

---

## 15. 已知问题登记

| 问题 | 影响 | 规避方案 | 修复计划 |
|------|------|----------|----------|
| Pin.Type 缺失 (100%) | PinMux/ESD/电源域检查降级 | 通过 Component.PartType 推断 | Phase 0 |
| PartType 未标准化 | IC 识别失败 | 建立器件类型词典 | Phase 0 |
| 无电源树关系 | 诊断功能完全不可用 | 暂不启用诊断任务 | Phase 0 |
| graph_tools 非只读 | 安全风险 | ETL 用高权限，Agent 用只读 | Phase 1 |
| 电容耐压未知 | AMR 电容检查跳过 | 依赖料号库建设 | Phase 2 |
| Agent 硬编码分流 | 意图理解能力弱 | 当前可用，Phase 3 升级 LLM | Phase 3 |

---

## 16. 附录

### 16.1 环境配置

```bash
# 核心服务
Neo4j:     bolt://localhost:7687  (user: neo4j)
ChromaDB:  http://localhost:8000
Ollama:    http://localhost:11434  (model: gemma4:26b)

# Python 版本
Python 3.12.8
```

### 16.2 验证命令

```bash
# 1. 审查引擎全量测试
cd /data/schematic_agent/hardware_ai_expert
python3 -c "
from agent_system.review_engine import ReviewRuleEngine
from agent_system.graph_tools import _get_driver
engine = ReviewRuleEngine(_get_driver())
violations = engine.run_rules()
print(f'Total violations: {len(violations)}')
"

# 2. Agent Core 端到端测试
python3 agent_system/agent_core.py

# 3. ETL 数据质量检查 (待开发)
python3 etl_pipeline/quality_checker.py
```

### 16.3 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| V3.0 | 2026-03 | 初始完整设计，基于 LangGraph 愿景 |
| V4.0 | 2026-04-30 | 代码对齐版：修正目录结构、Agent Core、Graph Tools、数据模型；新增 Phase 0 数据质量；补充已知问题登记 |

---

> 本文档基于对以下内容的全面调研生成：
> - PRD V3.0 文档: netlist_parser/PRD/*.md (7份)
> - 核心代码: hardware_ai_expert/agent_system/ (14+ 文件)
> - ETL 代码: hardware_ai_expert/etl_pipeline/ (6+ 文件)
> - Neo4j 实地数据: 12,688 Components, 8,159 Nets, 49,570 Pins
> - 端到端验证: 审查引擎 5 模板 13 规则全量运行 (1520 violations)
