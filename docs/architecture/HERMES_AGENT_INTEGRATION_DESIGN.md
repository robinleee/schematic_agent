# schematic_agent × Hermes Agent 集成设计

- **状态**：已评审（2026-10-23）
- **决策人**：robinshui
- **执行**：Jarvis
- **目标**：以 Hermes Agent 作为 schematic_agent 的唯一 AI 引擎，现有专业能力降级为 MCP 工具

---

## 1. 背景与目标

schematic_agent 当前使用自研 `AgentOrchestrator` + `ReActAgent` 承担意图识别、任务规划、工具选择、多步推理与报告生成。该层长期维护成本高，且在会话记忆、模型切换、错误恢复、长上下文方面能力有限。

Hermes Agent 已具备：

- 成熟的工具调用循环与多步规划
- 会话存储、记忆、压缩、模型 fallback
- ACP Server 与 OpenAI 兼容 HTTP API（`/v1/chat/completions`、`/v1/responses`、`/v1/runs/{id}/approval`）
- MCP 客户端，支持 stdio / HTTP 传输
- 通用审批系统（含 MCP 工具级 gate）

因此将 AI 引擎替换为 Hermes，schematic_agent 只保留**确定性专业能力**与**领域数据**。

### 非目标

- 不重写 ReviewEngine、AMR、ETL、GraphRAG、Neo4j 访问层
- 不把领域 HITL 状态机迁移到 Hermes 审批
- 不改变现有前端交互范式（仍为 HTTP + SSE）

---

## 2. 关键决策

| # | 决策项 | 结论 |
|---|---|---|
| 1 | 替换范围 | **C. 全面替换**：Hermes 接管路由、推理、记忆、工具编排，逐步淘汰 ReAct 层 |
| 2 | 迁移策略 | **A. 渐进替换**：旧引擎保留 2–4 周作为灰度与故障回退，验收后删除 |
| 3 | 部署隔离 | **A. 独立 Hermes profile**，与个人实例配置/会话/凭证隔离 |
| 4 | 审批分层 | **L1 Hermes 审批门（动作授权）+ L2 领域 HITL（工程结论）**，互不替代 |
| 5 | 会话与项目 | **A. 一会话一项目**，切项目即新开会话 |
| 6 | 工具粒度 | **A. 聚合优先**：8 个业务级 MCP 工具，不暴露底层细粒度函数 |

---

## 3. 目标架构

```
┌──────────────────────────────────────────────┐
│ React 前端                                    │
│  - 对话流 / 工具调用轨迹                       │
│  - 审批卡片（L1）                              │
│  - HITL 面板（L2，沿用现有）                    │
└───────────────────┬──────────────────────────┘
                    │ HTTP + SSE
┌───────────────────▼──────────────────────────┐
│ FastAPI 后端                                  │
│  ┌────────────────────────────────────────┐  │
│  │ AgentEngine（抽象层）                   │  │
│  │  ├── HermesEngine   （主）              │  │
│  │  └── NativeEngine   （回退，2–4 周）     │  │
│  └────────────────────────────────────────┘  │
└───────────────────┬──────────────────────────┘
                    │ OpenAI 兼容 + SSE
┌───────────────────▼──────────────────────────┐
│ Hermes Gateway（独立 profile: schematic）      │
│  - 会话 / 记忆 / 压缩                         │
│  - 规划 / 工具选择 / 报告生成                  │
│  - 审批门（MCP write tools）                   │
└───────────────────┬──────────────────────────┘
                    │ MCP (stdio / HTTP)
┌───────────────────▼──────────────────────────┐
│ schematic_agent MCP Server                    │
│  - 8 个业务级工具                              │
│  - 项目边界校验                                │
└───────────────────┬──────────────────────────┘
                    │
   ┌────────────────┼─────────────────┐
   ▼                ▼                 ▼
 Neo4j         ReviewEngine/AMR    GraphRAG/KB
（权威数据）    （确定性规则）      （ChromaDB/Datasheet）
```

---

## 4. 组件职责边界

### Hermes 负责

