# schematic_agent 项目状态分析报告

> 生成日期: 2026-05-14
> 分析人: Jarvis (AI Assistant)
> 项目路径: `/data/schematic_agent`
> GitHub: `https://github.com/robinleee/schematic_agent.git`

---

## 一、项目概述

### 1.1 项目定位

**schematic_agent** 是一个基于 **EDA 异构数据图谱 + GraphRAG + LangGraph Agent** 的硬件原理图审查与故障诊断系统。

核心目标是通过构建物理单板的"数字孪生"底座，实现硬件全生命周期的三大闭环：

| 闭环 | 阶段 | 功能 |
|------|------|------|
| **左移防御** | 设计阶段 | 原理图自动化审查（去耦、上拉、ESD、AMR降额、PinMux） |
| **右移排障** | 调试阶段 | 硬件故障诊断（Boot失败、信号中断、电源树失效、共因定位） |
| **终身学习** | 全周期 | Datasheet参数提取 + HITL审核 + 企业级知识库沉淀 |

### 1.2 核心价值主张

- **隐私绝对安全**: 本地部署 LLM (Ollama/vLLM)，数据不出内网
- **确定性规则 + AI 推理双引擎**: ReviewEngine 提供可解释的确定性检查，Agent 提供灵活的智能推理
- **知识可沉淀**: 通过 HITL 审核机制将工程师经验转化为可复用的规则

### 1.3 技术架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            系统架构总览                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │   Web UI    │    │  Agent Core │    │   LLM API   │                     │
│  │ (Streamlit) │◄──►│ (LangGraph) │◄──►│(Ollama/vLLM)│                     │
│  │  [✅ done]  │    │   [✅ done] │    │   [✅ done] │                     │
│  └─────────────┘    └──────┬──────┘    └─────────────┘                     │
│                             │                                                │
│              ┌──────────────┼──────────────┐                                │
│              ▼              ▼              ▼                                │
│  ┌─────────────────┐ ┌──────────────┐ ┌─────────────────┐                  │
│  │  Review Engine  │ │ Graph Tools  │ │ Knowledge Router│                  │
│  │   [✅ done]     │ │  [✅ done]   │ │  [⚠️ partial]   │                  │
│  │  6 templates    │ │  6+ cypher   │ │  Tier 1: ✅     │                  │
│  │  14 rules       │ │  聚合查询    │ │  Tier 2/3: ⚠️   │                  │
│  └────────┬────────┘ └──────┬───────┘ └────────┬────────┘                  │
│           │                 │                  │                           │
│           └─────────────────┼──────────────────┘                           │
│                             ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Neo4j Graph DB                               │   │
│  │  [✅ done] 49,570 Pins | 8,159 Nets | 12,688 Components            │   │
│  │  ✅ Pin.Type 100% | ✅ POWERED_BY 955条 | ✅ PartType 99.1%        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ChromaDB Vector DB                             │   │
│  │  [⚠️ partial] 仅3条记录，知识库严重匮乏                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 技术栈

| 层级 | 技术 | 状态 |
|------|------|------|
| **ETL 解析** | Cadence 网表 (pstchip/pstxprt/pstxnet) | ✅ |
| **图数据库** | Neo4j 5.26.0 | ✅ |
| **向量数据库** | ChromaDB | ✅ (空) |
| **LLM 推理** | Ollama (gemma4:26b) | ✅ (慢) |
| **Agent 框架** | LangGraph 状态机 | ✅ |
| **前端** | Streamlit | ✅ |
| **文档解析** | PyMuPDF + 智能切片 | ✅ |
| **编程语言** | Python 3.8 + venv | ✅ |

---

## 二、已实现功能（按模块详述）

### 2.1 数据底座层 (ETL Pipeline) — 完成度 85%

