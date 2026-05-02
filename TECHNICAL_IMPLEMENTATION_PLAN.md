# schematic_agent — 技术实现方案

> 版本: V1.0 | 日期: 2026-04-29 | 状态: 基于 PRD V3.0 + Solution V2.0 编制

---

## 1. 项目概述

### 1.1 目标
基于 EDA 异构数据图谱 + GraphRAG + LangGraph Agent 的硬件原理图审查与故障诊断系统。

### 1.2 核心闭环
- **左移防御**: 原理图审查（去耦、上拉、ESD、AMR 降额、PinMux）
- **右移排障**: 故障诊断（Boot 失败、信号中断、共因失效）
- **终身学习**: 分级知识检索 + Datasheet 自动提取

### 1.3 当前完成度: ~65%

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            系统架构总览                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │   Web UI    │    │  Agent Core │    │   LLM API   │                     │
│  │ (Streamlit) │◄──►│ (LangGraph) │◄──►│ (vLLM/OLl)│                     │
│  │  [待开发]   │    │   [✅ done] │    │   [✅ done]│                     │
│  └─────────────┘    └──────┬──────┘    └─────────────┘                     │
│                             │                                                │
│              ┌──────────────┼──────────────┐                                │
│              ▼              ▼              ▼                                │
│  ┌─────────────────┐ ┌──────────────┐ ┌─────────────────┐                  │
│  │  Review Engine  │ │ Graph Tools  │ │ Knowledge Router│                  │
│  │   [✅ done]     │ │  [✅ done]   │ │  [⚠️ partial]   │                  │
│  │  5 templates    │ │  6+ cypher   │ │  Tier 1: ✅     │                  │
│  │  13 rules       │ │  truncator   │ │  Tier 2/3: ⚠️   │                  │
│  └────────┬────────┘ └──────┬───────┘ └────────┬────────┘                  │
│           │                 │                  │                           │
│           └─────────────────┼──────────────────┘                           │
│                             ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Neo4j Graph DB                               │   │
│  │  [✅ done] 49,570 Pins | 8,159 Nets | Component topology            │   │
│  │  ⚠️ Pin.Type missing | ⚠️ [:POWERED_BY] not created                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ETL Pipeline                                   │   │
│  │  [✅ done] pstxnet + pstchip + pstxprt → Neo4j batch injection     │   │
│  │  ❌ quality_checker | ❌ Pin.Type injection | ❌ BOM standardization│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Knowledge Base                                 │   │
│  │  [⚠️ partial]                                                        │   │
│  │  ChromaDB: ✅ running (empty) | Datasheet processor: ❌ not built   │   │
│  │  Design Guide: ❌ not built | datasheet_linker: ❌ not built        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块完成状态详表

### 3.1 数据底座层 (ETL)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| Cadence 网表解析 | ✅ | `chip_parser.py`, `prt_parser.py`, `net_parser.py` | 完整解析 pstchip/pstxprt/pstxnet |
| 数据融合注入 | ✅ | `main_etl.py` | Pydantic 校验 + UNWIND MERGE 批量注入 |
| **数据质量检查** | ❌ | `quality_checker.py` | **缺失**: 缺失 Value/Type 拦截、错误日志 |
| **Pin Type 注入** | ❌ | — | **缺失**: PINUSE→Pin.Type 映射未实现（当前全为 None） |
| **BOM 标准化导入** | ❌ | — | **缺失**: CSV BOM 模板 + 模糊匹配 |
| **电源树生成** | ❌ | — | **缺失**: `[:POWERED_BY]` 关系未创建 |

### 3.2 知识外脑层 (Vector DB + RAG)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| ChromaDB 服务 | ✅ | — | 运行中，端口 8000 |
| **Datasheet 解析** | ❌ | `datasheet_processor.py` | **缺失**: Qianfan-OCR / PyMuPDF 解析 |
| **Datasheet 关联** | ❌ | `datasheet_linker.py` | **缺失**: MPN→ChromaDB→Neo4j 关联 |
| **Design Guide 处理** | ❌ | `design_guide_processor.py` | **缺失**: 用户上传 + 知识提取 |
| 向量存储 | ⚠️ | — | 服务就绪，无数据导入 |