- 意图识别与任务分解
- 工具选择与多步编排
- 会话记忆、上下文压缩、长上下文管理
- 模型选择与 fallback
- 错误恢复与重试
- 最终自然语言报告生成

### schematic_agent 负责

- Neo4j 图谱查询与遍历
- ReviewEngine 规则审查（9 模板 / 24 规则）
- AMR 降额计算、MPN 解码
- GraphRAG 检索（Tier0–Tier3）
- Datasheet 解析与知识入库
- 领域 HITL 状态机与审计持久化

### 明确不做

- 不允许 Hermes 直接拼 Cypher
- 不允许 Hermes 绕开 ReviewEngine 自行判断规则合规
- 不允许 Hermes 直接写 Neo4j

---

## 5. 接口契约

### 5.1 会话键

Hermes `POST /runs` 请求体字段 `session_id`：

```
{user_id}:{project_id}:{conversation_id}
```

- 由 FastAPI 组合（`api/routers/agent_runs.py::_session_key`），Hermes 不解析语义
- `user_id` 缺省 `web`；`project_id` 缺省 `all`（全库）；非法字符按 uuid 重新生成
- 一个 conversation 只对应一个 project：FastAPI 维护 `conversation → project` 绑定表，不一致返回 **409**（`HERMES_SESSION_TTL`，默认 24h）
- 绑定表是**进程内**存储（单 worker 部署成立）；多 worker / 多副本需换 Redis 或库表
- 清理沿用 Hermes `session_store_max_age_days`，FastAPI 侧仅做 TTL 淘汰（上限 2000 条）

### 5.2 项目上下文注入

- 请求体 `instructions` 注入当前项目元信息（项目名、器件数、网络数、电压域概要）
- `instructions` 仅作提示，**不作为隔离依据**
- 隔离由 MCP Server 强制校验

### 5.3 MCP 传输

- **当前实现：stdio** — profile 配置 `.venv-mcp/bin/python -m mcp_server.server`，由 Hermes 网关作为子进程管理
  - 改 MCP 代码后子进程不会自动重载：需重启网关（`echo caros | sudo -S systemctl restart hermes-gateway-cfa4b284`）或杀掉子进程
- 生产拟改 HTTP（多会话共享 + 健康检查），**尚未实施**
- 每个 Hermes profile 配置独立 server 条目，`trust: untrusted`（强制写工具审批）

### 5.4 工具返回

统一结构：

```json
{
  "project_id": "proj_xxx",
  "tool": "diagnose_fault",
  "ok": true,
  "summary": "…",
  "data": { },
  "truncated": false
}
```

LLM 可见 `summary` 与必要的 `data`；完整数据留在服务端，避免上下文膨胀。

---

## 6. 工具面设计（6 只读 + 2 写门控）

| 工具 | 能力 | readOnlyHint | 底层实现 |
|---|---|---|---|
| `project_overview` | 项目规模、电源域概览、网络统计 | `true` | `get_graph_summary` / `get_power_domain` |
| `query_graph` | 器件-网络、网络-器件、I2C 设备、电源树 | `true` | `get_component_nets` / `get_net_components` / `get_i2c_devices` / `get_power_tree` |
| `trace_signal` | 信号路径、差分对追踪与发现 | `true` | `get_signal_path` / `trace_signal_path` / `trace_differential_pair` / `discover_diff_pairs` |
| `diagnose_fault` | 电源链、故障根因、上电时序、共因失效 | `true` | `trace_power_chain` / `trace_fault_root` / `analyze_power_sequence` / `find_common_cause` / `get_common_cause_graph` / `common_cause_risk_score` |
| `run_review` | 规则审查并生成违规摘要 | `true` | `ReviewRuleEngine` |
| `search_knowledge` | GraphRAG 四级检索 + Datasheet | `true` | `KnowledgeRouter` |
| `import_netlist` | 网表 / BOM 导入 | `false` | `run_etl_pipeline` |
| `submit_hitl_decision` | 提交领域审批结论 | `false` | `HITLManager.approve/reject` |

设计原则：

