# schematic_agent — 后续工作全景规划

> 基于 2026-05-02 代码基线全面诊断后编制

---

## 一、当前基线诊断（真实状态）

### 1.1 数据底座

| 指标 | 数值 | 状态 |
|------|------|------|
| Components | 12,688 | ✅ |
| Pins | 49,570 | ✅ |
| Nets | 8,159 | ✅ |
| **Pin.Type 覆盖率** | **0 / 49,570 = 0.0%** | ❌ **P0** |
| **POWERED_BY 关系** | **0** | ❌ **P0** |
| PartType 覆盖率 | 12,688 / 12,688 = 100% | ⚠️ 质量差 |
| PartType = UNKNOWN | 1,651 (13%) | ⚠️ |
| PartType = IC | 36 | ⚠️ 极少 |
| 网络电压标注 | 1,416 / 8,159 = 17.3% | ⚠️ |

### 1.2 各模块真实状态

| 模块 | 状态 | 关键问题 |
|------|------|----------|
| ETL Pipeline | ⚠️ 可用 | Pin.Type / POWERED_BY / Quality Guard 未落地 |
| Review Engine | ⚠️ 能跑 | 14条规则，1,890违规，AMR有bug，误报高 |
| Agent Core | ⚠️ 能跑 | LLM Router成功率低，回退关键词，简化状态机 |
| Graph Tools | ✅ 可用 | 白名单属性缺失警告 |
| Knowledge Router | ⚠️ 框架有 | ChromaDB仅3条数据，知识库为空 |
| Datasheet Parser | ⚠️ 能导 | 未验证实际解析能力 |
| GraphRAG Bridge | ⚠️ 能导 | 未验证True GraphRAG链路 |
| HITL Workflow | ⚠️ 能导 | 未验证端到端审批流 |
| Web UI (Streamlit) | ⚠️ 代码有 | 632行，未启动验证 |
| AMR Engine | ❌ 有bug | 构造函数签名错误 + 字符串浮点比较崩溃 |

---

## 二、工作全景图

```
P0 数据底座修复 ────────────────────────────────────────┐
  ├─ Pin.Type 注入（ETL）                                │
  ├─ 电源树 [:POWERED_BY] 生成                           │
  ├─ PartType 精细化（1,651个 UNKNOWN）                  │
  └─ Quality Guard 集成到 ETL 流程                       │
                                                         ▼
P0 核心引擎修复 ────────────────────────────────────────┐
  ├─ AMR Engine 参数签名修正 + 类型比较bug              │
  ├─ Violation 对象字段统一                             │
  ├─ 白名单 Schema 与 Neo4j 对齐                        │
  └─ 规则误报调优（ESD/NC_FLOATING）                    │
                                                         ▼
P1 Agent 智能化升级 ────────────────────────────────────┐
  ├─ LLM Intent Router 稳定性提升                       │
  ├─ RoutingDecision 对象清理                           │
  ├─ 接入真实 LLM ReAct 循环（替代硬编码分流）          │
  └─ 诊断任务流：电源时序 + 信号链路溯源                │
                                                         ▼
P1 知识库建设 ──────────────────────────────────────────┐
  ├─ Datasheet 批量解析 + 向量化入库                    │
  ├─ MPN ↔ ChromaDB ↔ Neo4j 关联打通                  │
  ├─ Design Guide 上传与解析                            │
  └─ GraphRAG Bridge 验证与调通                         │
                                                         ▼
P2 Web UI 与闭环 ───────────────────────────────────────┐
  ├─ Streamlit 启动验证 + 各页面功能测试                │
  ├─ 推理链路可视化 (Thought→Action→Observation)        │
  ├─ Neo4j 局部图谱可视化 (PyVis)                       │
  └─ HITL 白名单审批 UI + Neo4j 回写验证                │
                                                         ▼
P2 生产化部署 ──────────────────────────────────────────┐
  ├─ vLLM 部署（替代 Ollama 开发环境）                  │
  ├─ Neo4j 只读账号配置                                 │
  ├─ 单元测试 + 集成测试覆盖                            │
  └─ Cypher 查询性能优化 + LLM 响应缓存                 │
                                                         ▼
P3+ 高级功能 ───────────────────────────────────────────┐
  ├─ True GraphRAG（LlamaIndex 完整集成）               │
  ├─ Cypher 计算下推（替代50节点截断）                  │
  ├─ 差分对追踪 (PCIe/MIPI)                             │
  ├─ 共因失效定位                                       │
  └─ 多网表/多项目支持                                  │
```

---

## 三、阶段详表

### Phase A：数据底座修复（P0，预计 1 周）