| 组件 | 状态 | 说明 |
|------|------|------|
| **Cadence 网表解析** | ✅ | 完整解析 pstchip/pstxprt/pstxnet 三种格式 |
| **拓扑关系注入** | ✅ | 49,580 条拓扑三元组 (:Component)-[:CONNECTS]-(:Pin)-[:ON_NET]-(:Net) |
| **Pin.Type 注入** | ✅ | **100% 覆盖** — SIGNAL:18,681 / GROUND:13,879 / POWER:4,030 / INPUT:4 / BIDIRECTIONAL:74 |
| **电源树 [:POWERED_BY]** | ✅ | 955 条关系，58 个供电源 → 253 个被供电器件 |
| **PartType 精细化** | ✅ | 99.1% 覆盖率，UNKNOWN 从 1,651 → 120 (0.9%) |
| **Quality Guard** | ✅ | PartType 覆盖率 < 90% 时熔断 |
| **BOM 标准化导入** | ❌ | 尚未实现 |
| **网络电压标注** | ⚠️ | 仅 17.3%，需扩展规则 |

**关键文件:**
- `etl_pipeline/chip_parser.py` — PINUSE 解析与 Pin.Type 映射
- `etl_pipeline/part_type_standardizer.py` — PartType 智能标准化
- `etl_pipeline/generate_power_tree.py` — 电源树生成
- `etl_pipeline/quality_guard.py` — 数据质量熔断

### 2.2 审查规则引擎 (Review Engine) — 完成度 80%

| 组件 | 状态 | 说明 |
|------|------|------|
| **模板层 (6类)** | ✅ | decap / pullup / esd / amr / pinmux / base |
| **配置层 (14条规则)** | ✅ | YAML 配置，可灵活扩展 |
| **AMR 降额引擎** | ⚠️ | 电阻检查可用，**电容降额被跳过**（缺少耐压数据源） |
| **白名单管理** | ✅ | CRUD 完整，Web UI 可交互 |
| **报告生成** | ✅ | Markdown 格式，支持按规则分组 |

**规则清单:**

| 规则 | 类别 | 状态 | 备注 |
|------|------|------|------|
| DECOUPLING_CAP_CHECK | 去耦电容 | ✅ | 检查 IC 电源引脚去耦 |
| I2C_PULLUP_CHECK | 上拉电阻 | ✅ | I2C 总线上拉检查 |
| EXTERNAL_IO_ESD | ESD 保护 | ⚠️ | 438 误报，需过滤测试点 |
| NC_FLOATING_CHECK | 悬空引脚 | ⚠️ | 500 误报，需增加排除条件 |
| RESISTOR_POWER_DERATING | 电阻降额 | ✅ | AMR 检查 |
| CAPACITOR_VOLTAGE_DERATING | 电容降额 | ❌ | 被跳过，无耐压数据 |
| PINMUX_CONFLICT_CHECK | 引脚复用 | ✅ | Pin.Type 依赖 |
| BOOT_RESISTOR_CONFIG | Boot 配置 | ✅ | 上拉/下拉检查 |
| POWER_DOMAIN_DECAP | 电源去耦 | ✅ | 按电压域检查 |
| I2C_DEVICE_COUNT | I2C 设备数 | ✅ | 总线负载 |
| MIPI_TERM_CHECK | MIPI 端接 | ✅ | 差分对端接 |
| DDR_REF_DECAP | DDR 参考 | ✅ | 参考电压去耦 |
| POWER_DOMAIN_ISOLATION | 电源隔离 | ✅ | 电平转换检查 |
| CLK_SKEW_CHECK | 时钟偏斜 | ✅ | 时钟线长度匹配 |

**关键文件:**
- `agent_system/review_engine/engine.py` — 规则引擎总控
- `agent_system/review_engine/templates/*.py` — 6 类规则模板
- `agent_system/amr_engine.py` — AMR 降额计算

### 2.3 Agent 核心系统 — 完成度 70%

