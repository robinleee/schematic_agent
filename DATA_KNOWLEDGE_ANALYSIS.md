# D 阶段：知识库需求分析与建设方案

## 一、当前状态诊断

### 1.1 ChromaDB 现状
```
Collection: hardware_datasheets
Records: 3（仅 MT25QU256 Flash 的手动录入数据）
Content: 通用规格描述（非结构化文本）
Embedding: 默认 l2 空间，768 维
```

**问题：当前知识库几乎为空，所有 RAG 查询返回空结果。**

### 1.2 Neo4j 器件清单（需要知识支撑的关键器件）

| 类型 | 数量 | 代表型号 | 知识需求 |
|------|------|----------|----------|
| **DRAM** | 64 | MT60B2G8HB (60×) | 时序参数、电压等级、端接要求 |
| **PMIC** | 57 | MPQ2176, MP87270, MPQ4371, P8910 | 输出电压公式、开关频率、效率曲线 |
| **IC** | 256 (67 unique) | TI 74CBTLV3251, NXP NTS0104, ADI MAX25302 | 逻辑电平、驱动能力、ESD 等级 |
| **Flash** | 9 | MX66L1G45, MT25QU256 | 读写时序、电压范围、容量 |
| **MCU** | 6 | — | GPIO 配置、外设接口 |
| **SOC** | 2 | BCM89581, BCM89586 | 复杂电源树、启动序列 |
| **FPGA** | 1 | — | IO 标准、时钟要求 |

**总计：约 140 个唯一器件型号需要 datasheet 知识。**

---

## 二、知识类型分类（四层金字塔）

### Layer 1: 器件级 Datasheet 知识（P0 - 最紧急）

**来源：** 厂商 PDF Datasheet
**内容：** 电气参数、时序图、引脚定义、封装信息
**用途：**
- AMR 降额检查（电容耐压、电阻功率、温度范围）
- Agent 问答（"TPS5430 的最大输入电压是多少？"）
- HITL 审核对照（验证 LLM 提取的参数是否正确）

**关键参数类型（已定义在 datasheet_parser.py）：**
```python
ParamType:
  CAP_VOLTAGE_RATING  # 电容耐压 → AMR 电容降额
  CAP_ESR             # ESR → 电源完整性分析
  RES_POWER_RATING    # 电阻额定功率 → AMR 电阻降额
  VOLTAGE_MIN/MAX     # 工作电压范围 → 电源兼容性
  CURRENT_MAX         # 最大电流 → 负载能力评估
  TEMP_MIN/MAX        # 温度范围 → 可靠性分析
  VOUT_FORMULA        # 输出电压公式 → PMIC 配置验证
  INDUCTANCE          # 电感值 → DC-DC 设计
  FREQUENCY           # 开关频率 → EMI 分析
```

### Layer 2: 设计规范知识（P1）

**来源：** 企业内部 Design Guide、行业规范（JEDEC、PCI-SIG、MIPI）
**内容：**
- I2C/SPI/UART 总线设计规范（上拉电阻值、走线长度、拓扑）
- DDR 设计规则（端接、匹配、时序预算）
- 电源设计规范（去耦电容配置、PCB 布局）
- ESD 防护等级（HBM/CDM 标准）
- 高速信号完整性（阻抗控制、等长匹配）

**用途：**
- ReviewEngine 规则参数调优（如 I2C 上拉 4.7K 的依据）
- 自动匹配设计规范与实现差异
- 生成审查报告时引用规范条款

### Layer 3: 项目级历史知识（P1）

**来源：** 历史审查报告、故障案例分析、工程师经验
**内容：**
- 常见违规模式（如 "XX 项目多次出现 VCC 去耦不足"）
- 已知器件问题（如 "某批次电容 ESR 偏高"）
- 平台特定约束（如 "Beet7 项目 PMIC 需预留 20% 余量"）

**用途：**
- 优先审查高风险区域
- 相似问题快速定位
- 知识传承（新工程师 onboarding）

### Layer 4: 通用硬件知识（P2）

**来源：** 教科书、技术博客、应用笔记
**内容：**
- 电路理论（欧姆定律、RC 时间常数）
- 器件物理（MOSFET 工作原理、电容特性）
- 标准接口协议（I2C 时序、SPI 模式、PCIe 链路训练）

**用途：**
- Agent 解释审查发现（"为什么这个电容需要 16V 耐压？"）
- 故障根因分析（"输出纹波过大的可能原因"）

---

## 三、具体知识需求清单（按优先级）

### P0: AMR 引擎急需（阻塞电容降额检查）

