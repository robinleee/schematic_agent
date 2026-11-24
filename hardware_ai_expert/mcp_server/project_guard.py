"""项目边界绑定与校验。

P0 阶段采用「单进程单项目」模型：
进程启动时通过 ``SCHEMATIC_PROJECT_ID`` 绑定一个项目，任何工具调用都不允许越界。

P1 阶段会升级为「按会话路由」：由 Hermes 的 session id 映射到 project，
每个会话仍只绑定一个项目（见 docs/architecture/HERMES_AGENT_INTEGRATION_DESIGN.md）。
"""

from __future__ import annotations

import os


class ProjectScopeError(RuntimeError):
    """请求的项目与进程绑定项目不一致，或未指定项目。"""


# ``default`` 在 Neo4j 层表示「未选定项目」，查询会退化为全库统计，
# 与「一会话一项目」的隔离保证冲突，因此 MCP 侧禁止绑定。
_RESERVED_PROJECTS = {"default", "all", "*"}


def bound_project() -> str:
    """返回进程绑定的项目 ID，未绑定则为空字符串。"""
    return os.getenv("SCHEMATIC_PROJECT_ID", "").strip()


def resolve_project(project_id: str = "") -> str:
    """解析本次调用应使用的项目 ID。

    优先级：显式参数 > 进程绑定。
    若两者都存在且不一致，直接拒绝（防止 LLM 跨项目调用）。
    """
    requested = (project_id or "").strip()
    bound = bound_project()

    if bound:
        if bound.lower() in _RESERVED_PROJECTS:
            raise ProjectScopeError(
                f"进程绑定的项目 '{bound}' 是保留值，会退化为全库查询，请改用具体项目 ID。"
            )
        if requested and requested != bound:
            raise ProjectScopeError(
                f"项目越界：当前会话绑定 '{bound}'，请求 '{requested}'。"
                "如需访问其他项目，请新建会话。"
            )
        return bound

    if not requested:
        raise ProjectScopeError(
            "未指定项目：请设置 SCHEMATIC_PROJECT_ID 环境变量，或在调用时传入 project_id。"
        )

    if requested.lower() in _RESERVED_PROJECTS:
        raise ProjectScopeError(
            f"'{requested}' 是保留值，会退化为全库查询，不能作为会话绑定项目。"
            "请指定具体项目 ID。"
        )
    return requested


def assert_not_cross_project(actual_project: str, expected: str) -> None:
    """核验工具返回数据所属项目与期望一致。"""
    if actual_project and expected and actual_project != expected:
        raise ProjectScopeError(
            f"数据越界：返回数据属于 '{actual_project}'，期望 '{expected}'。"
        )
