"""MCP Server 入口。

启动：
    SCHEMATIC_PROJECT_ID=proj_xxx \
    /data/schematic_agent/.venv-mcp/bin/python -m mcp_server.server

stdio 传输，供 Hermes 等 MCP 客户端拉起。
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import sys
import time

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mcp_server import tools

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)

INSTRUCTIONS = """schematic_agent 硬件原理图专家能力。

使用约定：
1. 所有工具都作用于当前会话绑定的项目，无需传 project_id。
2. 故障定位/“帮我找根因”：**第一步就是** diagnose_fault(mode="root_cause")。
   它一次返回：上游供电关系、网络级上游链（含串联器件与上游网络器件清单）、
   反馈分压网络（上/下臂阻值、分压比、反推 Vref 与是否自洽）、输出网络负载、
   可疑度排序。多数问题一次调用即可作答，不需要先跑 project_overview，
   也不需要再用 query_graph 手工拼拓扑。
3. 结构类问题用 query_graph，连通性用 trace_signal。
   一次要多个对象就用 refdes_list / net_name_list；查一个器件周围的电路用
   query_type="neighborhood"（一次拿到它的网络 + 网络上的器件），不要逐网络遍历。
4. 芯片规格与设计规范用 search_knowledge；规则合规结论只能来自 run_review。
   **诊断类问题不要调用 run_review**，它不是故障定位工具。
5. 同一工具同一参数不要重复调用；重复调用只会拿回同样的内容。
6. 不要臆测器件、网络或电压；工具未返回的事实应视为未知。
"""

# 相同参数的重复调用直接命中缓存：既省一次工具往返，也在返回里明确提示模型
# 「结果未变，别再来一次」。TTL 内数据不变（工具全部只读）。
_DEDUPE_TTL = float(os.getenv("SCHEMATIC_MCP_DEDUPE_TTL", "900"))
_DEDUPE_MAX = int(os.getenv("SCHEMATIC_MCP_DEDUPE_MAX", "200"))
_dedupe_cache: dict = {}


def dedupe(name: str, fn):
    """按「工具名 + 参数」缓存只读结果，重复调用返回提示 + 上次结果。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            key = (name, json.dumps([args, kwargs], sort_keys=True, default=str))
        except (TypeError, ValueError):
            return fn(*args, **kwargs)

        hit = _dedupe_cache.get(key)
        now = time.time()
        if hit and now - hit[0] < _DEDUPE_TTL:
            result, count = hit[1], hit[2] + 1
            _dedupe_cache[key] = (hit[0], result, count)
            return (
                f"[repeat-call | tool={name} | 相同参数第 {count} 次]"
                "结果与上次完全相同，已在上下文中；请直接使用该结果继续推理，"
                "不要再重复调用同一工具。\n\n" + result
            )

        result = fn(*args, **kwargs)
        if isinstance(result, str):
            if len(_dedupe_cache) >= _DEDUPE_MAX:
                _dedupe_cache.pop(next(iter(_dedupe_cache)))
            _dedupe_cache[key] = (now, result, 1)
        return result

    return wrapper


def quiet(fn):
    """把工具执行期间的标准输出重定向到 stderr。

    MCP stdio 传输以 stdout 为 JSON-RPC 线缆，而项目内存在大量 ``print``
    调试输出（例如 ``[RuleConfig] 已加载 24 条规则配置``），一旦落到
    stdout 就会污染协议流、导致客户端解析失败。在这里统一堵住。
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with contextlib.redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)

    return wrapper


def build_server() -> MCPServer:
    server = MCPServer(name="schematic-agent", instructions=INSTRUCTIONS)

    server.add_tool(
        quiet(tools.project_overview), name="project_overview", annotations=READ_ONLY
    )
    server.add_tool(
        quiet(dedupe("query_graph", tools.query_graph)),
        name="query_graph",
        annotations=READ_ONLY,
    )
    server.add_tool(
        quiet(dedupe("trace_signal", tools.trace_signal)),
        name="trace_signal",
        annotations=READ_ONLY,
    )
    server.add_tool(
        quiet(dedupe("diagnose_fault", tools.diagnose_fault)),
        name="diagnose_fault",
        annotations=READ_ONLY,
    )
    server.add_tool(
        quiet(dedupe("run_review", tools.run_review)),
        name="run_review",
        annotations=READ_ONLY,
    )
    server.add_tool(
        quiet(dedupe("search_knowledge", tools.search_knowledge)),
        name="search_knowledge",
        annotations=READ_ONLY,
    )

    if tools.WRITE_TOOLS_ENABLED:
        server.add_tool(
            quiet(tools.import_netlist), name="import_netlist", annotations=WRITE
        )
        server.add_tool(
            quiet(tools.submit_hitl_decision),
            name="submit_hitl_decision",
            annotations=WRITE,
        )

    return server


def main() -> None:
    server = build_server()
    transport = os.getenv("SCHEMATIC_MCP_TRANSPORT", "stdio").lower()
    server.run(transport=transport)


if __name__ == "__main__":
    main()