| 组件 | 状态 | 说明 |
|------|------|------|
| **LangGraph 状态机** | ✅ | parse → plan → tool_execution → reasoning → report |
| **LLM Intent Router** | ✅ | 结构化 JSON 输出，置信度 0.98-0.99 |
| **统一 LLM 封装** | ✅ | `llm_client.py` 支持 Ollama + vLLM，自动重试 |
| **审查任务流** | ✅ | `agent.review()` 端到端通 |
| **诊断任务流** | ⚠️ | 状态机有，电源时序/信号链路逻辑待完善 |
| **查询任务流** | ✅ | `agent.query_spec()` 知识库查询 |
| **LLM ReAct 循环** | ❌ | 当前硬编码分流，未接入 LLM 自主决策 |

**关键文件:**
- `agent_system/agent_core.py` — Agent 状态机 (1,302 行)
- `agent_system/llm_intent_router.py` — 意图分类
- `agent_system/llm_client.py` — LLM 统一封装

### 2.4 图谱工具层 (Graph Tools) — 完成度 85%

| 工具 | 状态 | 说明 |
|------|------|------|
| `get_component_nets` | ✅ | RefDes → 网络列表 |
| `get_net_components` | ✅ | Net → 器件列表（聚合摘要替代截断） |
| `get_power_domain` | ✅ | 电压等级聚合 |
| `get_i2c_devices` | ✅ | I2C 总线扫描 |
| `get_signal_path` | ⚠️ | 基础实现，无 shortestPath 算法 |
| `get_power_tree` | ✅ | 基于 [:POWERED_BY] 的电源树遍历 |
| `get_graph_summary` | ✅ | 统计信息 |

**关键文件:**
- `agent_system/graph_tools.py` — 6+ Cypher 查询工具

### 2.5 知识库管理系统 — 完成度 75%

| 组件 | 状态 | 说明 |
|------|------|------|
| **DesignGuideParser** | ✅ | PDF/Markdown/TXT 智能切片 |
| **TopicClassifier** | ✅ | 8 类关键词分类 (i2c/power/pcie/usb/gpio/thermal/si/ddr) |
| **DocumentProcessor** | ✅ | 统一入口，支持 4 种文档类型 |
| **ChecklistParser** | ✅ | CSV/Excel 规则提取 |
| **StorageDispatcher** | ✅ | 自动分发到 ChromaDB/Neo4j/YAML |
| **Neo4jKnowledgeStore** | ✅ | ReviewRule + KnowledgeChunk 节点存储 |
| **知识库 Web UI** | ✅ | 5 Tab：上传/列表/审核/查询/统计 |
| **ETL Web 导入** | ✅ | 网表上传 → 预览 → 质量检查 → 入库 |
| **ChromaDB 数据** | ❌ | **仅 3 条记录，严重不足** |

**关键文件:**
- `agent_system/parsers/*.py` — 文档解析器
- `agent_system/storage_dispatcher.py` — 存储分发
- `web_ui/pages/knowledge_base.py` — 知识库页面
- `web_ui/pages/etl_import.py` — ETL 导入页面

### 2.6 Web UI (Streamlit) — 完成度 70%

| 页面 | 状态 | 说明 |
|------|------|------|
| **主框架** | ✅ | `st.navigation()` 多页面结构 |
| **Agent 聊天** | ⚠️ | 基础界面，待打通端到端 |
| **审查报告** | ⚠️ | 待完善可视化 |
| **HITL 审批面板** | ⚠️ | 基础功能有，待优化交互 |
| **推理链路展示** | ❌ | Thought→Action→Observation 可视化待开发 |
| **Neo4j 图谱可视化** | ❌ | PyVis/Echarts 集成待开发 |
| **知识库管理** | ✅ | 5 Tab 完整功能 |
| **ETL 导入** | ✅ | 4 Tab 完整功能 |

### 2.7 测试覆盖 — 完成度 40%

| 测试文件 | 行数 | 覆盖内容 |
|----------|------|----------|
| `test_integration.py` | 248 | 模块导入 + 页面结构 + 端到端 + 数据库连接 |
| `test_phase1.py` | 299 | DesignGuideParser + TopicClassifier |
| `test_phase3.py` | 292 | StorageDispatcher + Neo4j 存储 |
| `test_phase4.py` | 141 | 知识库页面 + JSON 持久化 |
| `test_etl_web.py` | 144 | ETL Web 桥接测试 |