- 参数使用业务语义（`refdes`、`net_name`、`voltage`），不暴露 Cypher
- `diagnose_fault` 内部可串行多步，减少往返
- `query_graph` 保留为通用逃生口，避免能力被封死
- 工具数量控制在 8，降低模型选择噪声

> **实施说明（2026-10-23）**：
> 1. 2 个写工具仅当 `SCHEMATIC_ENABLE_WRITE_TOOLS=1` 时注册，默认只暴露 6 个只读工具（实测 `=0` 时注册数为 6）；
> 2. `search_knowledge` 实走 FastAPI `/api/v1/knowledge/search`（HTTP 能力复用），未在 MCP 进程内直连 ChromaDB / GraphRAG；
> 3. 工具异常统一转成 `[scope-denied]`/错误文本返回，避免 MCP SDK 把堆栈折叠成无信息错误。

---

## 7. 审批设计（L1 / L2）

### L1：Hermes 审批门（动作授权）

- 依据 MCP 工具 `readOnlyHint` 自动分级
- 写工具（`readOnlyHint != true`）在任何传输动作前触发审批
- 审批系统异常时 **fail-closed**，直接阻断
- 通道：SSE `approval.request` + `POST /v1/runs/{run_id}/approval`
- 选项：`once` / `session` / `always` / `deny`
- 生产 profile 禁止 `--yolo` 与全局 auto-approve

### L2：领域 HITL（工程结论）

- 沿用 `hitl_workflow.py`，状态持久化 Neo4j
- 覆盖：审查项确认、AMR 参数确认、Datasheet 抽取确认、BOM 问题确认
- Hermes 只能通过 `submit_hitl_decision` 提交结论，不能跳过
- 审计字段：提交人、时间、结论、意见、关联对象

### 为什么不能合并

Hermes 审批是一次阻塞问答，默认 5 分钟超时、四个固定选项，不携带业务数据、不做多步状态、不落业务审计。领域 HITL 需要状态机与可追溯性，二者语义不同。

---

## 8. 记忆与数据边界

| 类型 | 存放位置 | 权威性 |
|---|---|---|
| 会话对话记忆 | Hermes session store | 临时 |
| 用户偏好 / 习惯 | Hermes memory | 参考 |
| 工程事实（器件、网络、电压） | Neo4j | **唯一权威** |
| 知识库文档 | ChromaDB + Neo4j 向量索引 | **唯一权威** |
| 审批审计 | Neo4j | **唯一权威** |

约束：

- Hermes 记忆不得覆盖或推断工程事实
- 工具返回值为工程事实的唯一入口
- 矛盾时以工具返回为准，并要求 Agent 重新查询

---

## 9. 模型配置

独立 profile `schematic`：

```yaml
model:
  provider: custom
  default: DeepSeek-V4.1-Flash        # 1M 上下文，适合长轨迹
  base_url: https://oneapi-comate.baidu-int.com/v1
fallback_providers:
  - provider: custom
    model: gpt-5.6-sol                # ~90 万上下文
compression:
  threshold: 0.8
```

- 不使用本地 Bonsai 作为主回路模型（工具选择稳定性不足）
- Hermes 版本锁定，升级单独灰度

---

## 10. 迁移阶段

| 阶段 | 内容 | 退出条件 |
|---|---|---|
| **P0** | 抽 MCP Server：工具聚合封装、`readOnlyHint` 注解、项目校验 | 独立进程跑通只读工具，现网零改动 |
| **P1** | 建独立 Hermes profile，接 MCP，打通审批链路 | 写工具审批端到端可用 |
| **P2** | FastAPI 引入 `AgentEngine`，Hermes 灰度 10% → 50% → 100%（**进行中**：代理 + 审批卡片 + 会话绑定 + 灰度开关/自动回退已就绪） | 灰度期无回退触发 |
| **P3** | 双跑对比评测 | 通过验收门 |
| **P4** | 移除 `AgentOrchestrator` / `ReActAgent` | 验收通过且稳定 2 周 |

### 灰度维度

