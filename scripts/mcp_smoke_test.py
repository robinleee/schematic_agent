"""MCP Server 冒烟测试。

用法：
    cd /data/schematic_agent/hardware_ai_expert
    PYTHONPATH=. ../.venv-mcp/bin/python ../scripts/mcp_smoke_test.py [project_id]
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
HARDWARE_DIR = REPO_ROOT / "hardware_ai_expert"
PYTHON = REPO_ROOT / ".venv-mcp/bin/python"


async def main(project_id: str) -> int:
    env = dict(os.environ)
    env["SCHEMATIC_PROJECT_ID"] = project_id
    env["PYTHONPATH"] = str(HARDWARE_DIR)
    env.pop("SCHEMATIC_ENABLE_WRITE_TOOLS", None)

    params = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "mcp_server.server"],
        env=env,
        cwd=str(HARDWARE_DIR),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"工具数量: {len(tools.tools)}")
            for tool in tools.tools:
                ann = tool.annotations
                ro = getattr(ann, "read_only_hint", None) if ann else None
                print(f"  - {tool.name:24s} read_only={ro}")

            print("\n[1] project_overview")
            result = await session.call_tool("project_overview", {})
            text = result.content[0].text
            print(text[:300].replace("\n", " | "))
            assert project_id in text, "返回结果缺少项目标记"

            print("\n[2] query_graph / i2c_devices")
            result = await session.call_tool("query_graph", {"query_type": "i2c_devices"})
            print(result.content[0].text[:300].replace("\n", " | "))

            print("\n[3] 越界项目校验")
            result = await session.call_tool(
                "project_overview", {"project_id": "__other_project__"}
            )
            text = result.content[0].text
            print(text[:200].replace("\n", " | "))
            assert "scope-denied" in text, "越界访问未被拒绝"

            print("\n✅ 冒烟测试通过")
    return 0


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "HW7.0"
    raise SystemExit(asyncio.run(main(pid)))
