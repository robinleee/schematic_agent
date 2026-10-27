# MCP Server — schematic_agent

把已有能力以 MCP 工具形式暴露给 Hermes 等 Agent 运行时。**只做适配，不重写专业逻辑。**

## 启动

```bash
cd /data/schematic_agent/hardware_ai_expert
SCHEMATIC_PROJECT_ID=legacy \
SCHEMATIC_API_BASE=http://127.0.0.1:8501 \
  /data/schematic_agent/.venv-mcp/bin/python -m mcp_server.server
```

stdio 传输。环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SCHEMATIC_PROJECT_ID` | 无（必填） | 会话绑定项目，见下文隔离规则 |
| `SCHEMATIC_API_BASE` | `http://127.0.0.1:8501` | 现有 FastAPI 后端，供 `search_knowledge` 调用 |
| `SCHEMATIC_ENABLE_WRITE_TOOLS` | `0` | 置 1 才注册 `import_netlist` / `submit_hitl_decision` |
| `SCHEMATIC_MCP_MAX_RESULT_CHARS` | `6000` | 单次返回上限，超出截断 |

## 工具面（6 只读 + 2 写）

| 工具 | 说明 | readOnlyHint |
|---|---|---|
| `project_overview` | 项目规模、器件类型分布、电源域 | true |
| `query_graph` | component_nets / net_components / i2c_devices / power_tree / neighborhood | true |
| `trace_signal` | path / pin / pair / discover | true |
| `diagnose_fault` | power_chain / root_cause / power_sequence / common_cause / common_cause_graph / risk_score | true |
| `run_review` | 规则审查引擎全量跑批，返回违规统计 | true |
| `search_knowledge` | GraphRAG 四级路由，走现有 `/api/v1/knowledge/search` | true |
| `import_netlist` | ETL 导入（默认不注册） | false |
| `submit_hitl_decision` | 领域 HITL 审批（默认不注册） | false |

## query_graph 的批量与子图（2026-10-27）

单对象查询在故障诊断里要逐网络手工遍历（U20187 需 1+19 次调用），
而实测每次工具往返 ≈3.6s（`logs/agent_runs.jsonl` 拟合：duration ≈ 4.8s + 3.6s×tools）。
因此 `query_graph` 增加三条低轮次路径，旧参数行为完全不变：

| 用法 | 入参 | 说明 |
|---|---|---|
| 批量器件 | `refdes_list: string[]` | 一次返回多个器件的引脚-网络，每个器件结构与单值版一致 |
| 批量网络 | `net_name_list: string[]` | 一次返回多个网络的器件；>100 器件的网络按 PartType 聚合（同旧策略） |
| 子图 | `query_type="neighborhood"` + `refdes`、`depth`(1-3，默认 2)、`max_nets`(默认 40)、`max_pins`(默认 300) | 器件自身引脚-网络 → 这些网络上的其它器件（refdes/part_type/mpn/value/voltage）→ depth=3 追加邻居的其它网络 |

约定：

- 新路径返回**紧凑 JSON**（首行 `[project=.. | tool=..]`，第二行起为单行 JSON）。
- 单值路径（`refdes=` / `net_name=` 各一个）**仍返回原文本格式**，逐字符不变。
- 任何裁剪都会置 `truncated: true`，并在 `stats` 给出真实总量（`pin_total` / `net_total`
  / `peers_total` / `by_type` 分布），模型据此知道「没返回 ≠ 不存在」。
- 体量上限：`SCHEMATIC_MCP_MAX_JSON_CHARS`（默认 16000）；超出时先删邻居明细，
  再删网络明细，始终保证 JSON 合法（不做字符串硬截断）。
- 批量最多 50 个对象（`input_truncated: true` 表示被截）。

实测（legacy / U20187）：旧方式 20 次调用 8697B；`neighborhood` 1 次调用 11673B，
19/19 网络、19/19 引脚、53/59 具名邻居（其余 6 个在 `by_type` 里仍可见）。
对比脚本：`scripts/mcp_query_bench_u20187.py`。

## 项目隔离

- 一个 MCP 进程绑定一个项目，`project_id` 由启动方注入，**不由 LLM 决定**。
- 工具调用传入不一致的 `project_id` → 返回 `[scope-denied]` 文本，不抛异常（异常会被 SDK 折叠成无信息的 `Error executing tool`，模型无法自我纠正）。
- `default` / `all` / `*` 为保留值：在 Neo4j 层表示“未选定项目”，查询会退化为全库统计，因此禁止绑定。

## 注意

- 工具执行期间 `stdout` 被重定向到 `stderr`（`server.quiet`）。项目内大量 `print` 调试输出若落到 stdout 会污染 JSON-RPC 线缆。
- `search_knowledge` 依赖现有 FastAPI 后端在跑；后端不可用时返回明确错误，不静默降级。
- 返回统一带头 `[project=<id> | tool=<name>]`，便于审计与串话排查。

## 冒烟测试

```bash
cd /data/schematic_agent/hardware_ai_expert
PYTHONPATH=. ../.venv-mcp/bin/python ../scripts/mcp_smoke_test.py legacy
```