当前 `amr.py` 中电容检查被跳过：
```python
# CapacitorVoltageChecker 依赖 AMRDataSource.get_capacitor_voltage_rating()
# 当前 AMRDataSource 返回 None，因此跳过高风险误报
```

**需要的知识：**
1. **电容耐压数据库** — 所有项目中使用的电容型号 → 额定耐压值
   - 当前有 5,714 个电容，主要来自 `graph_components.json`
   - 需要建立 `(Model) → (VoltageRating)` 映射
   
2. **电阻功率数据库** — 封装 → 额定功率映射（已有部分代码）
   ```python
   # amr_engine.py 中已有
   PACKAGE_POWER_MAP = {
       "R0402": 0.0625,  # 1/16W
       "R0603": 0.1,     # 1/10W
       "R0805": 0.125,   # 1/8W
       ...
   }
   ```
   - 需要补充更多封装（R1206, R1210, R2512 等）

3. **PMIC 输出电压公式** — 用于验证反馈电阻配置
   - 如 TPS5430: Vout = 1.221V × (1 + R1/R2)
   - 当前项目中的 57 个 PMIC 都需要此数据

### P1: ReviewEngine 规则支撑

当前 14 条规则中，部分依赖硬编码阈值，需要知识库支撑：

| 规则 | 当前实现 | 需要知识 |
|------|----------|----------|
| I2C_STD_PULLUP | 硬编码 2.2K-10K | I2C 规范（不同电压等级对应电阻范围） |
| OPENDRAIN_PULLUP | 硬编码检查 | 开漏引脚定义库 |
| EXTERNAL_IO_ESD | 438 误报 | ESD 等级数据库（哪些引脚已有内部保护） |
| NC_FLOATING_CHECK | 500 误报 | NC 引脚处理规范（内部上拉/下拉？） |
| DECOUPLING_CAP | 简单检查 | 去耦电容配置规范（按电源轨） |

### P1: Agent 问答能力

工程师可能问的问题：
- "MPQ2176 的开关频率是多少？" → 需要 PMIC 规格
- "DDR5 PMIC P8910 的 VDDQ 输出能力？" → 需要 DRAM PMIC 规格
- "BCM89581 的 SerDes 速率？" → 需要 SOC 规格

---

## 四、数据源分析

### 4.1 已有数据源

| 数据源 | 位置 | 内容 | 质量 |
|--------|------|------|------|
| chip_library (pstchip.dat) | `data/netlist_Beet7/` | 12,688 器件的 Pin Name/Type/PINUSE | 高 |
| graph_components.json | `data/output/` | 器件属性（PartType/Model/Value） | 高 |
| topology_triplets.json | `data/output/` | 49,580 个连接关系 | 高 |
| pin_type_map.json | `data/output/` | 49,570 个 Pin 类型映射 | 高 |
| amr_data.yaml | 代码中 | 少量 AMR 参数 | 低（待扩展） |

### 4.2 缺失数据源

| 数据源 | 获取方式 | 优先级 |
|--------|----------|--------|
| **Datasheet PDF** | 厂商官网 / 内部库 | P0 |
| **Design Guide** | 内部文档 | P1 |
| **封装功率对照表** | JEDEC 标准 + 厂商规格 | P0 |
| **电容耐压数据库** | 料号库 / 采购系统 | P0 |
| **I2C/PCIe 规范** | NXP/PCI-SIG 公开文档 | P1 |

---

## 五、导入方案设计

### 方案 A: 最小可行方案（推荐先执行）

**目标：** 1-2 天内让 AMR 电容降额和 Agent 问答可用

**步骤：**
1. **提取项目中的关键 MPN 列表**（从 Neo4j 导出 67 个唯一 IC model + PMIC model）
2. **手工录入核心参数**（每个器件 5-10 个关键参数）
   - 使用 `datasheet_parser.py` 的数据模型
   - 格式：`mpn, param_type, value, unit, source`
3. **批量导入 ChromaDB**（文本切片 + 结构化参数双存储）
4. **建立 MPN → VectorChunk 关联**

**预期结果：**
- ChromaDB 记录数：~500（67 器件 × 平均 7 条参数）
- AMR 电容检查：从"跳过"变为"可用"
- Agent 问答：能回答核心器件的规格问题

### 方案 B: 自动化批量方案（后续迭代）

**目标：** 覆盖全部 140+ 器件

**步骤：**
1. **收集 Datasheet PDF**（通过爬虫或内部系统导出）
2. **PDF 解析 pipeline**
   - `datasheet_parser.py` 提取文本和表格
   - LLM 识别参数表区域（ABSOLUTE MAXIMUM RATINGS, ELECTRICAL CHARACTERISTICS）
   - LLM 结构化提取参数 → `DatasheetParameter` 列表