按项目分流（而非按用户），保证同一项目内行为一致，便于对比。

---

## 11. 验收门

| 指标 | 阈值 | 性质 |
|---|---|---|
| 跨项目数据泄漏 | 0 | 一票否决 |
| 写工具审批触发率 | 100% | 一票否决 |
| 审批漏放（未审批即执行） | 0 | 一票否决 |
| 端到端任务成功率 | ≥ 旧引擎 | 硬门 |
| P95 延迟 | ≤ 旧引擎 1.5× | 硬门 |
| 领域 HITL 状态丢失 | 0 | 硬门 |
| Hermes 故障自动回退成功率 | 100% | 硬门 |
| 工具调用参数错误率 | ≤ 5% | 观察项 |

---

## 12. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 双 Agent 套娃 | 延迟翻倍、行为不可控 | Hermes 独占编排权，旧引擎仅在 HermesEngine 整体失败时接管 |
| Hermes 升级漂移 | 行为突变 | 锁版本 + 独立 profile + 升级灰度 |
| 审批卡片未渲染 | 任务静默卡死 | SSE 必须消费 `approval.request`；`approvals.timeout` 收敛；超时明确报错 |
| `readOnlyHint` 误标 | 写操作绕过审批 | 工具标注由服务端代码固定，不读外部配置；CI 校验 |
| MCP 连接中断 | 工具不可用 | Hermes 内置熔断；FastAPI 侧健康检查 |
| 长上下文成本 | 费用上升 | `compression.threshold=0.8`；工具返回统一截断 |
| LLM 自选 project_id | 跨项目误操作 | 会话绑定项目 + 服务端交叉校验 + 拒绝越界 |

---

## 13. P0 交付物

```
hardware_ai_expert/mcp_server/
├── __init__.py
├── project_guard.py      # 项目边界绑定与校验
├── tools.py              # 8 个业务级工具适配层（复用现有实现）
├── server.py             # FastMCP 入口，注解与注册
├── requirements-mcp.txt
└── README.md
```

验收：

1. 独立 Python 环境可启动，不依赖 `.venv`（py3.8）
2. `tools/list` 返回 8 个工具及正确注解
3. 每个只读工具对真实 Neo4j 调用成功
4. 越界项目请求被拒绝
5. 现有 FastAPI / Streamlit / Agent 链路零改动

---

## 14. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 初版设计，P0 启动 |

---

## P0 实施结果（2026-10-23）

**已交付**：`hardware_ai_expert/mcp_server/`（`server.py` / `tools.py` / `project_guard.py` / `README.md` / `requirements-mcp.txt`）+ `scripts/mcp_smoke_test.py` + `.venv-mcp`（CPython 3.12.14，mcp 2.x）。

**验证（legacy 项目，12,688 器件 / 8,159 网络 / 49,570 引脚）**：

| 工具 | 耗时 | 结果 |
|---|---|---|
| project_overview | 0.3s | 统计与类型分布正常 |
| query_graph (component_nets / power_tree) | 0.1–0.4s | 正常，power_tree 超长自动截断 |
| trace_signal (discover) | 5.3s | 448 个差分对 |
| diagnose_fault (power_chain) | 0.1s | 正常 |
| run_review | ~10s | 1,724 违规（ERROR 664 / WARNING 529 / INFO 531） |
| search_knowledge | 6.7s | 走 `/api/v1/knowledge/search`，Tier1 命中 |

越界项目访问返回 `[scope-denied]`；现网代码零改动（git status 仅新增未跟踪文件）。

**实施中修正的三个设计问题**：

1. **`default` 会退化为全库查询**（`get_graph_summary` 中 `pid == "default"` → `true`）。与“一会话一项目”冲突，已在 `project_guard` 中把 `default`/`all`/`*` 列为保留值禁止绑定。
2. **工具异常被 SDK 折叠**：`ProjectScopeError` 抛出后客户端只看到 `Error executing tool xxx`，原因丢失。改为工具内捕获并返回结构化 `[scope-denied]` 文本，模型可自我纠正。
3. **stdout 污染 JSON-RPC**：`review_engine/engine.py:77` 等处的 `print` 直接写 stdout，导致客户端 `Failed to parse JSONRPC message`。已在 `server.quiet` 中对全部工具执行期重定向 stdout→stderr。

