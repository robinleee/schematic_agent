"""
端到端集成测试 — ReAct Agent 完整流程

测试场景：
1. 查询：U60140 器件信息
2. 诊断：3.3V 掉电
3. 审查：I2C 上拉检查

每个场景验证：
- Agent 不 crash（status == success）
- 至少调用 1 个工具
- report 非空且有实质内容
- 无重复工具调用
"""

import sys
import os
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from agent_system.react_agent import ReActAgent

# LLM 依赖测试标记 — 需要 Ollama 服务运行
# 跳过: pytest -m "not llm"
llm_test = pytest.mark.llm


@llm_test
@pytest.fixture(scope="module")
def agent():
    """共享 Agent 实例"""
    return ReActAgent()


class TestQueryTask:
    """查询任务端到端"""


    @llm_test
    @pytest.mark.timeout(180)
    def test_basic_component_query(self, agent):
        """基本器件查询 — 不 crash，有结果"""
        result = agent.run("U60140 是什么器件？")
        assert result["status"] == "success"
        assert result["tool_call_count"] >= 1
        assert result["report"] is not None
        assert len(result["report"]) > 50


    @llm_test
    @pytest.mark.timeout(180)
    def test_query_uses_correct_tools(self, agent):
        """查询应使用图谱工具"""
        result = agent.run("U60140 连接了哪些网络？")
        tool_names = [t["action"] for t in result["execution_trace"]]
        # 至少有一个图谱工具
        graph_tools = {"get_component_nets", "get_net_components", "get_power_tree",
                       "get_power_domain", "get_graph_summary", "analyze_power_sequence",
                       "trace_signal_path", "get_signal_path", "find_common_cause", "get_i2c_devices"}
        assert any(t in graph_tools for t in tool_names), f"No graph tool used: {tool_names}"


    @llm_test
    @pytest.mark.timeout(180)
    def test_no_duplicate_tool_calls(self, agent):
        """不应有完全重复的工具调用"""
        result = agent.run("查看 U60140 的电源连接")
        calls = [(t["action"], str(t["action_input"])) for t in result["execution_trace"]]
        # 允许同一工具不同参数，但不允许完全相同
        seen = set()
        duplicates = []
        for call in calls:
            if call in seen:
                duplicates.append(call)
            seen.add(call)
        assert len(duplicates) == 0, f"Duplicate tool calls: {duplicates}"


class TestDiagnosisTask:
    """诊断任务端到端"""


    @llm_test
    @pytest.mark.timeout(180)
    def test_power_diagnosis(self, agent):
        """电源故障诊断 — 不 crash"""
        result = agent.diagnose("3.3V 电源掉电，U60140 可能有问题")
        assert result["status"] == "success"
        assert result["tool_call_count"] >= 1
        assert result["report"] is not None


    @llm_test
    @pytest.mark.timeout(180)
    def test_diagnosis_uses_power_tools(self, agent):
        """诊断应使用电源相关工具"""
        result = agent.diagnose("U60140 的 3.3V 输出异常")
        tool_names = [t["action"] for t in result["execution_trace"]]
        power_tools = {"get_power_tree", "get_power_domain", "analyze_power_sequence",
                       "find_common_cause", "get_component_nets"}
        assert any(t in power_tools for t in tool_names), f"No power tool used: {tool_names}"


    def test_diagnosis_task_type(self, agent):
        """诊断任务类型应被正确检测"""
        from agent_system.react_agent import ReActAgent
        task_type = ReActAgent._detect_task_type("3.3V电源掉电了")
        assert task_type == "diagnosis"


class TestReviewTask:
    """审查任务端到端"""


    def test_review_task_type(self, agent):
        """审查任务类型应被正确检测"""
        from agent_system.react_agent import ReActAgent
        task_type = ReActAgent._detect_task_type("检查I2C上拉电阻是否合规")
        assert task_type == "review"


    @llm_test
    @pytest.mark.timeout(180)
    def test_review_runs(self, agent):
        """审查任务能运行"""
        result = agent.review("检查I2C上拉")
        assert result["status"] == "success"
        assert result["tool_call_count"] >= 1


class TestAgentRobustness:
    """Agent 鲁棒性测试"""


    @llm_test
    @pytest.mark.timeout(180)
    def test_empty_input(self, agent):
        """空输入不 crash"""
        result = agent.run(" ")
        assert result["status"] in ("success", "timeout")


    @llm_test
    @pytest.mark.timeout(180)
    def test_unknown_component(self, agent):
        """不存在的器件不 crash"""
        result = agent.run("U99999 是什么器件？")
        assert result["status"] in ("success", "timeout")


    @llm_test
    @pytest.mark.timeout(180)
    def test_chinese_input(self, agent):
        """中文输入正常处理"""
        result = agent.run("查看电源树拓扑")
        assert result["status"] in ("success", "timeout")


    @llm_test
    @pytest.mark.timeout(180)
    def test_mixed_language(self, agent):
        """中英混合输入"""
        result = agent.run("分析 U60140 的 power tree")
        assert result["status"] in ("success", "timeout")


    @llm_test
    @pytest.mark.timeout(180)
    def test_max_steps_limit(self, agent):
        """不应超过最大步数"""
        result = agent.run("详细分析所有电源域和信号链路")
        assert result["tool_call_count"] <= 15  # MAX_REACT_STEPS - 一些缓冲


class TestLLMJsonParsing:
    """LLM JSON 解析链路测试"""


    @llm_test
    @pytest.mark.timeout(180)
    def test_chat_json_works(self):
        """chat_json 正常工作"""
        from agent_system.llm_client import LLMClient
        client = LLMClient()
        result = client.chat_json(
            prompt='Return JSON: {"action": "test", "value": 1}',
            temperature=0.1,
            max_tokens=2048,
        )
        assert result is not None
        assert result.get("action") == "test"


    @llm_test
    @pytest.mark.timeout(180)
    def test_react_json_output(self):
        """ReAct prompt 下 LLM 输出可解析 JSON"""
        from agent_system.llm_client import LLMClient
        client = LLMClient()
        result = client.chat_json(
            prompt='Choose a tool for: "查看 U60140 的网络连接". Available: get_component_nets(refdes), get_power_tree(refdes). Respond with JSON.',
            system_prompt="You are a hardware expert. Respond ONLY with JSON.",
            temperature=0.2,
            max_tokens=2048,
        )
        assert result is not None
        assert "action" in result