3. **HITL 审核**
   - 工程师在 Web UI 上审核 LLM 提取的参数
   - 确认后落盘到 `amr_data.yaml` 和 ChromaDB
4. **持续更新**
   - 新器件自动加入解析队列
   - 错误参数通过 HITL 修正

---

## 六、技术实现路径

### 6.1 数据存储设计

```
ChromaDB (向量检索)
  └── collection: hardware_datasheets
      ├── documents: 文本切片（datasheet 段落）
      ├── embeddings: 768-dim 向量
      └── metadata: {mpn, page, chunk_type, param_type?}

Neo4j (图谱关系)
  └── (VectorChunk {chunk_id})-[:DESCRIBES]->(Component {Model})
  
amr_data.yaml (结构化参数)
  └── 器件 → 参数列表（用于确定性规则）
```

### 6.2 查询链路

```
用户提问: "MPQ2176 的输出电压范围？"
         ↓
KnowledgeRouter
  1. 从 Neo4j 查找 Component {Model: "MPQ2176"}
  2. 获取关联的 VectorChunk（通过 [:DESCRIBES]）
  3. 向量检索 ChromaDB 中相似内容
  4. 返回：结构化参数 + 原文片段
         ↓
Agent 生成回答
```

### 6.3 与现有代码的集成点

| 现有模块 | 集成方式 |
|----------|----------|
| `datasheet_parser.py` | 解析 PDF → 提取参数 → 入 ChromaDB |
| `graph_rag_bridge.py` | 建立 VectorChunk ↔ Component 关系 |
| `amr_engine.py` | 从 ChromaDB/yaml 读取 AMR 参数 |
| `review_engine/templates/` | 规则查询知识库获取阈值 |
| `llm_intent_router.py` | 意图识别后选择知识库查询策略 |

---

## 七、工作量估算

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 导出项目 MPN 清单 | 0.5 天 | 无 |
| 核心器件参数手工录入（20 个） | 1 天 | MPN 清单 |
| 批量导入 ChromaDB | 0.5 天 | 参数数据 |
| MPN ↔ Component 关联 | 0.5 天 | ChromaDB 数据 |
| AMR 引擎接入知识库 | 1 天 | 关联完成 |
| 验证端到端查询 | 0.5 天 | 全部完成 |

**最小可行方案总计：约 4 天**

---

## 八、关键决策建议

### 决策 1: 先做手工录入还是等自动化？
**建议：先手工录入 20 个核心器件。**
- 理由：自动化 PDF 解析准确率不稳定（需要 HITL 审核），手工录入可快速 unblock AMR 和 Agent 问答。
- 20 个器件覆盖项目中 80% 的关键器件（PMIC + DRAM + 高频 IC）。

### 决策 2: ChromaDB vs Neo4j 向量索引？
**建议：双轨并行。**
- ChromaDB：存储文档切片（非结构化文本），用于语义检索
- Neo4j：存储结构化参数和关系，用于确定性查询
- GraphRAG Bridge：联合检索时先查 Neo4j 结构化数据，再查 ChromaDB 语义数据

### 决策 3: 参数精度要求？
**建议：分三级精度。**
- **精确值**（用于 AMR 规则）：耐压、功率、温度 → 必须 100% 准确（HITL 审核）
- **典型值**（用于 Agent 问答）：开关频率、效率 → 允许 ±10% 误差
- **范围值**（用于设计建议）：推荐电容值、走线长度 → 区间即可

---

## 九、验收标准

### D 阶段交付检查清单

- [ ] ChromaDB 中 Datasheet chunks ≥ 500 条
- [ ] 至少 20 个核心器件有完整参数覆盖
- [ ] AMR 电容降额检查从"跳过"变为"执行"
- [ ] Agent 能回答 "XX 器件的 YY 参数是多少？"
- [ ] KnowledgeRouter 查询返回带 source 的上下文
- [ ] GraphRAG Bridge 端到端验证通过

---

## 十、下一步行动

如果你确认推进 D 阶段，我建议按以下顺序执行：

1. **导出 MPN 清单**（自动，5 分钟）
2. **选择 20 个核心器件**（人工，30 分钟）
3. **创建参数录入模板**（脚本，1 小时）
4. **批量导入 ChromaDB**（脚本，2 小时）
5. **验证 AMR 电容检查**（测试，2 小时）

要我立即开始第 1 步（导出 MPN 清单）吗？