### 3.3 检索路由层 (Tiered Search)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| Tier 1 (本地 RAG) | ✅ | `knowledge_router.py` | ChromaDB 语义检索 |
| Tier 2 (内网 PLM) | ⚠️ | `knowledge_router.py` | 接口占位，无实际 PLM 集成 |
| Tier 3 (脱敏外网) | ⚠️ | `knowledge_router.py` | 接口占位，无 Octopart/API 集成 |
| 脱敏逻辑 | ⚠️ | — | MPN 提取逻辑有，完整上下文剥离未验证 |

### 3.4 Agent 核心层

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| 状态机框架 | ✅ | `agent_core.py` | 简化状态机（entry→classifier→reasoning→tool→specific→report→end） |
| 审查任务流 | ✅ | `agent_core.py` | ReviewRuleEngine 集成，349 violations/demo |
| 诊断任务流 | ⚠️ | `agent_core.py` | 状态机有，电源时序分析逻辑缺失 |
| 查询任务流 | ✅ | `agent_core.py` | KnowledgeRouter 集成 |
| **LLM ReAct 循环** | ❌ | — | **缺失**: 当前是硬编码分流，未接入 LLM 推理 |

### 3.5 审查规则引擎 (Review Engine)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| 模板层 (Layer 1) | ✅ | `templates/*.py` | 5 模板: decap, pullup, esd, amr, pinmux |
| 配置层 (Layer 2) | ✅ | `default_rules.yaml` | 13 条规则，YAML 配置 |
| 知识层 (Layer 3) | ❌ | — | **缺失**: Datasheet 自动提取规则 |
| 白名单管理 | ⚠️ | `whitelist.py` | 读写逻辑有，Web UI 交互缺失 |
| 报告生成 | ✅ | `engine.py` | Markdown 格式报告 |

### 3.6 图谱工具层 (Graph Tools)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| 截断装饰器 | ✅ | `graph_tools.py` | MAX_RESULTS=50，超限返回摘要 |
| 器件属性查询 | ✅ | `get_component_nets` | RefDes→网络列表 |
| 网络器件查询 | ✅ | `get_net_components` | Net→器件列表 |
| 电源域查询 | ✅ | `get_power_domain` | 电压等级聚合 |
| I2C 器件查询 | ✅ | `get_i2c_devices` | I2C 总线扫描 |
| 信号路径追踪 | ⚠️ | `get_signal_path` | 基础实现，无 shortestPath 算法 |
| 图摘要 | ✅ | `get_graph_summary` | 统计信息 |
| **周边器件查询** | ❌ | — | **缺失**: `find_connected_peripherals(radius=2)` |

### 3.7 交互前端 (Web UI)

| 组件 | 状态 | 文件 | 说明 |
|------|------|------|------|
| **Streamlit 界面** | ❌ | `web_ui/app.py` | **缺失**: 完整前端 |
| **推理链路展示** | ❌ | — | **缺失**: Thought→Action→Observation 可视化 |
| **图谱可视化联动** | ❌ | — | **缺失**: Neo4j 局部网络渲染 |
| **HITL 反馈闭环** | ❌ | — | **缺失**: 白名单按钮 + Neo4j 回写 |

---

## 4. 关键数据质量问题

### 4.1 当前数据状态 (Beet7 网表)

| 问题 | 影响 | 优先级 |
|------|------|--------|
| **Pin.Type = None (100%)** | PinMux 检查失效、POWER/GND 检查失效 | P0 |
| **IC PartType 未分类** | MCU/FPGA/PMIC 识别失败 | P1 |
| **电容耐压未知** | AMR 电容检查跳过 | P1 |
| **无 `[:POWERED_BY]` 关系** | 电源树诊断、共因失效定位失效 | P1 |
| **无 Pin.Name** | 引脚功能检查无法按名称匹配 | P2 |

### 4.2 根因分析

```
Pin.Type 缺失
  └── ETL 未解析 pstchip.dat 的 PINUSE 字段
      └── chip_parser.py 有 PINUSE 解析逻辑但 main_etl.py 未写入 Neo4j

IC PartType 未分类
  └── 网表中的 PartType 是 Cadence 库名（如 "MT60B2G8HB"）
      └── 需要通过 MPN 或 Model 匹配器件类型词典

电容耐压未知
  └── AMRDataSource.get_capacitor_voltage_rating() 返回 None
      └── 需要接入料号库或 Datasheet 提取
```

---

