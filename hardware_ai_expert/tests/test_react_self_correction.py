import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

from agent_system.react_agent import ReActAgent


def test_self_correction_relaxes_empty_parameters():
    agent = ReActAgent()
    calls = []

    def fake_tool(**kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("exact") is True:
            return "未找到结果"
        return "找到 1 个结果"

    agent.tool_map["fake_tool"] = fake_tool
    trace = []
    observation = agent._execute_tool("fake_tool", {"name": "U1", "exact": True, "limit": 1})
    corrected, retries = agent._self_correct_tool_call(
        "fake_tool", {"name": "U1", "exact": True, "limit": 1}, observation, trace, 1
    )

    assert retries == 1
    assert corrected == "找到 1 个结果"
    assert calls[0]["exact"] is True
    assert calls[1]["exact"] is False
    assert calls[1]["limit"] == 10
    assert trace[0].action == "self_correction:fake_tool"