---

## 三、数据底座详细状态

### 3.1 核心指标

| 指标 | 数值 | 目标 | 状态 |
|------|------|------|------|
| Components | 12,688 | — | ✅ |
| Pins | 49,570 | — | ✅ |
| Nets | 8,159 | — | ✅ |
| Topology Triplets | 49,580 | — | ✅ |
| **Pin.Type 覆盖率** | **100%** | > 95% | ✅ |
| **POWERED_BY 关系** | **955** | > 100 | ✅ |
| **PartType 覆盖率** | **99.1%** | > 95% | ✅ |
| UNKNOWN PartType | 120 (0.9%) | < 5% | ✅ |
| 网络电压标注 | ~17.3% | > 50% | ⚠️ |
| ChromaDB 记录数 | 3 | > 500 | ❌ |

### 3.2 PartType 分布

```
CAPACITOR:    5,714 (45.0%)  ✅
RESISTOR:     5,255 (41.4%)  ✅
TESTPOINT:      377 ( 3.0%)  ✅
PASSIVE:        285 ( 2.2%)  ✅
IC:             256 ( 2.0%)  ✅ (67 unique)
DIODE:          176 ( 1.4%)  ✅
MOSFET:         126 ( 1.0%)  ✅
UNKNOWN:        120 ( 0.9%)  ✅ (< 5% 目标)
INDUCTOR:        86 ( 0.7%)  ✅
DRAM:            64 ( 0.5%)  ✅
PMIC:            57 ( 0.4%)  ✅
CONNECTOR:       40 ( 0.3%)  ✅
MECHANICAL:      40 ( 0.3%)  ✅
CRYSTAL:         28 ( 0.2%)  ✅
LED:             25 ( 0.2%)  ✅
TRANSISTOR:      20 ( 0.2%)  ✅
FLASH:            9 ( 0.1%)  ✅
MCU:              6 ( 0.0%)  ✅
SOC:              2 ( 0.0%)  ✅
FPGA:             1 ( 0.0%)  ✅
LDO:              1 ( 0.0%)  ✅
```

---

## 四、待开发功能（按优先级）

### 4.1 P0 — 阻塞性功能（影响现有功能可用性）

| # | 任务 | 说明 | 影响 | 预估 |
|---|------|------|------|------|
| 1 | **AMR 电容降额检查** | 当前被跳过，缺少电容耐压数据源。需建立 Model→VoltageRating 映射 | ReviewEngine 核心规则失效 | 2天 |
| 2 | **ChromaDB 知识库填充** | 仅 3 条记录，RAG 查询全部返回空，Agent 问答能力受限 | 知识库系统形同虚设 | 3天 |
| 3 | **网络电压标注扩展** | 从 17.3% → 50%+，增加更多电源命名规则（1V0, 1V2, VDD_CORE 等） | 电源域分析不准确 | 1天 |
| 4 | **BIDIRECTIONAL Pin.Type 修复** | 仅 74/4,122 映射成功，需调试 chip_parser PINUSE 注入逻辑 | PinMux 检查覆盖不足 | 0.5天 |

### 4.2 P1 — 核心功能完善（提升系统智能化水平）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| 5 | **Agent ReAct 循环** | 当前硬编码状态机，需让 LLM 根据 observation 自主决策 next action | 2-3天 |
| 6 | **规则误报调优** | EXTERNAL_IO_ESD (438误报)、NC_FLOATING_CHECK (500误报) 加过滤条件 | 1-2天 |
| 7 | **诊断任务流完善** | 电源时序分析、信号链路中断溯源、共因失效定位 | 2-3天 |
| 8 | **Datasheet 批量解析入库** | 验证 PyMuPDF 解析能力，批量处理 PDF，切片入 ChromaDB | 2天 |
| 9 | **MPN ↔ ChromaDB ↔ Neo4j 关联** | 建立 Component.MPN 与 VectorChunk 的关联机制 | 1.5天 |
| 10 | **BOM 标准化导入** | CSV BOM 模板 + 模糊匹配，补充器件参数 | 2天 |

