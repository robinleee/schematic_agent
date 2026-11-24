"""schematic_agent MCP Server（P0）。

将现有确定性能力聚合为 8 个业务级工具，供 Hermes Agent 通过 MCP 调用。
本模块不重写任何专业逻辑，只做参数整形、项目边界校验与返回裁剪。
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