**依赖策略调整**：`search_knowledge` 不在 MCP 进程内加载 `sentence-transformers`/torch（避免重复 2GB 依赖与每进程模型加载），改为调用现有 FastAPI `/api/v1/knowledge/search`。MCP 侧保持轻依赖：`mcp`、`neo4j`、`python-dotenv`、`langchain-core`。

**P1 待办**：写工具注册与 Hermes 审批联调、HTTP/streamable 传输、会话级项目路由、Hermes profile 装配、SSE 审批卡片前端。


---

## P1 联调记录（2026-10-23）

**落地形态**：独立 Hermes profile `schematic`（`/data/hermes/profiles/schematic`），MCP server 以 stdio 方式注册在 `mcp_servers.schematic`，`trust: untrusted`。

**HTTP 接入**：Hermes 一机一网关，secondary profile 不单独监听，而是被 default 监听器镜像到
`http://127.0.0.1:8642/p/schematic/v1`。前提：
1. default profile 的 `platforms.api_server` 启用（host/port/key）；
2. 该 profile 的 `.env` 里写 `API_SERVER_KEY`（镜像鉴权读 env，不读 config 的 `extra.key`）。

**审批链路已验证**：`POST /v1/runs` → SSE `/v1/runs/{id}/events` 收到 `approval.request`（含 `request_id`、`choices`）→ `POST /v1/runs/{id}/approval` → 工具执行/拦截。拒绝与批准两条路径均实测。

**工具集**：只读 6 个默认注册；写工具 2 个需 `SCHEMATIC_ENABLE_WRITE_TOOLS=1`，且因无 `readOnlyHint=true` 而强制走审批（未知 annotation 视为写能力，fail-safe）。

---

## 15. P1 实施结果（2026-10-23）

### 15.1 交付清单

| 层 | 交付物 | 状态 |
|---|---|---|
| MCP | `hardware_ai_expert/mcp_server/`（6 只读 + 2 写门控）、`.venv-mcp`（py3.12） | ✅ 已合入 `work/legacy-tasks-20260704` |
| 领域修复 | `hitl_workflow.py`：`load_pending` + 项目作用域 + 不再谎报成功 | ✅ `a925cda` |
| Hermes | 独立 profile `schematic`、MCP 注入、共享监听器镜像 `/p/schematic/v1` | ✅ 本机（`127.0.0.1:8642`） |
| 后端 | `api/routers/agent_runs.py`：运行代理 + SSE 透传 + 审批转发 + 会话绑定 + 灰度/健康 | ✅ `d858d59` 起 |
| 前端 | `types/agent.ts`、`api/agent.ts`、`ApprovalCard.tsx`、`ChatContainer` 引擎切换 | ✅ 构建通过、浏览器 E2E 通过 |

### 15.2 接口契约（产品侧）

前端**不直连** Hermes，一律走 FastAPI，网关密钥只留服务端。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/agent/runs` | 创建 run；body：`input` / `session_id?` / `user_id?` / `project_id?` / `model?` |
| GET | `/api/v1/agent/runs/{run_id}/events` | SSE 事件流（原样透传，`X-Accel-Buffering: no`） |
| POST | `/api/v1/agent/runs/{run_id}/approval` | body：`choice`（`once`/`session`/`always`/`deny`）/ `request_id` |
| GET | `/api/v1/agent/runs/{run_id}` | 查询状态与最终 `output` |
| GET | `/api/v1/agent/health` | `{enabled, upstream, detail, bound_project, base_url}` |

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HERMES_API_BASE` | `http://127.0.0.1:8642/p/schematic/v1` | 网关镜像基址 |
| `HERMES_API_KEY` | 空 → 回落读 profile `.env` 的 `API_SERVER_KEY` | 服务端鉴权 |
| `HERMES_BOUND_PROJECT` | `legacy` | 部署级项目白名单，不一致即 409 |
| `HERMES_ENGINE_ENABLED` | `1` | 灰度总开关；`0` 时 `/runs` 返回 503、前端置灰 |
| `HERMES_SESSION_TTL` | `86400` | 会话→项目绑定 TTL（秒） |