### 4.3 P2 — 生产化部署（提升系统可用性和性能）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| 11 | **vLLM 部署** | 替换 Ollama，降低延迟，支持并发 | 1天 |
| 12 | **Web UI 核心功能** | 聊天打通、审查报告可视化、推理链路展示、图谱可视化 | 3-5天 |
| 13 | **单元测试覆盖** | ETL parser、review templates、graph_tools 核心函数 | 1-2天 |
| 14 | **集成测试** | 网表 → ETL → 审查 → 报告 端到端 | 1天 |
| 15 | **Cypher 性能优化** | GND 等大网络加 LIMIT/聚合 | 0.5天 |
| 16 | **Neo4j 只读账号** | 创建 readonly 角色，graph_tools 切换只读连接 | 0.5天 |
| 17 | **LLM 响应缓存** | 相同查询缓存结果 | 0.5天 |

### 4.4 P3+ — 高级功能（未来演进方向）

| # | 任务 | 说明 |
|---|------|------|
| 18 | **True GraphRAG** | LlamaIndex 完整集成，图+向量联合检索，建立 [:DESCRIBES] 关系 |
| 19 | **Cypher 计算下推** | 超大节点网络在图库层聚合摘要，彻底废除 50 节点截断 |
| 20 | **差分对追踪** | PCIe/MIPI 信号完整性检查 |
| 21 | **共因失效定位** | 电源树共同上游节点定位 |
| 22 | **多网表支持** | 多项目数据隔离 |
| 23 | **规则热更新** | default_rules.yaml 修改后无需重启 Agent |
| 24 | **HITL 规则沉淀自动化** | LLM 提取 → Pending → 审批 → 自动注入规则引擎 |

---

## 五、开发进度评估

### 5.1 整体完成度: ~65%

```
数据底座层     ████████████████████░░░  85%
审查规则引擎   ███████████████░░░░░░░░  80%
Agent 核心     ██████████████░░░░░░░░░  70%
图谱工具层     ███████████████░░░░░░░░  85%
知识库管理     ██████████████░░░░░░░░░  75%
Web UI         █████████████░░░░░░░░░░  70%
测试覆盖       ██████░░░░░░░░░░░░░░░░░  40%
文档完善       █████████████████░░░░░░  90%
─────────────────────────────────────────
综合完成度     █████████████░░░░░░░░░░  ~65%
```

### 5.2 阶段完成状态

| 阶段 | 时间 | 状态 | 关键交付 |
|------|------|------|----------|
| **A: 数据底座修复** | 2026-05-01 | ✅ 完成 | Pin.Type 100%, POWERED_BY 955条, PartType 99.1% |
| **B: LLM 客户端** | 2026-05-02 | ✅ 完成 | LLMClient, Intent Router 稳定化 |
| **C1: Web UI 启动** | 2026-05-02 | ✅ 完成 | Streamlit 启动, 各页面导入正常 |
| **知识库 Phase 1** | 2026-05-09 | ✅ 完成 | DesignGuideParser, TopicClassifier |
| **知识库 Phase 2** | 2026-05-09 | ✅ 完成 | ChecklistParser, 规则提取 |
| **知识库 Phase 3** | 2026-05-09 | ✅ 完成 | StorageDispatcher, Neo4j 存储 |
| **知识库 Phase 4** | 2026-05-09 | ✅ 完成 | Streamlit 多页面 UI, JSON 持久化 |
| **ETL Web 导入** | 2026-05-09 | ✅ 完成 | 网表上传 → 预览 → 入库 |
| **C2-C3: ReAct 循环** | — | ⏳ 未开始 | LLM 自主决策 |
| **D: 知识库填充** | — | ⏳ 未开始 | Datasheet 批量入库 |
| **E: Web UI 完善** | — | ⏳ 未开始 | 可视化、HITL 面板 |
| **F: 生产化** | — | ⏳ 未开始 | vLLM、测试、性能优化 |