## 5. 技术债务与风险

### 5.1 技术债务

| 债务项 | 影响 | 偿还计划 |
|--------|------|----------|
| Agent Core 未接入 LLM | 所有推理是硬编码关键词匹配 | Phase 3 |
| 状态机是简化版非 LangGraph | 扩展性受限 | Phase 3 |
| graph_tools 使用高权 Neo4j 账号 | 安全风险（PRD 要求只读） | Phase 2 |
| 无电源树关系 | 诊断功能大面积失效 | Phase 2 |

### 5.2 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Beet7 数据不完整导致规则误报 | 高 | 工程师不信任系统 | 白名单机制 + 置信度阈值 |
| LLM 本地部署性能不足 | 中 | 响应延迟 > 5s | vLLM 量化 + 缓存 |
| Datasheet OCR 准确率不足 | 中 | 知识库质量差 | 人工审核 + 多模型投票 |
| Neo4j 查询超时 | 低 | Agent 卡住 | 索引优化 + 截断机制 |

---

## 6. 实施路线图

### Phase 1: 数据质量提升 (2 周)

**目标**: 解决数据缺失问题，让已有规则真正可用

| 任务 | 负责人 | 工作量 |
|------|--------|--------|
| ETL 补充 Pin.Type 注入 | Jarvis | 2 天 |
| ETL 添加 BOM 标准化导入 + quality_checker | Jarvis | 3 天 |
| 创建 IC PartType 分类词典 + 自动标注 | Claude Code | 2 天 |
| Neo4j 创建 `[:POWERED_BY]` 关系 | Jarvis | 2 天 |
| Neo4j 配置只读账号 + graph_tools 切换 | Jarvis | 1 天 |

**交付物**:
- Pin.Type 覆盖率 > 95%
- IC PartType 分类覆盖率 > 80%
- 电源树关系建立
- 数据质量检查流水线

### Phase 2: 知识库建设 (2 周)

**目标**: 让 Tier 1 知识库有实际内容

| 任务 | 负责人 | 工作量 |
|------|--------|--------|
| Datasheet PDF→文本解析 (PyMuPDF) | Claude Code | 3 天 |
| 文本切片 + ChromaDB 向量化 | Claude Code | 2 天 |
| datasheet_linker: MPN 关联 Neo4j | Jarvis | 2 天 |
| Design Guide 上传与解析 | Claude Code | 3 天 |
| Tier 2/3 检索接口实现（PLM/Octopart） | Jarvis | 2 天 |

**交付物**:
- 首批 50+ Datasheet 入向量库
- MPN→规格参数关联
- Design Guide 可上传解析

### Phase 3: Agent 智能化 (2 周)

**目标**: Agent 从硬编码升级为 LLM 驱动

| 任务 | 负责人 | 工作量 |
|------|--------|--------|
| Agent Core 接入 LLM (ReAct 循环) | Claude Code | 4 天 |
| 诊断逻辑: 电源时序分析 | Claude Code | 3 天 |
| 诊断逻辑: 信号链路中断溯源 | Claude Code | 3 天 |
| 诊断逻辑: 共因失效定位 | Jarvis | 2 天 |
| 上下文防爆截断优化 | Jarvis | 2 天 |

**交付物**:
- LLM 驱动的意图理解
- Boot 失败自动诊断
- 信号链路故障定位

### Phase 4: Web UI + 闭环 (2 周)

**目标**: 完整的用户交互界面

| 任务 | 负责人 | 工作量 |
|------|--------|--------|
| Streamlit 基础界面 | Claude Code | 3 天 |
| 推理链路可视化 (Thought→Action→Observation) | Claude Code | 3 天 |
| Neo4j 图谱局部可视化联动 | Jarvis | 3 天 |
| HITL 白名单按钮 + Neo4j 回写 | Jarvis | 2 天 |
| 报告导出 (PDF/Markdown) | Claude Code | 1 天 |

**交付物**:
- 可交互的 Web 界面
- 图谱可视化
- 专家反馈闭环

---

## 7. 关键设计决策

### 7.1 已确认

| 决策 | 内容 | 理由 |
|------|------|------|
| 状态机框架 | 简化自定义（非 LangGraph） | 降低依赖，当前复杂度可控 |
| 审查引擎架构 | 三层（Template+Config+Knowledge） | PRD 要求，已验证可行 |
| LLM 底座 | 本地 Ollama (gemma4:26b) | 数据安全红线 |
| 数据库 | Neo4j 5.26 + ChromaDB | 图 + 向量双引擎 |

