"""MCP Server 入口。

启动：
    SCHEMATIC_PROJECT_ID=proj_xxx \
    /data/schematic_agent/.venv-mcp/bin/python -m mcp_server.server

stdio 传输，供 Hermes 等 MCP 客户端拉起。
"""

from __future__ import annotations

import contextlib
import functools
import os
import sys

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
2. 先调用 project_overview 了解项目规模，再按需深入。
3. 结构类问题用 query_graph，连通性用 trace_signal，故障定位用 diagnose_fault。
4. 芯片规格与设计规范用 search_knowledge；规则合规结论只能来自 run_review。
5. 不要臆测器件、网络或电压；工具未返回的事实应视为未知。
"""


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
    server.add_tool(quiet(tools.query_graph), name="query_graph", annotations=READ_ONLY)
    server.add_tool(
        quiet(tools.trace_signal), name="trace_signal", annotations=READ_ONLY
    )
    server.add_tool(
        quiet(tools.diagnose_fault), name="diagnose_fault", annotations=READ_ONLY
    )
    server.add_tool(quiet(tools.run_review), name="run_review", annotations=READ_ONLY)
    server.add_tool(
        quiet(tools.search_knowledge), name="search_knowledge", annotations=READ_ONLY
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