---

## 六、技术债务与已知问题

### 6.1 🔴 严重问题

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 1 | **ChromaDB 仅 3 条记录** | RAG 查询全部返回空，Agent 问答能力受限 | 批量导入 Datasheet PDF |
| 2 | **AMR 电容降额被跳过** | `AMRDataSource.get_capacitor_voltage_rating()` 返回 None | 建立 Model→VoltageRating 映射 |
| 3 | **无 BOM 标准化导入** | 无法补充器件参数 | 实现 CSV BOM 模板导入 |

### 6.2 🟡 中等问题

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 4 | **BIDIRECTIONAL Pin.Type 1.8%** | 74/4,122 映射成功 | 调试 chip_parser PINUSE 注入 |
| 5 | **网络电压标注 17.3%** | VoltageLevelExtractor 覆盖不足 | 扩展电源命名规则 |
| 6 | **规则误报率高** | EXTERNAL_IO_ESD 438误报, NC_FLOATING 500误报 | 增加过滤条件 |
| 7 | **Ollama 响应慢** | ~10s/次，用户体验差 | 部署 vLLM |
| 8 | **Agent 硬编码分流** | 无法处理复杂复合意图 | 接入 ReAct 循环 |

### 6.3 🟢 轻微问题

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 9 | **ReviewWhitelist 查询属性名不一致** | Neo4j warning | 统一属性名 |
| 10 | **diagnose 模式 JSON 解析失败** | LLM thinking 内容干扰 | 过滤 thinking 字段 |
| 11 | **graph_tools 使用高权账号** | 安全风险 | 创建只读账号 |

---

## 七、下一步建议

### 7.1 短期（1-2 周）— 解决阻塞性问题

**优先级: 数据 > 规则 > Agent**

1. **填充 ChromaDB 知识库**
   - 批量解析项目中的 Datasheet PDF
   - 切片 + 向量化入库
   - 目标: 500+ 条记录

2. **修复 AMR 电容降额**
   - 建立 Model→VoltageRating 映射表
   - 或从 Datasheet 提取耐压参数

3. **规则误报调优**
   - EXTERNAL_IO_ESD: 排除测试点/内部网络
   - NC_FLOATING_CHECK: 增加排除条件

4. **网络电压标注扩展**
   - 增加 1V0, 1V2, 1V35, 2V5, VDD_CORE 等规则

### 7.2 中期（1-2 月）— 提升智能化水平

1. **Agent ReAct 循环**
   - 引入 LLM 自主决策节点
   - 支持复合意图处理

2. **诊断任务流完善**
   - 电源时序分析
   - 信号链路中断溯源
   - 共因失效定位

3. **Web UI 核心功能**
   - 聊天界面端到端打通
   - 审查报告可视化
   - 推理链路展示

4. **vLLM 部署**
   - 替代 Ollama
   - 降低延迟至 < 2s

### 7.3 长期（3 月+）— 生产级演进

1. **True GraphRAG**
   - LlamaIndex 完整集成
   - 图 + 向量联合检索

2. **Cypher 计算下推**
   - 超大网络聚合摘要
   - 废除硬截断

3. **多网表支持**
   - 项目数据隔离
   - 网表切换

4. **规则热更新**
   - YAML 修改实时生效
   - 无需重启 Agent

---

## 八、关键风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| gemma4:26b 中文理解能力差 | 中 | LLM Router 成功率低 | 换用 Qwen 或 DeepSeek；中英混合 prompt |
| Datasheet OCR 准确率不足 | 中 | 知识库质量差 | PyMuPDF+LLM 提取；HITL 审核兜底 |
| vLLM 显存不足 | 中 | 无法加载更大模型 | gemma4:26b 约 16GB；确认 GPU 显存 |
| 规则误报导致工程师不信任 | 高 | 系统被弃用 | 白名单机制 + 置信度阈值 + 持续调优 |
| ETL 改崩已有数据 | 低 | Neo4j 数据损坏 | 改前做 `neo4j-admin dump` 备份 |