> **数据不净，上层全废。Pin.Type=0% 意味着 PinMux/ESD/电源检查大面积失效。**

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| A1 | **Pin.Type 注入** | `chip_parser.py` 已解析 PINUSE 字段，但 `main_etl.py` 未写入 Neo4j。需要补全 PINUSE→Pin.Type 映射逻辑，在 ETL 中写入。 | 2天 |
| A2 | **电源树 [:POWERED_BY] 生成** | 从 LDO/Buck 器件的 VOUT 引脚向下游推导供电关系。需要规则：VOUT→连接网络→下游器件→建立 POWERED_BY。 | 2天 |
| A3 | **PartType 精细化** | 1,651个 UNKNOWN 中，通过 Model/MPN 关键词扩展词典（如 TPS*→PMIC, STM32*→MCU, XC7*→FPGA）。 | 1天 |
| A4 | **Quality Guard 熔断** | 将 `quality_guard.py` 集成到 `main_etl.py` 末尾：PartType 标准化率<90% 或核心网络识别率<100% 时阻断并输出错误报告。 | 1天 |

**A阶段交付标准：**
- Pin.Type 覆盖率 > 95%
- POWERED_BY 关系 > 100 条（核心电源树建立）
- PartType UNKNOWN < 5%
- ETL 不达标时自动熔断并提示

---

### Phase B：核心引擎修复（P0-P1，预计 3-4 天）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| B1 | **AMR Engine 修复** | `AMREngine.__init__` 签名是 `(self, standard)`，但 `ReviewRuleEngine` 传的是 `driver`。修复调用链 + ResistorPowerChecker 中字符串与 float 比较错误。 | 1天 |
| B2 | **Violation 字段统一** | `Violation` 对象使用 `description` 但外部代码期望 `message`。统一字段名或加 `@property` 兼容。 | 0.5天 |
| B3 | **白名单 Schema 修正** | `whitelist.py` 写入属性名与查询属性名不一致。统一为 `rule`, `refdes`, `status`, `reason`, `added_by`, `added_at`。 | 0.5天 |
| B4 | **规则误报调优** | `EXTERNAL_IO_ESD` 438个违规、`NC_FLOATING_CHECK` 500个违规，大概率大量误报。需要增加过滤条件（如排除测试点/内部网络）。 | 1天 |
| B5 | **网络电压标注完善** | 当前仅17.3%网络有电压标注。扩展规则覆盖更多电源网络（如 1V0, 1V2, 1V35, 2V5, VDD_CORE 等常见命名）。 | 1天 |

**B阶段交付标准：**
- AMR 全部规则执行不报错
- Review Engine 运行无异常
- 白名单 CRUD 无警告
- 误报率降低 30%+

---

### Phase C：Agent 智能化（P1，预计 1 周）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| C1 | **LLM Intent Router 稳定化** | 当前 Ollama 调用成功率低。优化 prompt（更严格的 JSON schema 要求），增加重试机制，调试 gemma4:26b 的实际输出格式。 | 2天 |
| C2 | **RoutingDecision 对象清理** | 统一属性命名：`intent_type` vs `task_type`，`confidence`，`targets` 等字段全链路对齐。 | 0.5天 |
| C3 | **接入真实 LLM ReAct 循环** | 当前状态机是硬编码分流（classifier→reasoning→tool→specific→report）。引入真正的 LLM 决策节点：LLM 根据 observation 决定下一步 action，而非预设路径。 | 3天 |
| C4 | **诊断任务流** | 实现电源时序分析（检查上电顺序）、信号链路中断溯源（从故障点向上下游追踪）。 | 2天 |

**C阶段交付标准：**
- LLM 意图分类成功率 > 80%
- Agent 能处理复合意图（"查 I2C 上拉 + TPS5430 公式"）
- 诊断任务流能输出电源树分析/信号路径报告

---

### Phase D：知识库建设（P1-P2，预计 1 周）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| D1 | **Datasheet 批量解析** | `datasheet_parser.py` 已存在。验证 PyMuPDF 解析能力，批量处理项目中的 Datasheet PDF，切片后入 ChromaDB。 | 2天 |
| D2 | **MPN 关联** | 建立 `(Component {MPN})` ↔ `(VectorChunk {mpn})` 的关联机制。`knowledge_router.py` 查询时先查 Neo4j 找 MPN，再查 ChromaDB。 | 1.5天 |
| D3 | **Design Guide 处理** | 上传入口 + 解析 + 向量化。可参考 datasheet_parser 逻辑复用。 | 1.5天 |
| D4 | **GraphRAG Bridge 验证** | 验证 `(VectorChunk)-[:DESCRIBES]->(Component)` 的创建与查询链路。 | 1天 |

**D阶段交付标准：**
- ChromaDB 中 Datasheet chunks > 500
- KnowledgeRouter 能返回带上下文的规格参数
- GraphRAG Bridge 端到端通

---

### Phase E：Web UI 与闭环（P2，预计 1 周）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| E1 | **Streamlit 启动验证** | `streamlit run web_ui/app.py`，修复 import 错误、配置缺失等问题。 | 1天 |
| E2 | **聊天界面打通** | 确保 Web UI 的聊天框能实际调用 `HardwareAgent.review/diagnose/query_spec`。 | 1天 |
| E3 | **审查报告可视化** | violations 列表展示、按规则分组、严重程度着色。 | 1天 |
| E4 | **HITL 审批面板** | 白名单添加/移除按钮，工程师一键审批，回写 Neo4j。 | 1天 |
| E5 | **推理链路展示** | `execution_trace` 数据渲染为时间线/折叠面板。 | 1天 |
| E6 | **Neo4j 图谱可视化** | 集成 `st.graphviz_chart` 或 PyVis，展示查询相关的局部子图。 | 1天 |

