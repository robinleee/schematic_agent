"""ReAct 失败态判定回归测试。

背景：LLM 选到不存在的工具时，历史实现只把正文换成「## 处理异常」，
status 仍是 success，导致灰度基线 / 验收门把失败算成成功
（2026-10-28 的 C1+C2 基线里，legacy C2 只回 21 字却被记为成功）。
这里锁住「无效工具 → status=error」这一行为。
"""
from __future__ import annotations

import os
import sys

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

from agent_system.react_agent import ALL_TOOLS, TOOL_SCHEMAS, ReActAgent


class _InvalidToolLLM:
    """chat_json 返回一个不存在的 action。"""

    def chat_json(self, **kwargs):  # noqa: D102
        return {"thought": "想调用一个不存在的工具", "action": "no_such_tool", "action_input": {}}

    def chat(self, **kwargs):  # noqa: D102
        return None


class _ValidFinalLLM:
    """正常收敛：直接给 final_answer。"""

    def chat_json(self, **kwargs):  # noqa: D102
        return {
            "thought": "信息足够",
            "action": "final_answer",
            "final_answer": "## 结论\n\n一切正常，未发现异常。" * 5,
            "is_final": True,
        }

    def chat(self, **kwargs):  # noqa: D102
        return None


def _bare_agent(llm) -> ReActAgent:
    agent = ReActAgent.__new__(ReActAgent)  # 跳过 __init__（不建真实 LLM 客户端）
    agent.llm = llm
    agent.tool_schemas = TOOL_SCHEMAS
    agent.tool_map = ALL_TOOLS
    return agent


def test_invalid_tool_decision_is_error():
    agent = _bare_agent(_InvalidToolLLM())
    decision = agent._llm_decide("测试", "", "", force_final=False)

    assert decision.action == "final_answer"
    assert decision.is_final is True
    assert decision.is_error is True
    assert "无效工具" in decision.thought
    assert "处理异常" in (decision.final_answer or "")


def test_invalid_tool_run_status_is_error():
    """_run_single 必须把决策失败上报为 status=error，而不是 success。"""
    agent = _bare_agent(_InvalidToolLLM())
    result = agent._run_single("U20187 输出电压异常，帮我定位根因", "diagnosis")

    assert result["status"] == "error"
    assert result["error"]
    assert "无效工具" in result["error"]


def test_valid_final_answer_stays_success():
    agent = _bare_agent(_ValidFinalLLM())
    decision = agent._llm_decide("测试", "", "", force_final=False)
    assert decision.is_error is False

    result = agent._run_single("解释一下差分对", "query")
    assert result["status"] == "success"
    assert result["error"] is None


@pytest.mark.parametrize(
    "text,ok",
    [
        ("## 处理异常\n\nLLM 选择了无效工具。", False),
        ("## 处理失败\n\nLLM 决策调用失败，请检查模型服务状态。", False),
        ("## 审查报告\n\n" + "共检测到 1724 条违规，其中 ERROR 664 条。" * 5, True),
    ],
)
def test_bench_report_markers(text, ok):
    """bench_engines.assess_report 要能识别失败占位正文。"""
    import importlib.util

    script = ROOT / "scripts" / "bench_engines.py"
    spec = importlib.util.spec_from_file_location("bench_engines_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    usable, _why = module.assess_report(text, "diagnosis")
    assert usable is ok