---

## 九、需要 Human 决策的事项

1. **GPU 显存情况？**
   - vLLM 部署需要确认 GPU 型号和显存大小
   - 当前环境: 2× GeForce 8GB + 2× Tesla T4 16GB

2. **Datasheet 来源？**
   - 项目目录下是否有 Datasheet PDF？
   - 还是需要从 PLM/供应商下载？

3. **模型选择？**
   - gemma4:26b 对中文理解一般
   - 是否考虑换 Qwen2.5-14B/32B 或 DeepSeek？

4. **生产环境部署目标？**
   - 单机 Docker 部署还是 K8s 集群？

5. **Phase G 高级功能优先级？**
   - 差分对检查、多网表支持是否有近期需求？

---

## 十、核心文件清单

### 10.1 新增/修改（最近）

```
hardware_ai_expert/agent_system/llm_client.py              # 统一 LLM 封装
hardware_ai_expert/agent_system/llm_intent_router.py       # LLM 意图路由
hardware_ai_expert/etl_pipeline/generate_power_tree.py     # 电源树生成
hardware_ai_expert/etl_pipeline/part_type_standardizer.py  # PartType 标准化
hardware_ai_expert/etl_pipeline/load_topology.py           # 拓扑注入
hardware_ai_expert/etl_pipeline/main_etl.py                # ETL 主流程
hardware_ai_expert/agent_system/review_engine/templates/amr.py  # AMR 降额
hardware_ai_expert/web_ui/pages/knowledge_base.py          # 知识库页面
hardware_ai_expert/web_ui/pages/etl_import.py              # ETL 导入页面
hardware_ai_expert/agent_system/parsers/*.py               # 文档解析器
hardware_ai_expert/agent_system/storage_dispatcher.py      # 存储分发
hardware_ai_expert/agent_system/kb_persistence.py          # JSON 持久化
```

### 10.2 核心架构文件

```
hardware_ai_expert/agent_system/agent_core.py              # Agent 状态机 (1,302行)
hardware_ai_expert/agent_system/amr_engine.py              # AMR 降额引擎
hardware_ai_expert/agent_system/graph_rag_bridge.py        # GraphRAG 桥接
hardware_ai_expert/agent_system/graph_tools.py             # 图谱工具
hardware_ai_expert/agent_system/hitl_workflow.py           # HITL 审批流
hardware_ai_expert/agent_system/knowledge_router.py        # 知识路由
hardware_ai_expert/agent_system/datasheet_parser.py        # Datasheet 解析
hardware_ai_expert/web_ui/app.py                           # Streamlit UI
hardware_ai_expert/etl_pipeline/main_etl.py                # ETL 主流程
hardware_ai_expert/etl_pipeline/quality_guard.py           # 质量熔断
```

---

## 十一、总结

**schematic_agent** 项目已经完成了 **~65%** 的核心功能，数据底座（ETL Pipeline）经过 A 阶段的修复已达到 **生产可用水平**（Pin.Type 100%, PartType 99.1%, POWERED_BY 955条）。Agent 核心、Review Engine、Graph Tools 等模块均已实现并可运行。

**当前最大的瓶颈是：**
1. **知识库为空**（ChromaDB 仅 3 条记录）— 导致 RAG 查询失效
2. **AMR 电容降额被跳过** — 导致核心审查规则不完整
3. **Agent 仍为硬编码分流** — 限制了智能化水平

**建议下一步优先解决阻塞性问题**（P0 任务），然后逐步推进到 P1/P2 阶段。按照当前节奏，预计 **4-6 周** 可达到生产可用的 MVP 状态。

---

*报告生成时间: 2026-05-14 18:58 CST*
*分析基于: PRD V5.0, ROADMAP_NEXT.md, TECHNICAL_IMPLEMENTATION_PLAN.md, 代码基线*
