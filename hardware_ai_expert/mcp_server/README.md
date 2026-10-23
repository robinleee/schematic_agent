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
| `query_graph` | component_nets / net_components / i2c_devices / power_tree | true |
| `trace_signal` | path / pin / pair / discover | true |
| `diagnose_fault` | power_chain / root_cause / power_sequence / common_cause / common_cause_graph / risk_score | true |
| `run_review` | 规则审查引擎全量跑批，返回违规统计 | true |
| `search_knowledge` | GraphRAG 四级路由，走现有 `/api/v1/knowledge/search` | true |
| `import_netlist` | ETL 导入（默认不注册） | false |
| `submit_hitl_decision` | 领域 HITL 审批（默认不注册） | false |

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
