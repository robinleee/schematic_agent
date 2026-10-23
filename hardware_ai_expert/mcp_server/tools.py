"""业务级工具适配层。

原则：
- 只做参数整形、项目边界校验、返回裁剪
- 不重写任何专业逻辑，全部复用 ``agent_system`` 现有实现
- 工具签名即 LLM 可见契约，参数使用业务语义（refdes / net_name / voltage）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
HARDWARE_DIR = REPO_ROOT / "hardware_ai_expert"
if str(HARDWARE_DIR) not in sys.path:
    sys.path.insert(0, str(HARDWARE_DIR))

from agent_system import graph_tools  # noqa: E402
from mcp_server.project_guard import ProjectScopeError, resolve_project  # noqa: E402

MAX_RESULT_CHARS = int(os.getenv("SCHEMATIC_MCP_MAX_RESULT_CHARS", "6000"))

WRITE_TOOLS_ENABLED = os.getenv("SCHEMATIC_ENABLE_WRITE_TOOLS", "0").lower() in (
    "1",
    "true",
    "yes",
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _bind_project(project_id: str) -> str:
    """解析并绑定项目，同步到 graph_tools 的全局上下文。"""
    pid = resolve_project(project_id)
    graph_tools.set_current_project(pid)
    return pid


def _guard(tool: str, project_id: str) -> tuple[str, str]:
    """解析项目；越界时返回可被模型理解的拒绝结果，而不是抛异常。

    MCP 客户端拿到的异常会被 SDK 折叠成 "Error executing tool xxx"，
    丢失具体原因；这里显式转成结构化文本，便于 Agent 自我纠正。
    """
    try:
        return _bind_project(project_id), ""
    except ProjectScopeError as exc:
        return "", (
            f"[scope-denied | tool={tool}] {exc}\n"
            "说明：当前会话已绑定固定项目，不能跨项目查询。"
            "如需访问其他项目，请新建会话。"
        )


def _invoke(tool_obj, args: dict) -> str:
    """调用 LangChain StructuredTool 并统一转为字符串。"""
    result = tool_obj.invoke(args)
    if isinstance(result, str):
        return result
    return str(result)


def _format(pid: str, tool: str, body: str) -> str:
    """统一返回格式：项目标签 + 截断。"""
    text = body.strip()
    truncated = False
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n\n[结果已截断，如需细节请缩小查询范围]"
        truncated = True
    suffix = " | truncated" if truncated else ""
    return f"[project={pid} | tool={tool}{suffix}]\n{text}"


def _error(pid: str, tool: str, exc: Exception) -> str:
    return f"[project={pid} | tool={tool} | error] {type(exc).__name__}: {exc}"


def _require_write_enabled(tool: str) -> None:
    if not WRITE_TOOLS_ENABLED:
        raise PermissionError(
            f"写工具 '{tool}' 未启用。设置 SCHEMATIC_ENABLE_WRITE_TOOLS=1 后重启服务。"
        )


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------


def project_overview(project_id: str = "") -> str:
    """查看当前项目的整体概况：器件/网络规模、电源域分布、I2C 设备数量。

    回答「这个项目有多大」「有哪些电压域」这类问题时的第一个工具。
    """
    pid, denied = _guard("project_overview", project_id)
    if denied:
        return denied
    try:
        parts = [
            _invoke(graph_tools.get_graph_summary, {}),
            _invoke(graph_tools.get_power_domain, {"detail": False}),
        ]
        return _format(pid, "project_overview", "\n\n".join(parts))
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "project_overview", exc)


def query_graph(
    query_type: Literal[
        "component_nets",
        "net_components",
        "i2c_devices",
        "power_tree",
    ],
    refdes: str = "",
    net_name: str = "",
    root_refdes: str = "",
    voltage: str = "",
    project_id: str = "",
) -> str:
    """按对象查询图谱结构。

    - component_nets: 某器件连接了哪些网络（需要 refdes）
    - net_components: 某网络连接了哪些器件（需要 net_name）
    - i2c_devices: 列出所有 I2C 设备
    - power_tree: 电源树（可选 root_refdes 或 voltage 过滤）
    """
    pid, denied = _guard("query_graph", project_id)
    if denied:
        return denied
    try:
        if query_type == "component_nets":
            if not refdes:
                raise ValueError("component_nets 需要 refdes")
            body = _invoke(graph_tools.get_component_nets, {"refdes": refdes})
        elif query_type == "net_components":
            if not net_name:
                raise ValueError("net_components 需要 net_name")
            body = _invoke(graph_tools.get_net_components, {"net_name": net_name})
        elif query_type == "i2c_devices":
            body = _invoke(graph_tools.get_i2c_devices, {})
        else:
            args = {}
            if root_refdes:
                args["root_refdes"] = root_refdes
            if voltage:
                args["voltage"] = voltage
            body = _invoke(graph_tools.get_power_tree, args)
        return _format(pid, "query_graph", body)
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "query_graph", exc)


def trace_signal(
    mode: Literal["path", "pin", "pair", "discover"],
    from_refdes: str = "",
    from_pin: str = "",
    to_refdes: str = "",
    to_pin: str = "",
    start_pin: str = "",
    start_pin_id: str = "",
    signal_type: str = "",
    max_depth: int = 5,
    project_id: str = "",
) -> str:
    """追踪信号连通性与差分对。

    - path: 两个引脚之间的连通路径（需要 from_refdes/from_pin/to_refdes/to_pin）
    - pin: 从单个引脚出发的被动穿透追踪（需要 start_pin，格式 U1_A4 或 U1.A4）
    - pair: 追踪一个差分对（需要 start_pin_id）
    - discover: 发现全部差分对（可选 signal_type 过滤）
    """
    pid, denied = _guard("trace_signal", project_id)
    if denied:
        return denied
    try:
        if mode == "path":
            body = _invoke(
                graph_tools.get_signal_path,
                {
                    "from_refdes": from_refdes,
                    "from_pin": from_pin,
                    "to_refdes": to_refdes,
                    "to_pin": to_pin,
                },
            )
        elif mode == "pin":
            if not start_pin:
                raise ValueError("pin 模式需要 start_pin")
            body = _invoke(
                graph_tools.trace_signal_path,
                {"start_pin": start_pin, "max_depth": max_depth},
            )
        elif mode == "pair":
            if not start_pin_id:
                raise ValueError("pair 模式需要 start_pin_id")
            body = _invoke(
                graph_tools.trace_differential_pair, {"start_pin_id": start_pin_id}
            )
        else:
            body = _invoke(
                graph_tools.discover_diff_pairs, {"signal_type": signal_type or ""}
            )
        return _format(pid, "trace_signal", body)
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "trace_signal", exc)


def diagnose_fault(
    mode: Literal[
        "power_chain",
        "root_cause",
        "power_sequence",
        "common_cause",
        "common_cause_graph",
        "risk_score",
    ],
    refdes: str = "",
    refdes_list: str = "",
    symptom: str = "",
    direction: Literal["upstream", "downstream", "both"] = "downstream",
    max_depth: int = 5,
    project_id: str = "",
) -> str:
    """故障诊断与电源分析。

    - power_chain: 沿供电关系追踪电源链（refdes + direction + max_depth）
    - root_cause: 故障根因反向溯源（refdes + symptom）
    - power_sequence: 上电时序分析（refdes）
    - common_cause: 共因失效定位（refdes_list，逗号分隔）
    - common_cause_graph: 共因失效关系图（refdes_list）
    - risk_score: 共因失效风险评分（refdes_list）
    """
    pid, denied = _guard("diagnose_fault", project_id)
    if denied:
        return denied
    try:
        if mode == "power_chain":
            body = _invoke(
                graph_tools.trace_power_chain,
                {"refdes": refdes, "direction": direction, "max_depth": max_depth},
            )
        elif mode == "root_cause":
            body = _invoke(
                graph_tools.trace_fault_root, {"refdes": refdes, "symptom": symptom}
            )
        elif mode == "power_sequence":
            body = _invoke(graph_tools.analyze_power_sequence, {"refdes": refdes})
        elif mode == "common_cause":
            body = _invoke(graph_tools.find_common_cause, {"refdes_list": refdes_list})
        elif mode == "common_cause_graph":
            body = _invoke(
                graph_tools.get_common_cause_graph, {"refdes_list": refdes_list}
            )
        else:
            body = _invoke(
                graph_tools.common_cause_risk_score, {"refdes_list": refdes_list}
            )
        return _format(pid, "diagnose_fault", body)
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "diagnose_fault", exc)


def run_review(rule_ids: Optional[list[str]] = None, project_id: str = "") -> str:
    """执行规则审查引擎，返回违规统计与典型条目。

    rule_ids 为空则运行全部启用规则。审查结果只读，不修改数据。
    """
    pid, denied = _guard("run_review", project_id)
    if denied:
        return denied
    try:
        from agent_system.review_engine import ReviewRuleEngine  # 延迟导入

        driver = graph_tools._get_driver()
        engine = ReviewRuleEngine(driver, project_id=pid)
        violations = engine.run_rules(rule_ids=rule_ids, enabled_only=True)

        by_severity: dict[str, int] = {}
        by_rule: dict[str, int] = {}
        for item in violations:
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
            by_rule[item.rule_id] = by_rule.get(item.rule_id, 0) + 1

        lines = [f"审查完成：共 {len(violations)} 个违规"]
        lines.append(
            "按严重度：" + ", ".join(f"{k}:{v}" for k, v in sorted(by_severity.items()))
        )
        top_rules = sorted(by_rule.items(), key=lambda kv: -kv[1])[:8]
        lines.append("按规则：" + ", ".join(f"{k}:{v}" for k, v in top_rules))

        for item in violations[:10]:
            lines.append(
                f"- [{item.severity}] {item.rule_id} | {getattr(item, 'refdes', '-')} | "
                f"{getattr(item, 'message', '')}"
            )
        return _format(pid, "run_review", "\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "run_review", exc)


def search_knowledge(query: str, mpn: str = "", project_id: str = "") -> str:
    """检索知识库：GraphRAG 四级路由（图谱 → 本地 → 向量库 → 公网）+ Datasheet。

    适用于芯片规格、引脚定义、典型应用电路、设计规范等问题。
    """
    pid, denied = _guard("search_knowledge", project_id)
    if denied:
        return denied
    try:
        import json
        import urllib.request

        base = os.getenv("SCHEMATIC_API_BASE", "http://127.0.0.1:8501").rstrip("/")
        payload = {"query": query, "project_id": pid}
        if mpn:
            payload["mpn"] = mpn
        req = urllib.request.Request(
            f"{base}/api/v1/knowledge/search",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read()).get("data") or {}

        if data.get("status") != "success" or not data.get("content"):
            return _format(
                pid,
                "search_knowledge",
                f"未找到相关内容 (query={query!r}, mpn={mpn!r})",
            )
        body = (
            f"置信度: {data.get('confidence', 0):.2f}\n"
            f"来源: {data.get('tier')} / {data.get('source')}\n\n{data['content']}"
        )
        return _format(pid, "search_knowledge", body)
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "search_knowledge", exc)


# ---------------------------------------------------------------------------
# 写工具（默认关闭，P1 接入 Hermes 审批后启用）
# ---------------------------------------------------------------------------


def import_netlist(
    netlist_path: str,
    bom_path: str = "",
    project_name: str = "",
    skip_quality: bool = False,
    project_id: str = "",
) -> str:
    """导入网表 / BOM 到图数据库（写操作，需要人工审批）。"""
    pid, denied = _guard("import_netlist", project_id)
    if denied:
        return denied
    try:
        _require_write_enabled("import_netlist")
        from agent_system.etl_web_bridge import run_etl_pipeline

        file_paths = {"netlist": netlist_path}
        if bom_path:
            file_paths["bom"] = bom_path
        payload = {"file_paths": file_paths, "project_name": project_name or pid, "skip_quality": skip_quality}
        result = (
            run_etl_pipeline.invoke(payload) if hasattr(run_etl_pipeline, "invoke") else run_etl_pipeline(**payload)
        )
        return _format(pid, "import_netlist", str(result))
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "import_netlist", exc)


def submit_hitl_decision(
    review_id: str,
    decision: Literal["approve", "reject"],
    comment: str = "",
    project_id: str = "",
) -> str:
    """提交领域 HITL 审批结论（写操作，需要人工审批）。"""
    pid, denied = _guard("submit_hitl_decision", project_id)
    if denied:
        return denied
    try:
        _require_write_enabled("submit_hitl_decision")
        from agent_system.hitl_workflow import approve_review, reject_review

        fn = approve_review if decision == "approve" else reject_review
        # approve_review / reject_review 是 LangChain StructuredTool（@tool 装饰），不能直接调用
        payload = {"review_id": review_id, "comment": comment, "project_id": pid}
        raw = fn.invoke(payload) if hasattr(fn, "invoke") else fn(review_id, comment=comment, project_id=pid)
        return _format(pid, "submit_hitl_decision", str(raw))
    except Exception as exc:  # noqa: BLE001
        return _error(pid, "submit_hitl_decision", exc)
