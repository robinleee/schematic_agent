"""
多 Agent 编排器

专业 Agent 架构：
  - ReviewAgent: 审查专用（run_review + 电源/接口查询 + 差分对）
  - DiagnosisAgent: 诊断专用（共因失效 + 电源时序 + 信号路径）
  - QueryAgent: 查询专用（知识库 + 图谱查询 + GraphRAG）

编排策略：
  1. Intent Router 分类 → 选择专业 Agent
  2. 专业 Agent 用精简工具集 + 专属 Prompt
  3. 低置信度时 fallback 到全工具 ReAct Agent

兼容性：
  - ReActAgent 保留为 fallback（全工具模式）
  - AgentOrchestrator.run() API 与 ReActAgent.run() 一致
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

from agent_system.llm_client import LLMClient
from agent_system.llm_intent_router import LLMIntentRouter
from agent_system.react_agent import ReActAgent
from agent_system.schemas import ReActDecision, ReActTraceStep

logger = logging.getLogger(__name__)


# ============================================================
# 专业 Agent 基类
# ============================================================

class SpecializedAgent(ABC):
    """专业 Agent 基类 — 限定工具集 + 专属 Prompt"""

    name: str = ""
    description: str = ""
    tool_names: list[str] = []

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self._react = ReActAgent(llm_client=self.llm)

    @abstractmethod
    def get_system_prompt_addon(self) -> str:
        """返回专业化的 Prompt 附加指导"""

    def get_allowed_tools(self) -> set[str]:
        """返回该 Agent 允许使用的工具名集合"""
        return set(self.tool_names)

    def run(self, user_input: str, context: dict = None) -> dict:
        """执行专业 Agent 循环"""
        # 复用 ReAct Agent，但注入专业 Prompt + 限定工具
        task_type = self.name
        result = self._react.run(user_input, task_type=task_type)

        # 添加 Agent 标识
        result["agent_name"] = self.name
        return result


# ============================================================
# Review Agent
# ============================================================

class ReviewAgent(SpecializedAgent):
    """审查专用 Agent"""

    name = "review"
    description = "原理图设计审查 — 规则检查、差分对完整性、电源去耦"
    tool_names = [
        "run_review",
        "get_i2c_devices",
        "get_power_domain",
        "get_power_tree",
        "discover_diff_pairs",
        "trace_differential_pair",
        "get_component_nets",
        "get_net_components",
        "search_knowledge",
    ]

    def get_system_prompt_addon(self) -> str:
        return (
            "\n## Task Guidance: Review (Specialized)\n"
            "You are a schematic design review specialist.\n\n"
            "### Review Strategy\n"
            "1. **Scope first**: Understand what the user wants reviewed (power? I2C? ESD? diff pairs?)\n"
            "2. **Run targeted rules**: Use run_review with specific rule_ids rather than running all rules\n"
            "3. **Deep-dive on violations**: For each violation, use graph tools to understand context\n"
            "4. **Summarize**: Group violations by severity and category\n\n"
            "### Available Review Rules\n"
            "- POWER_3V3_DECAP / POWER_1V8_DECAP / POWER_5V0_DECAP: Power decoupling\n"
            "- I2C_STD_PULLUP / OPENDRAIN_PULLUP: Pull-up resistor checks\n"
            "- EXTERNAL_IO_ESD / USB_ESD_PROTECTION / ETHERNET_ESD_PROTECTION: ESD protection\n"
            "- NC_FLOATING_CHECK / FLOATING_PIN_CHECK: Floating pin checks\n"
            "- AMR_RESISTOR_POWER: Resistor power derating\n"
            "- DIFF_PAIR_MATCHING / DIFF_PAIR_TERMINATION / DIFF_PAIR_CMC: Differential pair integrity\n"
            "- POWER_NET_ORPHAN / REGULATOR_OUTPUT_DECAP / POWER_DOMAIN_ISOLATION: Power integrity\n"
            "- VOLTAGE_COMPATIBILITY: Voltage compatibility\n"
            "- SINGLE_END_NET / BUS_INTEGRITY: Connectivity checks\n\n"
            "### Decision Rules\n"
            "- ALWAYS start with run_review (with targeted rule_ids if possible)\n"
            "- After run_review, analyze 1-2 key violations with graph tools, then conclude\n"
            "- Do NOT call run_review more than once\n"
            "- Do NOT call more than 3 graph tools after run_review\n"
        )


# ============================================================
# Diagnosis Agent
# ============================================================

class DiagnosisAgent(SpecializedAgent):
    """诊断专用 Agent"""

    name = "diagnosis"
    description = "硬件故障诊断 — 电源故障、信号异常、共因分析"
    tool_names = [
        "find_common_cause",
        "common_cause_risk_score",
        "get_common_cause_graph",
        "analyze_power_sequence",
        "trace_signal_path",
        "trace_differential_pair",
        "get_component_nets",
        "get_power_tree",
        "get_power_domain",
        "search_knowledge",
    ]

    def get_system_prompt_addon(self) -> str:
        return (
            "\n## Task Guidance: Diagnosis (Specialized)\n"
            "You are a hardware failure diagnosis specialist.\n\n"
            "### Diagnosis Framework (Fault Tree Analysis)\n"
            "1. **Symptom Analysis** (1 tool call)\n"
            "   - Component-level: get_component_nets(refdes=...) → see connections\n"
            "   - Power issue: get_power_tree(refdes=...) or analyze_power_sequence(refdes=...)\n"
            "   - Signal issue: trace_signal_path(start_pin=...) or trace_differential_pair(start_pin_id=...)\n\n"
            "2. **Root Cause Hypothesis** (1-2 tool calls)\n"
            "   - Power: find_common_cause(refdes_list=...) → shared upstream\n"
            "   - Risk: common_cause_risk_score(refdes_list=...) → risk assessment\n"
            "   - Graph: get_common_cause_graph(refdes_list=...) → visualization data\n"
            "   - Specs: search_knowledge(query=...) → datasheet limits\n\n"
            "3. **Verification** (0-1 tool calls)\n"
            "   - Cross-reference with knowledge base for failure patterns\n"
            "   - Use analyze_power_sequence for PMIC sequencing issues\n\n"
            "4. **Conclusion**\n"
            "   - Root cause + evidence + recommendations\n"
            "   - Include voltage values, component refs, net names\n\n"
            "### Decision Rules\n"
            "- Do NOT call run_review (it's for design review, not failure analysis)\n"
            "- Max 4 tool calls total before concluding\n"
            "- Do NOT repeat the same tool with same parameters\n"
            "- Use find_common_cause or common_cause_risk_score when multiple components fail\n"
        )


# ============================================================
# Query Agent
# ============================================================

class QueryAgent(SpecializedAgent):
    """查询专用 Agent"""

    name = "query"
    description = "硬件知识查询 — 器件规格、网络信息、图谱结构"
    tool_names = [
        "search_knowledge",
        "get_component_nets",
        "get_net_components",
        "get_power_domain",
        "get_i2c_devices",
        "get_graph_summary",
        "discover_diff_pairs",
        "get_power_tree",
    ]

    def get_system_prompt_addon(self) -> str:
        return (
            "\n## Task Guidance: Query (Specialized)\n"
            "You are a hardware knowledge query specialist.\n\n"
            "### Query Strategy\n"
            "1. **Identify target**: Component (RefDes/MPN), Net, or general question\n"
            "2. **Look up**: Use appropriate graph tool\n"
            "   - Component → get_component_nets\n"
            "   - Net → get_net_components\n"
            "   - Power → get_power_domain / get_power_tree\n"
            "   - Specs → search_knowledge (with MPN if available)\n"
            "3. **Answer**: Clear, structured response in Chinese\n\n"
            "### Decision Rules\n"
            "- Most queries can be answered in 1-2 tool calls\n"
            "- Do NOT call more than 3 tools total\n"
            "- Provide specific data (voltages, values, pin names) not just summaries\n"
        )


# ============================================================
# Agent 编排器
# ============================================================

class AgentOrchestrator:
    """
    多 Agent 编排器

    路由策略：
    1. 关键词快速分类（复用 ReActAgent._detect_task_type）
    2. 低置信度时 fallback 到全工具 ReAct Agent

    API 兼容 ReActAgent.run()
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.agents = {
            "review": ReviewAgent(llm_client=self.llm),
            "diagnosis": DiagnosisAgent(llm_client=self.llm),
            "query": QueryAgent(llm_client=self.llm),
        }
        self.fallback_agent = ReActAgent(llm_client=self.llm)

    def run(self, user_input: str, task_type: str = "") -> dict:
        """
        路由 + 执行

        Args:
            user_input: 用户输入
            task_type: 强制指定任务类型（空=自动检测）

        Returns:
            与 ReActAgent.run() 一致的结果 dict
        """
        if not task_type:
            task_type = ReActAgent._detect_task_type(user_input)

        # 选择专业 Agent
        agent = self.agents.get(task_type)

        if agent is None:
            logger.info(f"No specialized agent for '{task_type}', using fallback")
            return self.fallback_agent.run(user_input, task_type=task_type)

        logger.info(f"Routing to {agent.name} agent")
        result = agent.run(user_input)
        result["routed_agent"] = agent.name

        # 如果结果不佳（超时/错误），尝试 fallback
        if result.get("status") == "timeout" or result.get("error"):
            logger.info(f"Specialized agent failed, trying fallback")
            fallback_result = self.fallback_agent.run(user_input, task_type=task_type)
            fallback_result["routed_agent"] = "fallback"
            fallback_result["initial_agent"] = agent.name
            return fallback_result

        return result

    # 兼容旧版 API
    def review(self, user_input: str, **kwargs) -> dict:
        return self.run(user_input, task_type="review")

    def diagnose(self, user_input: str, **kwargs) -> dict:
        return self.run(user_input, task_type="diagnosis")

    def query_spec(self, user_input: str, **kwargs) -> dict:
        return self.run(user_input, task_type="query")


# ============================================================
# Self-test
# ============================================================

if __name__ == "__main__":
    orchestrator = AgentOrchestrator()

    # 测试路由
    test_cases = [
        ("帮我审查 I2C 上拉", "review"),
        ("U60140 3.3V 无输出", "diagnosis"),
        ("查一下 U4 的电源连接", "query"),
    ]

    for user_input, expected_type in test_cases:
        detected = ReActAgent._detect_task_type(user_input)
        status = "✅" if detected == expected_type else "❌"
        print(f"  {status} '{user_input}' → {detected} (expected: {expected_type})")

    print("\n✅ Agent Orchestrator routing test passed")