**E阶段交付标准：**
- Web UI 可完整访问，无报错
- 聊天 → Agent → 报告 端到端通
- 工程师可在 UI 上审批白名单

---

### Phase F：生产化部署（P2，预计 3-5 天）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| F1 | **vLLM 部署** | 部署 vLLM 服务加载 gemma4:26b（或更优模型），配置 OpenAI 兼容 API。 | 1天 |
| F2 | **Agent 切到 vLLM** | 替换 Ollama 地址为 vLLM 地址，验证所有 LLM 调用正常。 | 0.5天 |
| F3 | **Neo4j 只读账号** | 创建 readonly 角色，graph_tools 切换只读连接，保留写权限给 ETL/HITL。 | 0.5天 |
| F4 | **单元测试** | ETL parser、review engine templates、graph_tools 核心函数补单元测试。 | 1天 |
| F5 | **集成测试** | 端到端：网表 → ETL → 审查 → 报告，验证完整链路。 | 1天 |
| F6 | **Cypher 性能优化** | 为大查询（如 GND 网络器件）加 LIMIT/聚合，避免超时。 | 0.5天 |
| F7 | **LLM 响应缓存** | 相同查询缓存结果，降低 LLM 调用成本。 | 0.5天 |

**F阶段交付标准：**
- vLLM 服务稳定运行，并发 > 4
- 所有 Cypher 查询 < 2s
- 单元测试覆盖率 > 60%
- Agent 全链路通过集成测试

---

### Phase G：高级功能（P3+，视需求排期）

| # | 任务 | 说明 | 优先级 |
|---|------|------|--------|
| G1 | **True GraphRAG** | LlamaIndex 完整集成：文档 chunk 与 Neo4j 实体建立 `[:DESCRIBES]`，联合检索。 | 低 |
| G2 | **Cypher 计算下推** | 超大节点网络（如 GND）在图库层聚合摘要，不截断。 | 低 |
| G3 | **差分对追踪** | `trace_differential_pair()` 工具，检查 PCIe/MIPI 等差分信号一致性。 | 低 |
| G4 | **共因失效定位** | 基于电源树/信号树的共同上游节点定位。 | 低 |
| G5 | **多网表支持** | 支持切换不同项目网表，数据隔离。 | 低 |
| G6 | **规则热更新** | `default_rules.yaml` 修改后无需重启 Agent。 | 低 |

---

## 四、优先级总览

### 立即开工（本周）

1. **A1 + A2 + A3** — Pin.Type + 电源树 + PartType 精细化
2. **B1 + B2 + B3** — AMR修复 + Violation统一 + 白名单Schema

### 下周

3. **A4 + B4 + B5** — Quality Guard + 规则调优 + 电压标注
4. **C1 + C2** — LLM Router 稳定化 + 对象清理

### 第三周

5. **C3 + C4** — ReAct 循环 + 诊断任务流
6. **D1 + D2** — Datasheet 批量导入 + MPN 关联

### 第四周

7. **D3 + D4 + E1 + E2** — Design Guide + GraphRAG验证 + Web UI启动
8. **E3 + E4 + E5 + E6** — 报告可视化 + HITL面板 + 推理链路 + 图谱可视化

### 第五周

9. **F1 ~ F7** — vLLM部署 + 测试 + 性能优化

---

## 五、关键风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| gemma4:26b 理解中文意图能力差 | 中 | LLM Router 成功率低 | 换用更强模型（如 Qwen2.5-14B/32B）或中英混合 prompt |
| Datasheet PDF 解析质量差 | 中 | 知识库垃圾进垃圾出 | PyMuPDF+LLM 提取，HITL 审核兜底 |
| 电源树规则推导覆盖不足 | 高 | POWERED_BY 关系缺失 | 从 LDO/Buck 正向推导 + 电压网络逆向推导，双保险 |
| ETL 改崩已有数据 | 低 | Neo4j 数据损坏 | 改前做 `neo4j-admin dump` 备份 |
| vLLM 显存不足 | 中 | 无法加载更大模型 | gemma4:26b 约 16GB，当前环境需确认 GPU 显存 |

---

## 六、需要 human 决策的事项

1. **GPU 显存情况？** vLLM 部署需要确认当前机器的 GPU 型号和显存大小。
2. **Datasheet 来源？** 项目目录下是否有 Datasheet PDF？还是需要从 PLM/供应商下载？
3. **生产环境部署目标？** 是单机 Docker 部署还是 K8s 集群？
4. **Phase G 高级功能是否有紧急需求？** 比如多网表支持、差分对检查是否在近期 roadmap 内？
5. **模型选择？** gemma4:26b 对中文理解一般，是否考虑换 Qwen 或 DeepSeek？