### 7.2 待决策

| 决策 | 选项 | 建议 |
|------|------|------|
| Datasheet OCR | Qianfan-OCR vs PyMuPDF+LLM | 建议先用 PyMuPDF+LLM（简单），Qianfan 作为增强 |
| IC 分类 | 规则词典 vs LLM 分类 | 建议规则词典（确定性强）+ LLM 辅助（覆盖边缘） |
| Web UI 框架 | Streamlit vs Gradio vs React | 建议 Streamlit（快速），后期可迁移 |
| 电源树生成 | 规则推导 vs LLM 推断 | 建议规则推导（从 LDO/Buck 引脚正向推导） |

---

## 8. 附录

### 8.1 文件清单

#### ✅ 已完成文件

```
etl_pipeline/
  ├── chip_parser.py          # pstchip.dat 解析
  ├── prt_parser.py           # pstxprt.dat 解析
  ├── net_parser.py           # pstxnet.dat 解析
  ├── main_etl.py             # 主 ETL 流程
  ├── load_to_neo4j.py        # Neo4j 注入（已集成到 main_etl）
  ├── load_topology.py        # 拓扑注入（已集成到 main_etl）
  ├── run_etl_validation.py   # ETL 验证
  └── run_real_etl.py         # 真实 ETL 执行

agent_system/
  ├── graph_tools.py          # 6+ Cypher 工具
  ├── knowledge_router.py     # Tier 1-3 检索路由
  ├── agent_core.py           # LangGraph 状态机
  ├── amr_engine.py           # AMR 降额引擎
  ├── init_neo4j_schema.py    # Neo4j Schema 初始化
  ├── review_engine/
  │   ├── engine.py           # ReviewRuleEngine 总控
  │   ├── whitelist.py        # 白名单管理
  │   ├── config/
  │   │   └── default_rules.yaml  # 13 条规则配置
  │   └── templates/
  │       ├── base.py         # RuleTemplate + Registry
  │       ├── decap.py        # 去耦电容检查
  │       ├── pullup.py       # 上拉电阻检查
  │       ├── esd.py          # ESD 保护检查
  │       ├── amr.py          # AMR 降额检查
  │       └── pinmux.py       # 引脚 MUX 检查
  └── schemas/
      ├── graph.py            # ComponentNode, PinNode, NetNode
      ├── agent.py            # AgentMessage, ExecutionStep, AgentState
      ├── review.py           # Violation, RuleConfig, WhitelistEntry
      └── knowledge.py        # KnowledgeQuery, SearchResult
```

#### ❌ 缺失文件

```
etl_pipeline/
  └── quality_checker.py      # 数据质量检查 + BOM 标准化

agent_system/
  ├── datasheet_processor.py  # Qianfan-OCR / PDF 解析
  ├── datasheet_linker.py     # MPN 关联 ChromaDB + Neo4j
  └── design_guide_processor.py  # Design Guide 上传与提取

web_ui/
  └── app.py                  # Streamlit 交互界面
```

### 8.2 环境配置

```bash
# 核心服务
Neo4j:     bolt://localhost:7687  (user: neo4j, password: SecretPassword123)
ChromaDB:  http://localhost:8000
Ollama:    http://localhost:11434  (model: gemma4:26b)

# Python 版本
Python 3.12.8

# 关键依赖
neo4j==5.26.0
chromadb==0.6.3
pydantic==2.10.4
python-dotenv==1.0.1
```

### 8.3 验证命令

```bash
# 1. 审查引擎全量测试
cd /data/schematic_agent/hardware_ai_expert
python3 -c "
from agent_system.review_engine import ReviewRuleEngine
from agent_system.graph_tools import _get_driver
engine = ReviewRuleEngine(_get_driver())
violations = engine.run_rules()
print(f'Total: {len(violations)}')
"

# 2. Agent Core 端到端测试
python3 agent_system/agent_core.py

# 3. ETL 数据质量检查
python3 etl_pipeline/run_etl_validation.py
```

---

## 9. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| V1.0 | 2026-04-29 | 初始版本，基于 PRD V3.0 + Solution V2.0 编制 | Jarvis |
