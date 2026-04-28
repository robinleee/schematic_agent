# schematic_agent 项目分析报告

**分析时间：** 2026-04-28 15:14 (Asia/Shanghai)
**分析师：** Jarvis

---

## 一、项目定位

这是一个**硬件 AI 专家系统**，面向 EDA 电路图谱的审查与故障诊断。核心目标是：

> 通过解析 Cadence 网表构建 Neo4j "数字孪生" 图谱，结合本地大模型，实现原理图自动化审查 + 硬件故障根因定位。

---

## 二、项目结构

```
schematic_agent/
├── hardware_ai_expert/          ← 主开发目录（较新）
│   ├── agent_system/             ← Agent 核心逻辑（状态机、工具箱）
│   ├── etl_pipeline/            ← Cadence 网表解析 + Neo4j 注入
│   ├── web_ui/                   ← Streamlit 前端
│   ├── data/                     ← 原始网表 + 输出产物
│   ├── .env                      ← 敏感配置（Neo4j 密码等）
│   └── requirements.txt
│
└── netlist_parser/              ← 早期版本（代码重复，未维护）
    └── PRD/                      ← 产品设计文档（非常完整）
```

**两个目录功能高度重复**，`hardware_ai_expert/` 是 `netlist_parser/` 的后续重构版本。

---

## 三、技术架构

```
用户输入 (Streamlit UI)
         ↓
    ┌─────────────┐
    │  LangGraph  │  ← Agent 状态机 (agent_core.py)
    │  状态机      │
    └──────┬──────┘
           ↓
    ┌──────────────┐   ┌────────────────┐
    │  Graph Tools │   │ Knowledge Router│
    │  (Neo4j 查询) │   │ (Tier 1-3 RAG)  │
    └──────┬───────┘   └───────┬────────┘
           ↓                   ↓
    ┌─────────────┐     ┌──────────────┐
    │   Neo4j     │     │ ChromaDB/     │
    │  图数据库   │     │ Milvus 向量库 │
    └─────────────┘     └──────────────┘
           ↓                   ↓
    ┌──────────────────────────────────┐
    │        本地 LLM (vLLM)            │
    └──────────────────────────────────┘
```

---

## 四、核心模块解析

### 4.1 ETL 层 — Cadence 网表解析

| 文件 | 功能 | 状态 |
|------|------|------|
| `chip_parser.py` | 解析 `pstchip.dat` → 器件库（属性、引脚定义） | ✅ 完成 |
| `prt_parser.py` | 解析 `pstxprt.dat` → RefDes → 库模型名映射 | ✅ 完成 |
| `net_parser.py` | 解析 `pstxnet.dat` → 拓扑三元组 | ✅ 完成 |
| `main_etl.py` | 三表融合 + Pydantic 校验 + Neo4j 直接注入 | ✅ 完成 |
| `load_to_neo4j.py` | 节点批量写入 | ✅ 可用 |

解析器用**状态机**逐行处理 Cadence 格式文件（`latin-1` 编码），已能处理真实网表数据。

### 4.2 图谱层 — Neo4j Schema

定义了 5 类节点：
- `:Component` — 器件（RefDes, Model, Value, PartType, MPN...）
- `:Pin` — 引脚（Number, Type: POWER/SIGNAL/GND）
- `:Net` — 网络（Name, VoltageLevel）
- `:ReviewRule` — 审查规则
- `:ReviewWhitelist` — 白名单

关系：`Component → HAS_PIN → Pin → CONNECTS_TO → Net`

### 4.3 Agent 层 — LangGraph 状态机

基于 LangGraph 的 `StateGraph`，设计了：
- `BaseAgentState` — 基础状态（messages, tool_call_count, visited_nodes）
- `ReviewState` / `DiagnosisState` — 任务特定状态
- 节点：Reasoning Node、Tool Execution Node、Router Node
- 防死循环：visited_nodes + tool_call_count 计数器

### 4.4 检索路由 — 三级降级 RAG

```
Tier 1: 本地 ChromaDB/Milvus (毫秒级，安全)
Tier 2: 内网 PLM 系统 (公司 PDM)
Tier 3: 脱敏公网 (仅携带 MPN，剥离项目上下文)
```

### 4.5 审查规则引擎 — 三层架构

```
Template 层：通用检查模板（decap_check, pullup_check...）
Config 层：YAML 实例化规则
Knowledge 层：从 Datasheet AI 自动提取
```

---

## 五、代码质量评估

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐ | 分层清晰，PRD 文档极为详尽 |
| **代码完整性** | ⭐⭐⭐ | 核心解析器完成，Agent 状态机有设计但未看到完整实现代码 |
| **PRD 文档** | ⭐⭐⭐⭐⭐ | 非常完整，覆盖架构、流程、API 设计 |
| **安全设计** | ⭐⭐⭐⭐ | Neo4j 只读账号、防爆截断、Tier-3 脱敏 |
| **可维护性** | ⭐⭐⭐ | `hardware_ai_expert` 与 `netlist_parser` 功能重复 |

---

## 六、⚠️ 发现的问题

### 6.1 代码重复

`netlist_parser/` 和 `hardware_ai_expert/` 的 ETL 和 Parser 代码几乎一致，但 `netlist_parser/` 明显是早期版本，未同步更新。

### 6.2 `.env.swp` 泄露风险

存在 `hardware_ai_expert/.env.swp`（Vim 交换文件），如果含 Neo4j 密码会被暴露：

```bash
-rw-r--r--  1 caros caros 12288 Apr 28 14:37 .env.swp  ⚠️
```

### 6.3 Agent 核心实现代码缺失

`agent_system/` 目录只有 `__init__.py`，**看不到 `agent_core.py`、`graph_tools.py`、`knowledge_router.py` 等核心文件**。这些在 PRD 中有详细设计，但代码尚未实现。

### 6.4 敏感信息硬编码在 .env

```env
NEO4J_PASSWORD=SecretPassword123
NEO4J_READONLY_PASSWORD=ReadOnlyPassword123
```

这些凭据直接写在文件中，需要确认 `.gitignore` 是否已排除。

### 6.5 Web UI 未实现

`web_ui/` 只有 `__init__.py`，Streamlit 应用未开发。

---

## 七、依赖栈

```
neo4j >= 5.0          图数据库
langchain >= 0.2       Agent 框架
langgraph >= 0.1      状态机
openai >= 1.0         API 兼容
chromadb >= 0.4       向量库
streamlit >= 1.30     前端
pydantic >= 2.0       数据校验
pandas >= 2.0         数据处理
vllm                  本地 LLM 推理
```

---

## 八、总结

| 维度 | 结论 |
|------|------|
| **项目成熟度** | 中等。ETL 解析层完整可用，Agent 核心有设计但实现不完整 |
| **工程价值** | 高。硬件 EDA + GraphRAG + 本地 LLM 是不错的切入方向 |
| **安全风险** | 低。设计有安全考虑，但 `.env.swp` 需立即清理 |
| **最大问题** | Agent 核心代码（`agent_core.py`、`graph_tools.py` 等）实际不存在，仅 PRD 有设计 |

**建议下一步**：确认 `agent_system/` 下的核心 Python 文件是否存在，或需要基于 PRD 文档重新实现。

---

## 九、安全加固建议

1. **立即清理** `hardware_ai_expert/.env.swp` 文件
2. 在 `.gitignore` 中添加 `*.swp`、`*.swx`、`.env` 等敏感文件
3. 考虑将 Neo4j 密码从 `.env` 迁移至环境变量或密钥管理服务
4. Agent 系统实现时，确保 Neo4j 连接使用只读账号（已设计，需落地）