### 15.3 事件契约（实测）

`message.delta{delta}` / `tool.started{tool,preview}` / `tool.completed{tool,duration,error}` / `reasoning.available{text}` / `approval.request{...}` / `approval.responded{choice,request_id,resolved}` / `run.completed{output,...}`

`approval.request` **实际字段**（重要偏差）：

```
{command, description, pattern_key: "mcp_elicitation", pattern_keys: [...],
 request_id, choices: ["once","session","always","deny"], event, run_id, timestamp}
```

**没有 `tool` 字段** —— 前端只能用前一条 `tool.started.tool` 配对工具名（当前实现即如此）。如果未来 Hermes 增加该字段，应优先使用。

### 15.4 审批时序与超时

```
前端 ──POST /runs──────────────▶ FastAPI ──POST /runs──▶ Hermes
前端 ◀─SSE approval.request──── FastAPI ◀──SSE────────── Hermes   （tool.started 后）
     └─ 渲染审批卡片（工具名 + 倒计时 180s）
用户点「仅本次允许」 → POST /runs/{id}/approval{choice:once,request_id}
Hermes 收到 → approval.responded{resolved:1} → 工具真执行
deny / 超时 → 工具不执行，模型收到 “user did not approve … NOT run”
```

- 前端超时（180s）自动提交 `deny`，卡片标记 `expired`；**任何情况下都不会自动放行**
- 后端 SSE `read` 超时 600s，避免模型思考期被误断
- 非交互调用（`hermes -q --oneshot`）由 Hermes 自动拒绝（fail-closed）

### 15.5 灰度与回退

- 前端 Chat 头部引擎切换：`经典引擎`（默认，现有 ReAct/WS 链路）/ `Hermes 引擎`
- `GET /agent/health` 决定 Hermes 选项是否可用；网关不可用时按钮置灰并显示原因
- 自动回退：`/runs` 返回 502/503/504、SSE 建连失败、`灰度未开启` → 前端插一条提示消息并**立即改走经典引擎重试**，无需用户干预
- 回退不影响既有链路：`/api/v1/chat`、`/ws/chat` 代码零改动

### 15.6 与设计的偏差（需知）

| 设计 | 实际 | 原因 |
|---|---|---|
| 会话键放 `X-Hermes-Session-Id` 头 | 放 `POST /runs` body 的 `session_id` | Hermes 该 API 只认 body 字段 |
| 8 工具全部注册 | 6 只读 + 2 写（门控） | 写能力默认关闭，最小权限 |
| MCP 生产走 HTTP | 当前 stdio | HTTP 传输层尚未实现，stdio 已满足单机部署 |
| `search_knowledge` 直连 GraphRAG | 走 FastAPI HTTP 能力 | 复用现网实现，避免在 MCP 进程重建客户端 |
| 审批卡片「后端超时收敛」 | 前端 180s 超时 + 后端透传 | 后端不做超时裁决，避免与 Hermes 会话状态竞争 |

### 15.7 已知风险（待处理）

1. **Hermes 工具面过宽**：`schematic` profile 目前仍带 `terminal` / 文件系统等内置工具，实测模型会 SSH 回宿主机核查（已观察到 `terminal` 调用 2s）。生产前应 `agent.enabled_toolsets` 收敛到 `mcp` 最小集，否则等于把宿主机 shell 交给模型。
2. **会话绑定表在进程内**：uvicorn 多 worker / 多副本会失效，需 Redis。
3. ~~审批卡片与消息合并~~：已改为 `approvals: ApprovalState[]`，按 `request_id` 渲染多张卡片并各自结算（2026-10-23 修复）。
4. 设计文档第 9 节模型配置仍写旧值，需按 `schematic` profile 实际的 `DeepSeek-V4.1-Flash` 配置更新。
